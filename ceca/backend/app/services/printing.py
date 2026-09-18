"""Label printing: an accumulating queue, then a traced job per run.

Nothing prints untraced. A :class:`PrintJob` row exists before any label
reaches a printer, and every reprint is a new job.
"""

from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import UTC, datetime
from math import ceil
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager

from app.deps import TenantContext, scoped, scoped_select
from app.errors import DomainError, NotFoundError
from app.models.documents import ComplianceStatus, Document, DocumentStatus
from app.models.printing import PrintJob, PrintJobItem, PrintJobStatus, PrintLayout, PrintQueueItem
from app.services import audit, quota
from app.services.documents import active_share_token
from app.services.qr import public_url, qr_svg

MIN_QR_MM = 20.0


@dataclass(frozen=True, slots=True)
class LabelTemplate:
    """A physical label sheet, in millimetres."""

    code: str
    name_es: str
    name_en: str
    layout: PrintLayout
    page_width_mm: float
    page_height_mm: float
    label_width_mm: float
    label_height_mm: float
    rows: int
    columns: int
    margin_top_mm: float = 0.0
    margin_left_mm: float = 0.0
    gutter_x_mm: float = 0.0
    gutter_y_mm: float = 0.0

    @property
    def slots(self) -> int:
        return self.rows * self.columns

    @property
    def slots_per_sheet(self) -> int:
        return self.slots

    @property
    def qr_mm(self) -> float:
        return max(MIN_QR_MM, min(self.label_width_mm, self.label_height_mm) * 0.6)

    def name(self, language: str) -> str:
        return self.name_en if language == "en" else self.name_es


TEMPLATES: dict[str, LabelTemplate] = {
    "thermal_50x30": LabelTemplate(
        code="thermal_50x30",
        name_es="Termica 50 x 30 mm",
        name_en="Thermal 50 x 30 mm",
        layout=PrintLayout.SINGLE,
        page_width_mm=50.0,
        page_height_mm=30.0,
        label_width_mm=50.0,
        label_height_mm=30.0,
        rows=1,
        columns=1,
    ),
    "a4_3x7": LabelTemplate(
        code="a4_3x7",
        name_es="A4 21 etiquetas (63,5 x 38,1 mm)",
        name_en="A4 21 labels (63.5 x 38.1 mm)",
        layout=PrintLayout.SHEET,
        page_width_mm=210.0,
        page_height_mm=297.0,
        label_width_mm=63.5,
        label_height_mm=38.1,
        rows=7,
        columns=3,
        margin_top_mm=15.15,
        margin_left_mm=7.25,
        gutter_x_mm=2.5,
    ),
    "a4_2x4": LabelTemplate(
        code="a4_2x4",
        name_es="A4 8 etiquetas (105 x 74 mm)",
        name_en="A4 8 labels (105 x 74 mm)",
        layout=PrintLayout.SHEET,
        page_width_mm=210.0,
        page_height_mm=297.0,
        label_width_mm=105.0,
        label_height_mm=74.0,
        rows=4,
        columns=2,
        margin_top_mm=0.5,
    ),
}


async def add_to_queue(
    db: AsyncSession,
    ctx: TenantContext,
    *,
    document_ids: list[UUID],
    user_id: UUID | None = None,
    copies: int = 1,
) -> list[PrintQueueItem]:
    if copies < 1:
        raise DomainError("PRINT_COPIES_INVALID", copies=copies)

    owner = user_id or ctx.user_id
    documents = await _documents_of(db, ctx, document_ids)
    for document in documents:
        _reject_unprintable(document)
    position = await _next_position(db, ctx, owner)

    items = []
    for offset, document in enumerate(documents):
        item = PrintQueueItem(
            mm_id=ctx.mm_id,
            site_id=ctx.site_id,
            user_id=owner,
            document_id=document.id,
            copies=copies,
            position=position + offset,
        )
        # Assigned, not merely keyed: the caller serialises the item with its
        # document, and the relationship refuses to lazy-load (see the model).
        item.document = document
        db.add(item)
        items.append(item)
    await db.flush()
    return items


async def list_queue(
    db: AsyncSession,
    ctx: TenantContext,
    *,
    user_id: UUID | None = None,
    offset: int | None = None,
    limit: int | None = None,
) -> tuple[list[PrintQueueItem], int]:
    """One page of the caller's own queue, plus how many labels it holds.

    Each item comes back with its :class:`Document` already loaded, through an
    inner join that carries the tenant filter on *both* tables. The label is
    named after the document (``label-template.md``), so a queue without the
    document is a queue of bare UUIDs.
    """
    owner = user_id or ctx.user_id
    base = scoped(
        scoped_select(PrintQueueItem, ctx)
        .where(PrintQueueItem.user_id == owner)
        .join(Document, Document.id == PrintQueueItem.document_id)
        .options(contains_eager(PrintQueueItem.document)),
        ctx,
        Document,
    )
    total = await db.scalar(
        scoped(select(func.count(PrintQueueItem.id)), ctx, PrintQueueItem).where(
            PrintQueueItem.user_id == owner
        )
    )
    stmt = base.order_by(PrintQueueItem.position, PrintQueueItem.created_at)
    if offset is not None:
        stmt = stmt.offset(offset)
    if limit is not None:
        stmt = stmt.limit(limit)
    return list((await db.execute(stmt)).scalars().all()), int(total or 0)


async def remove_from_queue(
    db: AsyncSession,
    ctx: TenantContext,
    *,
    item_id: UUID,
    user_id: UUID | None = None,
) -> None:
    item = await _queue_item(db, ctx, item_id, user_id or ctx.user_id)
    await db.delete(item)
    await db.flush()


async def reorder_queue(
    db: AsyncSession,
    ctx: TenantContext,
    *,
    item_ids: list[UUID],
    user_id: UUID | None = None,
) -> None:
    """Positions follow the order given. Every id must be in the caller's queue."""
    rows, _ = await list_queue(db, ctx, user_id=user_id)
    items = {item.id: item for item in rows}
    if any(item_id not in items for item_id in item_ids):
        raise NotFoundError("PRINT_QUEUE_ITEM_NOT_FOUND")

    for position, item_id in enumerate(item_ids):
        items[item_id].position = position
    await db.flush()


async def clear_queue(db: AsyncSession, ctx: TenantContext, *, user_id: UUID | None = None) -> None:
    rows, _ = await list_queue(db, ctx, user_id=user_id)
    for item in rows:
        await db.delete(item)
    await db.flush()


async def create_job(
    db: AsyncSession,
    ctx: TenantContext,
    *,
    template_code: str,
    printer_name: str | None = None,
    start_position: int = 1,
    item_ids: list[UUID] | None = None,
    user_id: UUID | None = None,
    layout: PrintLayout | None = None,
    ip_hash: str | None = None,
) -> PrintJob:
    """Turn the queue into a traced job and empty what it consumed.

    Consumption is metered here, when the labels are dispatched.
    ``Document.print_count`` only moves once the run is confirmed.
    """
    template = template_for(template_code)
    _reject_bad_start(template, start_position)

    owner = user_id or ctx.user_id
    queued, _ = await list_queue(db, ctx, user_id=owner)
    if item_ids is not None:
        wanted = set(item_ids)
        queued = [item for item in queued if item.id in wanted]
    if not queued:
        raise DomainError("PRINT_QUEUE_EMPTY")

    label_count = sum(item.copies for item in queued)
    job = PrintJob(
        mm_id=ctx.mm_id,
        site_id=ctx.site_id,
        user_id=owner,
        printer_name=printer_name,
        layout=PrintLayout(layout) if layout else template.layout,
        template_code=template.code,
        start_position=start_position,
        label_count=label_count,
        page_count=_page_count(template, label_count, start_position),
        status=PrintJobStatus.PENDING,
    )
    db.add(job)
    await db.flush()

    index = 0
    for item in queued:
        db.add(
            PrintJobItem(
                print_job_id=job.id,
                document_id=item.document_id,
                copies=item.copies,
                label_index=index,
            )
        )
        index += item.copies
        await db.delete(item)
    await db.flush()

    await quota.record_prints(db, ctx, labels=label_count)
    await audit.record(
        db,
        mm_id=ctx.mm_id,
        site_id=ctx.site_id,
        actor_user_id=owner,
        action="print_job.created",
        object_type="print_job",
        object_id=job.id,
        payload={"labels": label_count, "template": template.code},
        ip_hash=ip_hash,
    )
    return job


async def confirm_job(
    db: AsyncSession,
    ctx: TenantContext,
    job_id: UUID,
    *,
    success: bool = True,
    ok: bool | None = None,
    failure_reason: str | None = None,
    actor_user_id: UUID | None = None,
    ip_hash: str | None = None,
) -> PrintJob:
    """Close a run. A closed job never reopens; a reprint is a new job."""
    job = await _job(db, ctx, job_id)
    if PrintJobStatus(job.status) != PrintJobStatus.PENDING:
        raise DomainError("PRINT_JOB_ALREADY_CLOSED")

    succeeded = success if ok is None else ok
    job.status = PrintJobStatus.PRINTED if succeeded else PrintJobStatus.FAILED
    job.confirmed_at = datetime.now(UTC)
    job.failure_reason = None if succeeded else failure_reason

    if succeeded:
        await _increment_print_counts(db, ctx, job)
    await db.flush()

    await audit.record(
        db,
        mm_id=ctx.mm_id,
        site_id=ctx.site_id,
        actor_user_id=actor_user_id or ctx.user_id,
        action="print_job.confirmed" if succeeded else "print_job.failed",
        object_type="print_job",
        object_id=job.id,
        payload={"failure_reason": job.failure_reason},
        ip_hash=ip_hash,
    )
    return job


async def render_labels_html(
    db: AsyncSession,
    ctx: TenantContext,
    job_id: UUID,
    *,
    language: str = "es",
) -> str:
    """Print-ready HTML for a job the browser is about to print."""
    job = await _job(db, ctx, job_id)
    template = template_for(job.template_code)
    labels = await labels_for_job(db, ctx, job)
    return render_labels(job, labels, template, language=language)


async def labels_for_job(
    db: AsyncSession, ctx: TenantContext, job: PrintJob
) -> list[dict[str, str]]:
    """Expand a job into one dict per physical label, ready for rendering."""
    stmt = (
        select(PrintJobItem)
        .where(PrintJobItem.print_job_id == job.id)
        .order_by(PrintJobItem.label_index)
    )
    items = (await db.execute(stmt)).scalars().all()
    documents = {
        document.id: document
        for document in await _documents_of(db, ctx, [item.document_id for item in items])
    }

    labels: list[dict[str, str]] = []
    for item in items:
        document = documents[item.document_id]
        share = await active_share_token(db, document.id)
        labels.extend(
            [
                {
                    "document_id": str(document.id),
                    "short_id": str(document.id)[:8],
                    "filename": document.original_filename,
                    "uploaded_at": document.created_at.date().isoformat(),
                    "qr_url": public_url(share.token) if share else "",
                }
            ]
            * item.copies
        )
    return labels


def template_for(template_code: str) -> LabelTemplate:
    template = TEMPLATES.get(template_code)
    if template is None:
        raise DomainError("PRINT_TEMPLATE_UNKNOWN", template_code=template_code)
    return template


def render_labels(
    job: PrintJob,
    labels: list[dict[str, str]],
    template: LabelTemplate,
    *,
    language: str = "es",
) -> str:
    """Print-ready HTML: black on white, exact millimetres, no backgrounds.

    Each label dict carries ``qr_url``, ``filename``, ``short_id`` and
    ``uploaded_at``; :func:`labels_for_job` builds them.
    """
    blanks = max(0, job.start_position - 1) if template.layout == PrintLayout.SHEET else 0
    cells = [_BLANK_CELL] * blanks
    cells += [_label_cell(label) for label in labels]

    return _DOCUMENT.format(
        language=html.escape(language),
        title=html.escape(f"{template.name(language)} - {job.id}"),
        style=_stylesheet(template),
        cells="\n".join(cells),
    )


async def _documents_of(
    db: AsyncSession, ctx: TenantContext, document_ids: list[UUID]
) -> list[Document]:
    if not document_ids:
        return []
    stmt = scoped_select(Document, ctx).where(Document.id.in_(set(document_ids)))
    found = {document.id: document for document in (await db.execute(stmt)).scalars().all()}
    if len(found) != len(set(document_ids)):
        raise NotFoundError("DOCUMENT_NOT_FOUND")
    return [found[document_id] for document_id in document_ids]


async def _next_position(db: AsyncSession, ctx: TenantContext, user_id: UUID) -> int:
    stmt = scoped(select(func.max(PrintQueueItem.position)), ctx, PrintQueueItem).where(
        PrintQueueItem.user_id == user_id
    )
    return ((await db.execute(stmt)).scalar() or 0) + 1


async def _queue_item(
    db: AsyncSession, ctx: TenantContext, item_id: UUID, user_id: UUID
) -> PrintQueueItem:
    stmt = scoped_select(PrintQueueItem, ctx).where(
        PrintQueueItem.id == item_id, PrintQueueItem.user_id == user_id
    )
    item = (await db.execute(stmt)).scalars().first()
    if item is None:
        raise NotFoundError("PRINT_QUEUE_ITEM_NOT_FOUND")
    return item


async def _job(db: AsyncSession, ctx: TenantContext, job_id: UUID) -> PrintJob:
    stmt = scoped_select(PrintJob, ctx).where(PrintJob.id == job_id)
    job = (await db.execute(stmt)).scalars().first()
    if job is None:
        raise NotFoundError("PRINT_JOB_NOT_FOUND")
    return job


async def _increment_print_counts(db: AsyncSession, ctx: TenantContext, job: PrintJob) -> None:
    stmt = (
        select(PrintJobItem)
        .where(PrintJobItem.print_job_id == job.id)
        .order_by(PrintJobItem.label_index)
    )
    items = (await db.execute(stmt)).scalars().all()
    documents = {
        document.id: document
        for document in await _documents_of(db, ctx, [item.document_id for item in items])
    }
    for item in items:
        documents[item.document_id].print_count += item.copies


def _reject_unprintable(document: Document) -> None:
    """A label is a claim: "scan this, it is a DeCA". Only make it for one.

    A scan carries no text layer and can never be a control document, whatever
    QR is stuck on it (``CLAUDE.md`` prohibition 13). A superseded revision or a
    withdrawn file no longer resolves to anything an inspector should see.
    Compared with ``==``: rows loaded from the database hold plain strings.
    """
    if document.compliance_status == ComplianceStatus.NOT_A_DECA:
        raise DomainError("PRINT_NOT_A_DECA", status_code=422, filename=document.original_filename)
    unavailable = (
        document.withdrawn_at is not None
        or document.superseded_at is not None
        or document.compliance_status == ComplianceStatus.SUPERSEDED
        or document.status == DocumentStatus.WITHDRAWN
    )
    if unavailable:
        raise DomainError(
            "PRINT_DOCUMENT_UNAVAILABLE", status_code=409, filename=document.original_filename
        )


def _page_count(template: LabelTemplate, label_count: int, start_position: int) -> int:
    if template.layout == PrintLayout.SINGLE:
        return label_count
    return ceil((start_position - 1 + label_count) / template.slots)


def _reject_bad_start(template: LabelTemplate, start_position: int) -> None:
    if start_position < 1 or start_position > template.slots:
        raise DomainError(
            "PRINT_START_POSITION_INVALID",
            position=start_position,
            slots=template.slots,
        )


def _label_cell(label: dict[str, str]) -> str:
    qr = qr_svg(label["qr_url"]) if label.get("qr_url") else ""
    return (
        '<div class="label">'
        f'<div class="qr">{qr}</div>'
        f'<p class="filename">{html.escape(str(label.get("filename", "")))}</p>'
        f'<p class="meta">{html.escape(str(label.get("short_id", "")))} '
        f"&middot; {html.escape(str(label.get('uploaded_at', '')))}</p>"
        "</div>"
    )


def _stylesheet(template: LabelTemplate) -> str:
    return f"""
    @page {{ size: {template.page_width_mm}mm {template.page_height_mm}mm; margin: 0; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: #fff; color: #000;
            font-family: Helvetica, Arial, sans-serif; }}
    .sheet {{ display: grid; width: {template.page_width_mm}mm;
              grid-template-columns: repeat({template.columns}, {template.label_width_mm}mm);
              grid-auto-rows: {template.label_height_mm}mm;
              column-gap: {template.gutter_x_mm}mm; row-gap: {template.gutter_y_mm}mm;
              padding: {template.margin_top_mm}mm 0 0 {template.margin_left_mm}mm; }}
    .label {{ width: {template.label_width_mm}mm; height: {template.label_height_mm}mm;
              padding: 2mm; overflow: hidden; page-break-inside: avoid; }}
    .label.blank {{ visibility: hidden; }}
    .qr svg {{ width: {template.qr_mm}mm; height: {template.qr_mm}mm;
               shape-rendering: crispEdges; }}
    .filename {{ margin: 1mm 0 0; font-size: 9pt; font-weight: 600; line-height: 1.15;
                 display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical;
                 overflow: hidden; }}
    .meta {{ margin: 0.5mm 0 0; font-size: 8pt;
             font-family: "SFMono-Regular", Consolas, monospace; }}
    """


_BLANK_CELL = '<div class="label blank"></div>'

_DOCUMENT = """<!doctype html>
<html lang="{language}">
<head><meta charset="utf-8"><title>{title}</title><style>{style}</style></head>
<body><div class="sheet">
{cells}
</div></body>
</html>
"""

"""Label queue and print jobs. Nothing reaches a printer without a job row."""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.deps import Db, TenantContext, require_permission, scoped_select
from app.errors import NotFoundError
from app.models.printing import PrintJob
from app.routers import ClientIpHash, Page
from app.schemas.common import Acknowledgement, PageParams, PageResponse
from app.schemas.printing import (
    LabelTemplateCatalogResponse,
    LabelTemplateRead,
    PrintJobConfirmRequest,
    PrintJobCreate,
    PrintJobRead,
    QueueAddRequest,
    QueueItemRead,
    QueueReorderRequest,
)
from app.services import printing as printing_service

router = APIRouter(prefix="/printing", tags=["printing"])

ReadCtx = Annotated[TenantContext, Depends(require_permission("printing:read"))]
QueueCtx = Annotated[TenantContext, Depends(require_permission("printing:queue"))]
PrintCtx = Annotated[TenantContext, Depends(require_permission("printing:print"))]


async def _queue_page(db: Db, ctx: TenantContext, page: PageParams) -> PageResponse[QueueItemRead]:
    rows, total = await printing_service.list_queue(
        db, ctx, user_id=ctx.user_id, offset=page.offset, limit=page.limit
    )
    return PageResponse.of([QueueItemRead.model_validate(row) for row in rows], total, page)


async def _job_read(db: Db, ctx: TenantContext, job_id: uuid.UUID) -> PrintJobRead:
    stmt = (
        scoped_select(PrintJob, ctx)
        .where(PrintJob.id == job_id)
        .options(selectinload(PrintJob.items))
    )
    job = (await db.execute(stmt)).scalar_one_or_none()
    if job is None:
        raise NotFoundError("PRINT_JOB_NOT_FOUND")
    return PrintJobRead.model_validate(job)


def _template_read(code: str, template: Any) -> LabelTemplateRead:
    source = dict(template) if isinstance(template, dict) else template
    if isinstance(source, dict):
        source.setdefault("code", code)
        return LabelTemplateRead.model_validate(source)
    return LabelTemplateRead.model_validate(source).model_copy(update={"code": code})


@router.get("/queue/", response_model=PageResponse[QueueItemRead])
async def list_queue(ctx: ReadCtx, db: Db, page: Page) -> PageResponse[QueueItemRead]:
    return await _queue_page(db, ctx, page)


@router.post(
    "/queue/",
    response_model=PageResponse[QueueItemRead],
    status_code=status.HTTP_201_CREATED,
)
async def add_to_queue(
    payload: QueueAddRequest, ctx: QueueCtx, db: Db, page: Page
) -> PageResponse[QueueItemRead]:
    await printing_service.add_to_queue(
        db,
        ctx,
        user_id=ctx.user_id,
        document_ids=payload.document_ids,
        copies=payload.copies,
    )
    return await _queue_page(db, ctx, page)


@router.post("/queue/reorder", response_model=PageResponse[QueueItemRead])
async def reorder_queue(
    payload: QueueReorderRequest, ctx: QueueCtx, db: Db, page: Page
) -> PageResponse[QueueItemRead]:
    await printing_service.reorder_queue(db, ctx, user_id=ctx.user_id, item_ids=payload.item_ids)
    return await _queue_page(db, ctx, page)


@router.delete("/queue/", response_model=Acknowledgement)
async def clear_queue(ctx: QueueCtx, db: Db) -> Acknowledgement:
    await printing_service.clear_queue(db, ctx, user_id=ctx.user_id)
    return Acknowledgement()


@router.delete("/queue/{item_id}", response_model=Acknowledgement)
async def remove_from_queue(item_id: uuid.UUID, ctx: QueueCtx, db: Db) -> Acknowledgement:
    await printing_service.remove_from_queue(db, ctx, user_id=ctx.user_id, item_id=item_id)
    return Acknowledgement()


@router.get("/templates", response_model=LabelTemplateCatalogResponse)
async def list_templates(ctx: ReadCtx) -> LabelTemplateCatalogResponse:
    """Label templates in both languages. The client never hardcodes one."""
    templates = printing_service.TEMPLATES
    pairs = (
        templates.items()
        if isinstance(templates, dict)
        else [(template.code, template) for template in templates]
    )
    return LabelTemplateCatalogResponse(
        items=[_template_read(code, template) for code, template in pairs]
    )


@router.get("/jobs/", response_model=PageResponse[PrintJobRead])
async def list_jobs(ctx: ReadCtx, db: Db, page: Page) -> PageResponse[PrintJobRead]:
    stmt = scoped_select(PrintJob, ctx).options(selectinload(PrintJob.items))
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.execute(
            stmt.order_by(PrintJob.created_at.desc()).offset(page.offset).limit(page.limit)
        )
    ).scalars()
    return PageResponse.of([PrintJobRead.model_validate(row) for row in rows], total, page)


@router.post("/jobs/", response_model=PrintJobRead, status_code=status.HTTP_201_CREATED)
async def create_job(
    payload: PrintJobCreate, ctx: PrintCtx, db: Db, ip_hash: ClientIpHash
) -> PrintJobRead:
    """Created before the browser opens the print dialog, never after."""
    job = await printing_service.create_job(
        db,
        ctx,
        user_id=ctx.user_id,
        template_code=payload.template_code,
        printer_name=payload.printer_name,
        start_position=payload.start_position,
        item_ids=payload.item_ids,
        ip_hash=ip_hash,
    )
    return await _job_read(db, ctx, job.id)


@router.get("/jobs/{job_id}/render", response_class=HTMLResponse)
async def render_job(job_id: uuid.UUID, ctx: PrintCtx, db: Db) -> HTMLResponse:
    """Print-ready HTML: the browser's own print dialog does the rest."""
    html = await printing_service.render_labels_html(db, ctx, job_id)
    return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})


@router.post("/jobs/{job_id}/confirm", response_model=PrintJobRead)
async def confirm_job(
    job_id: uuid.UUID,
    payload: PrintJobConfirmRequest,
    ctx: PrintCtx,
    db: Db,
    ip_hash: ClientIpHash,
) -> PrintJobRead:
    await printing_service.confirm_job(
        db,
        ctx,
        job_id,
        success=payload.success,
        failure_reason=payload.failure_reason,
        actor_user_id=ctx.user_id,
        ip_hash=ip_hash,
    )
    return await _job_read(db, ctx, job_id)

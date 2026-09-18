"""Label queue, label templates and the print jobs that trace every copy."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.models.printing import PrintJobStatus, PrintLayout
from app.schemas.common import Schema
from app.schemas.documents import DocumentSummary


class QueueAddRequest(Schema):
    document_ids: list[uuid.UUID] = Field(min_length=1, max_length=500)
    copies: int = Field(default=1, ge=1, le=99)


class QueueReorderRequest(Schema):
    """The full ordering, front to back. Anything missing keeps its place."""

    item_ids: list[uuid.UUID] = Field(min_length=1)


class QueueItemRead(Schema):
    id: uuid.UUID
    document_id: uuid.UUID
    copies: int
    position: int
    created_at: datetime
    document: DocumentSummary | None = None


class LabelTemplateRead(Schema):
    """Served from the service catalogue; the UI never hardcodes a template."""

    code: str
    name_es: str | None = None
    name_en: str | None = None
    layout: PrintLayout | None = None
    columns: int | None = None
    rows: int | None = None
    slots_per_sheet: int | None = None
    label_width_mm: float | None = None
    label_height_mm: float | None = None


class LabelTemplateCatalogResponse(Schema):
    items: list[LabelTemplateRead]


class PrintJobCreate(Schema):
    """Created before anything reaches a printer. Nothing prints untraced."""

    template_code: str = Field(min_length=1, max_length=64)
    printer_name: str | None = Field(default=None, max_length=160)
    start_position: int = Field(default=1, ge=1)
    #: Omitted means the whole queue.
    item_ids: list[uuid.UUID] | None = None


class PrintJobConfirmRequest(Schema):
    success: bool = True
    failure_reason: str | None = Field(default=None, max_length=255)


class PrintJobItemRead(Schema):
    id: uuid.UUID
    document_id: uuid.UUID
    copies: int
    label_index: int


class PrintJobRead(Schema):
    id: uuid.UUID
    status: PrintJobStatus
    template_code: str
    layout: PrintLayout
    printer_name: str | None
    start_position: int
    label_count: int
    page_count: int
    confirmed_at: datetime | None
    failure_reason: str | None
    created_at: datetime
    user_id: uuid.UUID | None
    items: list[PrintJobItemRead] = Field(default_factory=list)

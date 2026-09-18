"""Label printing: an accumulating queue, then a traceable job per run."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import (
    UUID as PgUUID,  # noqa: N811 (alias avoids shadowing uuid.UUID)
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, OptimisticLock, TenantScoped, TimestampMixin, uuid_pk
from app.models.documents import Document


class PrintLayout(enum.StrEnum):
    SINGLE = "single"  # one label per page, thermal printers
    SHEET = "sheet"  # N x M grid on a sheet


class PrintJobStatus(enum.StrEnum):
    PENDING = "pending"
    PRINTED = "printed"
    FAILED = "failed"


class PrintQueueItem(Base, TenantScoped, TimestampMixin, OptimisticLock):
    """A label waiting to be printed. Survives reloads, one queue per user+site."""

    __tablename__ = "print_queue_items"
    __table_args__ = (Index("ix_print_queue_owner", "mm_id", "site_id", "user_id", "position"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    copies: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    #: The row the label names. ``lazy="raise"``: an async session cannot load
    #: it on attribute access, and a silent ``MissingGreenlet`` is exactly the
    #: bug that shipped a queue full of bare UUIDs. ``printing.list_queue``
    #: joins it in, under the same tenant filter as the queue item itself.
    document: Mapped[Document] = relationship(lazy="raise")


class PrintJob(Base, TenantScoped, TimestampMixin, OptimisticLock):
    """One print run. Created *before* printing, so nothing prints untraced."""

    __tablename__ = "print_jobs"

    id: Mapped[uuid.UUID] = uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    printer_name: Mapped[str | None] = mapped_column(String(160))
    layout: Mapped[PrintLayout] = mapped_column(
        String(16), nullable=False, default=PrintLayout.SINGLE
    )
    template_code: Mapped[str] = mapped_column(String(64), nullable=False, default="thermal_50x30")
    start_position: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    label_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[PrintJobStatus] = mapped_column(
        String(16), nullable=False, default=PrintJobStatus.PENDING
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_reason: Mapped[str | None] = mapped_column(String(255))

    items: Mapped[list[PrintJobItem]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class PrintJobItem(Base, TimestampMixin):
    """One document within a print run. This is the reprint record."""

    __tablename__ = "print_job_items"
    __table_args__ = (Index("ix_print_job_items_document", "document_id", "created_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    print_job_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("print_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    copies: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    label_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    job: Mapped[PrintJob] = relationship(back_populates="items")

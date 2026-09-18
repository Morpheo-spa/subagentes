"""Delivery notes (albaranes): the archived PDF, its QR token and its access log."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import (
    UUID as PgUUID,  # noqa: N811 (alias avoids shadowing uuid.UUID)
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, OptimisticLock, TenantScoped, TimestampMixin, uuid_pk


class DocumentStatus(enum.StrEnum):
    PENDING = "pending"  # row created, bytes not yet stored
    PROCESSING = "processing"  # hashing, QR, upload to backend
    READY = "ready"
    WITHDRAWN = "withdrawn"  # file removed by retention; record kept
    FAILED = "failed"


class DecaStatus(enum.StrEnum):
    COMPLETE = "completo"
    INCOMPLETE = "incompleto"
    NOT_APPLICABLE = "no_aplica"


class DocumentOrigin(enum.StrEnum):
    """How the PDF came to exist, which decides whether it can be a valid DeCA."""

    #: Rendered by us from structured DECA data. The compliant path.
    GENERATED = "generated"
    #: A natively generated PDF supplied by the customer's own system.
    UPLOADED_NATIVE = "uploaded_native"
    #: A scan or photo. Archived, but flagged as NOT a valid DeCA.
    UPLOADED_SCANNED = "uploaded_scanned"


class ComplianceStatus(enum.StrEnum):
    """Whether this file can stand as a DeCA under the 2026 Resolution."""

    COMPLIANT = "compliant"
    #: Missing DECA fields, or no QR embedded. Fixable.
    INCOMPLETE = "incomplete"
    #: Image-only PDF. Cannot be a DeCA whatever we add to it.
    NOT_A_DECA = "not_a_deca"
    SUPERSEDED = "superseded"


class Document(Base, TenantScoped, TimestampMixin, OptimisticLock):
    """One archived delivery note.

    ``id`` is the GUID the file is stored under. It is deliberately *not* the
    value published in the QR: see :class:`ShareToken`.
    """

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_tenant", "mm_id", "site_id", "created_at"),
        Index("ix_documents_sha256", "mm_id", "site_id", "sha256"),
        Index("ix_documents_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_backend_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("storage_backends.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sha256: Mapped[str | None] = mapped_column(String(64))
    page_count: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[DocumentStatus] = mapped_column(
        String(16), nullable=False, default=DocumentStatus.PENDING
    )
    failure_code: Mapped[str | None] = mapped_column(String(64))

    #: DECA metadata, validated against the field catalogue in force at upload time.
    deca: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    deca_status: Mapped[DecaStatus] = mapped_column(
        String(16), nullable=False, default=DecaStatus.INCOMPLETE
    )
    deca_catalog_version: Mapped[int | None] = mapped_column(Integer)

    origin: Mapped[DocumentOrigin] = mapped_column(
        String(24), nullable=False, default=DocumentOrigin.UPLOADED_NATIVE
    )
    compliance_status: Mapped[ComplianceStatus] = mapped_column(
        String(16), nullable=False, default=ComplianceStatus.INCOMPLETE
    )
    #: False when the PDF carries no extractable text layer, i.e. it is a scan.
    has_text_layer: Mapped[bool | None] = mapped_column(Boolean)
    #: True once the QR has been stamped into the PDF itself, not just onto a label.
    qr_embedded: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # --- Immutable revision chain (apartado quinto of the Resolution) --------
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: Mandatory when this revision replaces another one.
    change_reason: Mapped[str | None] = mapped_column(String(500))

    uploaded_by_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    retention_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("retention_policies.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    withdrawn_reason: Mapped[str | None] = mapped_column(String(255))
    print_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    share_tokens: Mapped[list[ShareToken]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    @property
    def is_available(self) -> bool:
        """Whether the public viewer may serve this file."""
        return (
            self.status is DocumentStatus.READY
            and self.withdrawn_at is None
            and self.superseded_at is None
        )

    @property
    def is_valid_deca(self) -> bool:
        """A scan can never be a DeCA, whatever metadata it carries."""
        return (
            self.origin is not DocumentOrigin.UPLOADED_SCANNED
            and self.compliance_status is ComplianceStatus.COMPLIANT
        )


class ShareToken(Base, TimestampMixin):
    """The secret published in the QR code.

    Independent of ``Document.id`` and revocable, so a leaked or reprinted label
    can be killed without touching the archived file.
    """

    __tablename__ = "share_tokens"
    __table_args__ = (UniqueConstraint("token", name="uq_share_tokens_token"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    token: Mapped[str] = mapped_column(String(64), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    document: Mapped[Document] = relationship(back_populates="share_tokens")


class DocumentAccess(Base):
    """Audit trail of public QR scans. IPs are stored hashed, never raw."""

    __tablename__ = "document_accesses"
    __table_args__ = (Index("ix_document_accesses_document", "document_id", "accessed_at"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    document_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    share_token_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("share_tokens.id", ondelete="SET NULL")
    )
    accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(Text)

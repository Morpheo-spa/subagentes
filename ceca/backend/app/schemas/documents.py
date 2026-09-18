"""Delivery notes: listing, upload results, revisions and history."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import Field

from app.models.documents import (
    ComplianceStatus,
    DecaStatus,
    DocumentOrigin,
    DocumentStatus,
)
from app.schemas.common import ErrorDetail, Schema


class DocumentFilters(Schema):
    """Everything the archive list can be narrowed by. Built from query params."""

    search: str | None = None
    status: DocumentStatus | None = None
    deca_status: DecaStatus | None = None
    compliance_status: ComplianceStatus | None = None
    origin: DocumentOrigin | None = None
    created_from: date | None = None
    created_to: date | None = None
    expires_before: date | None = None
    include_superseded: bool = False


class DocumentSummary(Schema):
    """One row of the archive table."""

    id: uuid.UUID
    original_filename: str
    status: DocumentStatus
    deca_status: DecaStatus
    origin: DocumentOrigin
    compliance_status: ComplianceStatus
    is_valid_deca: bool
    revision: int
    byte_size: int
    page_count: int | None
    print_count: int
    created_at: datetime
    expires_at: datetime | None
    withdrawn_at: datetime | None
    superseded_at: datetime | None


class DocumentRead(DocumentSummary):
    """The detail view. Storage keys and credentials never appear here."""

    sha256: str | None
    has_text_layer: bool | None
    qr_embedded: bool
    deca: dict[str, Any] = Field(default_factory=dict)
    deca_catalog_version: int | None
    supersedes_id: uuid.UUID | None
    change_reason: str | None
    withdrawn_reason: str | None
    failure_code: str | None
    uploaded_by_id: uuid.UUID | None
    retention_policy_id: uuid.UUID | None
    storage_backend_id: uuid.UUID
    updated_at: datetime
    version: int
    share_token: str | None = None
    public_url: str | None = None


class UploadWarning(Schema):
    """A duplicate or a scan: the file is archived, the user decides what to do."""

    code: str
    params: dict[str, Any] = Field(default_factory=dict)


class UploadItemResult(Schema):
    """One entry per submitted file. A bad file never fails the whole batch."""

    filename: str
    accepted: bool
    document: DocumentSummary | None = None
    warnings: list[UploadWarning] = Field(default_factory=list)
    error: ErrorDetail | None = None


class UploadResponse(Schema):
    items: list[UploadItemResult]
    accepted: int
    rejected: int


class DocumentGenerateRequest(Schema):
    """The compliant path: we render the PDF from structured data."""

    deca: dict[str, Any]
    filename: str | None = Field(default=None, max_length=255)
    retention_policy_id: uuid.UUID | None = None


class DecaPatchRequest(Schema):
    """Completes or corrects metadata on a document that is not yet final."""

    deca: dict[str, Any]
    version: int | None = None


class RevisionCreateRequest(Schema):
    """Apartado quinto of the Resolution: a change always states its reason."""

    change_reason: str = Field(min_length=3, max_length=500)
    deca: dict[str, Any] | None = None


class WithdrawRequest(Schema):
    reason: str = Field(min_length=3, max_length=255)


class RevisionEntry(Schema):
    id: uuid.UUID
    revision: int
    change_reason: str | None
    created_at: datetime
    superseded_at: datetime | None
    is_current: bool


class PrintEntry(Schema):
    print_job_id: uuid.UUID
    copies: int
    template_code: str
    printed_at: datetime | None
    user_id: uuid.UUID | None


class PublicAccessEntry(Schema):
    accessed_at: datetime
    ip_hash: str | None
    user_agent: str | None


class DocumentHistoryResponse(Schema):
    document_id: uuid.UUID
    revisions: list[RevisionEntry] = Field(default_factory=list)
    prints: list[PrintEntry] = Field(default_factory=list)
    public_accesses: list[PublicAccessEntry] = Field(default_factory=list)


class PublicDocumentView(Schema):
    """What an inspector sees after scanning the QR. No internal identifiers."""

    original_filename: str
    issued_at: datetime
    revision: int
    is_valid_deca: bool
    compliance_status: ComplianceStatus
    deca: dict[str, Any] = Field(default_factory=dict)
    file_url: str
    site_name: str | None = None

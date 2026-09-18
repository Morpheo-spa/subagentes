"""Delivery notes: listing, upload results, revisions and history.

The DECA payload is the one place where a client hands us a free-form mapping,
and a PDF gets rendered from it, so it is bounded here before anything else
looks at it: how many fields, how long a key, how long a value and - just as
important - what shape a value may take at all. Which codes are legitimate is a
different question, answered against the catalogue table in the service layer.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import Field, StringConstraints

from app.models.documents import (
    ComplianceStatus,
    DecaStatus,
    DocumentOrigin,
    DocumentStatus,
)
from app.schemas.common import ErrorDetail, Schema

#: Bounds on a DECA payload. The catalogue in force carries a dozen or so
#: fields; the headroom is for a catalogue that grows, not for a payload that
#: pays for itself in rendered pages.
MAX_DECA_FIELDS = 40
MAX_DECA_KEY_CHARS = 64
MAX_DECA_VALUE_CHARS = 1000

#: Field codes are identifiers from the catalogue, not free text.
DECA_CODE_PATTERN = r"^[a-z][a-z0-9_]*$"

#: No control characters in a stored filename. One ``\r\n`` in there used to be
#: enough to make a document permanently undownloadable, for its owner and for
#: the inspector scanning its QR alike. See ``documents.header_filename``.
FILENAME_PATTERN = r"^[^\x00-\x1f\x7f/\\]+$"

DecaCode = Annotated[
    str, StringConstraints(max_length=MAX_DECA_KEY_CHARS, pattern=DECA_CODE_PATTERN)
]
#: A scalar, and nothing else: no nested object, no list. Every catalogue type -
#: text, number, decimal, date, datetime, boolean, enum - fits in one of these,
#: and a nested structure could only ever be a way to smuggle in bulk.
DecaValue = Annotated[str, StringConstraints(max_length=MAX_DECA_VALUE_CHARS)] | bool | int | float
#: What every endpoint that accepts DECA metadata accepts.
DecaPayload = Annotated[dict[DecaCode, DecaValue | None], Field(max_length=MAX_DECA_FIELDS)]
Filename = Annotated[str, Field(max_length=255, pattern=FILENAME_PATTERN)]


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

    deca: DecaPayload
    filename: Filename | None = None
    retention_policy_id: uuid.UUID | None = None


class DecaSidecar(Schema):
    """The ``deca`` form field of a multipart upload, bounded like the rest.

    It arrives as a JSON string next to the files, so it would otherwise skip
    every constraint the JSON endpoints get for free.
    """

    deca: DecaPayload


class DecaPatchRequest(Schema):
    """Completes or corrects metadata on a document that is not yet final."""

    deca: DecaPayload
    version: int | None = None


class RevisionCreateRequest(Schema):
    """Apartado quinto of the Resolution: a change always states its reason."""

    change_reason: str = Field(min_length=3, max_length=500)
    deca: DecaPayload | None = None


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

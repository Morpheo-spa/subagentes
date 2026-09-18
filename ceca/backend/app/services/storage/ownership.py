"""Resolving a document's storage backend without trusting the foreign key.

Lives under ``storage`` rather than next to the document service so that both
``documents`` and ``retention`` can use it without importing each other.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.errors import DomainError
from app.models.storage import StorageBackend


class TenantOwned(Protocol):
    """Anything that claims to belong to a tenant and to point at a backend.

    Read-only members on purpose: the mapped columns that satisfy this protocol
    arrive as ``Mapped[...]`` descriptors, and this function only ever reads them.
    """

    @property
    def mm_id(self) -> UUID: ...

    @property
    def site_id(self) -> UUID: ...

    @property
    def storage_backend_id(self) -> UUID: ...


async def tenant_backend(db: AsyncSession, owner: TenantOwned) -> StorageBackend | None:
    """Load the backend a record points at, and prove it belongs to the same tenant.

    ``db.get`` fetches by primary key, so it cannot filter by tenant on its own.
    The id comes from a row that was already scoped, but a mismatch would mean
    reading from, or deleting in, another company's storage. Verify, don't assume.
    """
    backend = await db.get(
        StorageBackend, owner.storage_backend_id
    )  # tenant-exempt: ownership is checked on the next line
    if backend is None:
        return None
    if backend.mm_id != owner.mm_id or backend.site_id != owner.site_id:
        raise DomainError("STORAGE_NOT_CONFIGURED", status_code=500)
    return backend

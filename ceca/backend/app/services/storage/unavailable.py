"""Backend kinds that are modelled but not implemented.

Nothing here pretends to work. Configuring one of these fails loudly at the
first call, which is better than silently archiving nowhere.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from app.errors import DomainError
from app.models.storage import StorageBackend, StorageKind
from app.services.storage.base import register

UNAVAILABLE_KINDS = (
    StorageKind.SFTP,
    StorageKind.GOOGLE_DRIVE,
    StorageKind.ONEDRIVE,
)


@register(*UNAVAILABLE_KINDS)
class UnavailableStorage:
    def __init__(self, backend: StorageBackend) -> None:
        self._kind = StorageKind(backend.kind).value

    def _fail(self) -> DomainError:
        return DomainError("STORAGE_KIND_UNAVAILABLE", kind=self._kind)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        raise self._fail()

    async def get_stream(self, key: str) -> AsyncIterator[bytes]:
        raise self._fail()
        yield b""  # pragma: no cover - keeps this an async generator

    async def delete(self, key: str) -> None:
        raise self._fail()

    async def health(self) -> bool:
        return False

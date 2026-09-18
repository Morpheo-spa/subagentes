"""Local filesystem backend. The default for single-server installations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from app.errors import DomainError
from app.models.storage import StorageBackend, StorageKind
from app.services.storage.base import CHUNK_SIZE, normalise_key, register
from app.services.storage.validation import validate_base_path


@register(StorageKind.LOCAL)
class LocalStorage:
    def __init__(self, backend: StorageBackend) -> None:
        self._name = backend.name
        # Confined to the deployment's storage root, so a tenant cannot write
        # elsewhere, nor archive outside the volume that survives a restart.
        self._root = Path(validate_base_path(backend.config.get("base_path")))

    def _path(self, key: str) -> Path:
        return self._root / normalise_key(key)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._path(key)
        try:
            await asyncio.to_thread(self._write, path, data)
        except OSError as exc:
            raise DomainError("STORAGE_UNREACHABLE", name=self._name) from exc

    @staticmethod
    def _write(path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(data)
        temporary.replace(path)

    async def get_stream(self, key: str) -> AsyncIterator[bytes]:
        path = self._path(key)
        if not path.is_file():
            raise DomainError("STORAGE_OBJECT_MISSING", status_code=410)
        handle = await asyncio.to_thread(path.open, "rb")
        try:
            while True:
                chunk = await asyncio.to_thread(handle.read, CHUNK_SIZE)
                if not chunk:
                    return
                yield chunk
        finally:
            await asyncio.to_thread(handle.close)

    async def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            await asyncio.to_thread(path.unlink, True)
        except OSError as exc:
            raise DomainError("STORAGE_UNREACHABLE", name=self._name) from exc

    async def health(self) -> bool:
        probe = self._root / ".estampa-health"
        try:
            await asyncio.to_thread(self._write, probe, b"ok")
            await asyncio.to_thread(probe.unlink, True)
        except OSError:
            return False
        return True

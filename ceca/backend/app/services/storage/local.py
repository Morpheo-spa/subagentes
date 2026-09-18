"""Local filesystem backend. The default for single-server installations."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

from app.errors import DomainError
from app.models.storage import StorageBackend, StorageKind
from app.services.storage.base import CHUNK_SIZE, normalise_key, register

DEFAULT_BASE_PATH = "/var/lib/estampa/documents"


@register(StorageKind.LOCAL)
class LocalStorage:
    def __init__(self, backend: StorageBackend) -> None:
        self._name = backend.name
        self._root = Path(backend.config.get("base_path") or DEFAULT_BASE_PATH)

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

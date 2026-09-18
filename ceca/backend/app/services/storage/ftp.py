"""FTP / FTPS backend, for customers who archive on their own server."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.errors import DomainError
from app.models.storage import StorageBackend, StorageKind
from app.services.storage.base import (
    CHUNK_SIZE,
    credentials_of,
    normalise_key,
    register,
)

DEFAULT_PORT = 21


@register(StorageKind.FTP)
class FtpStorage:
    def __init__(self, backend: StorageBackend) -> None:
        config = backend.config
        credentials = credentials_of(backend)
        self._name = backend.name
        self._host = config.get("host", "")
        self._port = int(config.get("port") or DEFAULT_PORT)
        self._base_path = (config.get("base_path") or "").strip("/")
        self._use_tls = bool(config.get("tls"))
        self._user = credentials.get("username") or config.get("username") or "anonymous"
        self._password = credentials.get("password") or ""

    def _remote_path(self, key: str) -> str:
        clean = normalise_key(key)
        return f"{self._base_path}/{clean}" if self._base_path else clean

    def _connection(self) -> Any:
        import aioftp

        return aioftp.Client.context(
            self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            ssl=self._use_tls or None,
        )

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        path = self._remote_path(key)
        try:
            async with self._connection() as client:
                parent = path.rsplit("/", 1)[0] if "/" in path else ""
                if parent:
                    await client.make_directory(parent)
                async with client.upload_stream(path) as stream:
                    await stream.write(data)
        except Exception as exc:
            raise DomainError("STORAGE_UNREACHABLE", name=self._name) from exc

    async def get_stream(self, key: str) -> AsyncIterator[bytes]:
        path = self._remote_path(key)
        try:
            async with self._connection() as client:
                if not await client.exists(path):
                    raise DomainError("STORAGE_OBJECT_MISSING", status_code=410)
                async with client.download_stream(path) as stream:
                    async for block in stream.iter_by_block(CHUNK_SIZE):
                        yield block
        except DomainError:
            raise
        except Exception as exc:
            raise DomainError("STORAGE_UNREACHABLE", name=self._name) from exc

    async def delete(self, key: str) -> None:
        path = self._remote_path(key)
        try:
            async with self._connection() as client:
                if await client.exists(path):
                    await client.remove_file(path)
        except Exception as exc:
            raise DomainError("STORAGE_UNREACHABLE", name=self._name) from exc

    async def health(self) -> bool:
        try:
            async with self._connection() as client:
                await client.get_current_directory()
        except Exception:
            return False
        return True

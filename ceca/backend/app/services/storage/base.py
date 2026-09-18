"""The storage adapter contract and the registry that builds one per backend row.

An adapter knows nothing about documents. It receives a key and bytes.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol, runtime_checkable

from app.errors import DomainError
from app.models.storage import StorageBackend, StorageKind
from app.security import decrypt_secret

CHUNK_SIZE = 64 * 1024


@runtime_checkable
class StorageAdapter(Protocol):
    """What every backend must be able to do.

    ``get_stream`` is an async generator: iterate it with ``async for``.
    """

    async def put(self, key: str, data: bytes, content_type: str) -> None: ...

    # Not ``async def``: an async generator function returns its iterator
    # directly, without being awaited. Declaring it ``async`` here would demand
    # a coroutine that every implementation rightly does not return.
    def get_stream(self, key: str) -> AsyncIterator[bytes]: ...

    async def delete(self, key: str) -> None: ...

    async def health(self) -> bool: ...


AdapterFactory = Callable[[StorageBackend], StorageAdapter]

#: Every implemented backend kind, keyed by :class:`StorageKind`.
REGISTRY: dict[StorageKind, AdapterFactory] = {}


def register[AdapterT: type[StorageAdapter]](
    *kinds: StorageKind,
) -> Callable[[AdapterT], AdapterT]:
    """Class decorator that puts an adapter class in the registry.

    The adapter class is itself the factory: calling it with a backend row
    builds the adapter. Returning the class unchanged keeps the decorated name
    a class rather than a plain callable.
    """

    def decorator(adapter: AdapterT) -> AdapterT:
        for kind in kinds:
            REGISTRY[kind] = adapter
        return adapter

    return decorator


def credentials_of(backend: StorageBackend) -> dict[str, Any]:
    """Decrypt the backend's secret half. Never logged, never serialised."""
    if not backend.config_encrypted:
        return {}
    credentials: dict[str, Any] = json.loads(decrypt_secret(backend.config_encrypted))
    return credentials


def normalise_key(key: str) -> str:
    """Reject anything that could escape the backend's own namespace."""
    cleaned = key.strip().lstrip("/")
    parts = [part for part in cleaned.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise DomainError("STORAGE_OBJECT_MISSING")
    return "/".join(parts)


def build_adapter(backend: StorageBackend) -> StorageAdapter:
    """Resolve the adapter for a backend row, or say the kind is unavailable."""
    _load_adapters()
    kind = StorageKind(backend.kind)
    factory = REGISTRY.get(kind)
    if factory is None:
        raise DomainError("STORAGE_KIND_UNAVAILABLE", kind=kind.value)
    return factory(backend)


_ADAPTERS_LOADED = False


def _load_adapters() -> None:
    """Import the concrete modules so their decorators populate the registry.

    Guarded by a flag, not by "is the registry non-empty": importing one
    adapter module directly (a test, a script) registers that kind alone, and
    the old guard then took the registry for complete and answered
    STORAGE_KIND_UNAVAILABLE for the local adapter it never imported.
    """
    global _ADAPTERS_LOADED  # noqa: PLW0603
    if _ADAPTERS_LOADED:
        return
    _ADAPTERS_LOADED = True
    from app.services.storage import (  # noqa: F401
        ftp,
        local,
        s3,
        unavailable,
    )

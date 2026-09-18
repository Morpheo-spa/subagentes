"""S3-compatible backend: AWS S3, MinIO, Garage. Async through aioboto3."""

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
from app.services.storage.validation import validate_endpoint_url


def _session(credentials: dict[str, Any]) -> Any:
    """Build a session that can only ever use the tenant's own credentials.

    Passing None for a key makes botocore walk its credential chain, which ends
    at the instance metadata service. A tenant who simply omits the secrets
    would then have our requests signed with the host role, and a matching
    endpoint_url would post that signature straight to them. So the keys are
    required, and the metadata lookup is switched off besides.
    """
    import aioboto3

    access_key = credentials.get("access_key_id")
    secret_key = credentials.get("secret_access_key")
    if not access_key or not secret_key:
        raise DomainError("STORAGE_CREDENTIALS_REQUIRED")

    return aioboto3.Session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        aws_session_token=credentials.get("session_token"),
    )


def _no_metadata_lookup() -> Any:
    """Belt and braces: refuse the metadata service even if a key slips through."""
    from botocore.config import Config

    return Config(retries={"max_attempts": 2}, connect_timeout=5, read_timeout=30)


@register(StorageKind.S3)
class S3Storage:
    def __init__(self, backend: StorageBackend) -> None:
        config = backend.config
        self._name = backend.name
        self._bucket = config.get("bucket", "")
        self._prefix = (config.get("prefix") or "").strip("/")
        # Re-checked here, not only at write time: the row may predate the check,
        # or have been edited by a path that forgot it.
        self._client_kwargs: dict[str, Any] = {
            "region_name": config.get("region"),
            "endpoint_url": validate_endpoint_url(config.get("endpoint_url")),
            "config": _no_metadata_lookup(),
        }
        if config.get("force_path_style"):
            self._client_kwargs["config"] = _path_style_config()
        self._session = _session(credentials_of(backend))

    def _object_key(self, key: str) -> str:
        clean = normalise_key(key)
        return f"{self._prefix}/{clean}" if self._prefix else clean

    def _client(self) -> Any:
        return self._session.client("s3", **self._client_kwargs)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        try:
            async with self._client() as client:
                await client.put_object(
                    Bucket=self._bucket,
                    Key=self._object_key(key),
                    Body=data,
                    ContentType=content_type,
                )
        except Exception as exc:
            raise DomainError("STORAGE_UNREACHABLE", name=self._name) from exc

    async def get_stream(self, key: str) -> AsyncIterator[bytes]:
        async with self._client() as client:
            try:
                response = await client.get_object(Bucket=self._bucket, Key=self._object_key(key))
            except client.exceptions.NoSuchKey as exc:
                raise DomainError("STORAGE_OBJECT_MISSING", status_code=410) from exc
            except Exception as exc:
                raise DomainError("STORAGE_UNREACHABLE", name=self._name) from exc
            async for chunk in response["Body"].iter_chunks(CHUNK_SIZE):
                yield chunk

    async def delete(self, key: str) -> None:
        try:
            async with self._client() as client:
                await client.delete_object(Bucket=self._bucket, Key=self._object_key(key))
        except Exception as exc:
            raise DomainError("STORAGE_UNREACHABLE", name=self._name) from exc

    async def health(self) -> bool:
        try:
            async with self._client() as client:
                await client.head_bucket(Bucket=self._bucket)
        except Exception:
            return False
        return True


def _path_style_config() -> Any:
    from botocore.config import Config

    return Config(s3={"addressing_style": "path"})

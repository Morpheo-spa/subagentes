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


def _client_config(force_path_style: bool) -> Any:
    """One Config for every client, whatever the addressing style.

    Two things in here are security controls, not tuning:

    * ``allow_redirects`` is switched off at the HTTP layer. aiohttp follows a
      3xx by default and aiobotocore does not override that, so a whitelisted
      endpoint could answer ``307 Location: http://10.0.0.5:5432/`` and turn
      ``health()`` into a blind port scanner of the internal network. aiohttp
      drops ``Authorization`` on a cross-origin hop, so credentials were never
      at stake; the oracle was.
    * Timeouts bound how long a tenant-controlled host can hold a worker
      thread, and they are the same Config whether or not path style is on. A
      previous version replaced the whole Config when ``force_path_style`` was
      set and silently lost them (audit N-06).
    """
    from aiobotocore.config import AioConfig

    s3_options = {"addressing_style": "path"} if force_path_style else {}
    return AioConfig(
        retries={"max_attempts": 2},
        connect_timeout=5,
        read_timeout=30,
        s3=s3_options,
        http_session_cls=_no_redirect_session_class(),
    )


def _no_redirect_session_class() -> Any:
    """An aiobotocore HTTP session whose aiohttp client never follows a 3xx."""
    import aiohttp
    from aiobotocore.httpsession import AIOHTTPSession

    class _NoRedirectClientSession(aiohttp.ClientSession):
        async def _request(self, method: str, str_or_url: Any, **kwargs: Any) -> Any:
            kwargs["allow_redirects"] = False
            return await super()._request(method, str_or_url, **kwargs)

    class _NoRedirectHttpSession(AIOHTTPSession):  # type: ignore[misc]
        async def _get_session(self, proxy_url: Any) -> Any:
            if not (session := self._sessions.get(proxy_url)):
                connector = self._create_connector(proxy_url)
                self._sessions[proxy_url] = session = await self._exit_stack.enter_async_context(
                    _NoRedirectClientSession(
                        connector=connector,
                        timeout=self._timeout,
                        skip_auto_headers={"CONTENT-TYPE"},
                        auto_decompress=False,
                    )
                )
            return session

    return _NoRedirectHttpSession


@register(StorageKind.S3)
class S3Storage:
    def __init__(self, backend: StorageBackend) -> None:
        config = backend.config
        self._name = backend.name
        self._bucket = config.get("bucket", "")
        self._prefix = (config.get("prefix") or "").strip("/")
        # Re-checked here, not only at write time: the row may predate the check,
        # or have been edited by a path that forgot it. Without DNS: this runs
        # on the event loop for every request, and the name was resolved and
        # checked when the row was saved.
        self._client_kwargs: dict[str, Any] = {
            "region_name": config.get("region"),
            "endpoint_url": validate_endpoint_url(config.get("endpoint_url"), resolve=False),
            "config": _client_config(bool(config.get("force_path_style"))),
        }
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

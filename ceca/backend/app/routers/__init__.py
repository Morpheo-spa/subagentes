"""HTTP layer.

A router validates the request, calls a service and maps the result onto an
explicit output schema. Business rules live in ``app/services``, never here.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, Query, Request

from app.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PageParams
from app.security import hash_ip


def get_page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


def client_ip(request: Request) -> str | None:
    """The caller's address, honouring the single proxy hop we run behind."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def get_client_ip_hash(request: Request) -> str | None:
    return hash_ip(client_ip(request))


Page = Annotated[PageParams, Depends(get_page_params)]
ClientIpHash = Annotated[str | None, Depends(get_client_ip_hash)]


def content_disposition(disposition: str, filename: str) -> str:
    """RFC 5987 header value, so accented delivery note names survive."""
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
    return (
        f'{disposition}; filename="{ascii_name}"; '
        f"filename*=UTF-8''{quote(filename, safe='')}"
    )

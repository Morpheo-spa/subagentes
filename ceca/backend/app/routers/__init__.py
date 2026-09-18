"""HTTP layer.

A router validates the request, calls a service and maps the result onto an
explicit output schema. Business rules live in ``app/services``, never here.
"""

from __future__ import annotations

import re
from typing import Annotated
from urllib.parse import quote

from fastapi import Depends, Query, Request

from app.config import get_settings
from app.schemas.common import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, PageParams
from app.security import hash_ip


def get_page_params(
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = DEFAULT_PAGE_SIZE,
) -> PageParams:
    return PageParams(page=page, page_size=page_size)


def client_ip(request: Request) -> str | None:
    """The caller's address, counted from the right of ``X-Forwarded-For``.

    Every proxy appends the address it saw to the right of the header, so the
    left-hand entries are whatever the client chose to send. Reading the
    leftmost element let anyone poison the ``ip_hash`` of the legal access log
    by sending ``X-Forwarded-For: 8.8.8.8`` (audit E-10).

    ``TRUSTED_PROXY_COUNT`` is the number of proxies we run behind (1 = Traefik
    only) and it is the same quantity as ``ipStrategy.depth`` in
    ``infra/traefik/dynamic/middlewares.yml``, which Traefik already uses for the
    login rate limit. Change one and you must change the other, or the address
    that is rate-limited stops being the address that is logged. With 0 the
    header is ignored altogether, for a deployment with no proxy in front.

    A header with fewer hops than expected is truncated rather than trusted: we
    take the leftmost entry present, never an element a client could have added.
    """
    hops = request.headers.get("X-Forwarded-For", "")
    trusted = get_settings().trusted_proxy_count
    if trusted > 0 and hops:
        chain = [hop.strip() for hop in hops.split(",") if hop.strip()]
        if chain:
            return chain[-min(trusted, len(chain))]
    return request.client.host if request.client else None


def get_client_ip_hash(request: Request) -> str | None:
    return hash_ip(client_ip(request))


Page = Annotated[PageParams, Depends(get_page_params)]
ClientIpHash = Annotated[str | None, Depends(get_client_ip_hash)]


def content_disposition(disposition: str, filename: str) -> str:
    """RFC 5987 header value, so accented delivery note names survive.

    Control characters are replaced here rather than at each call site. A name
    holding CRLF makes the whole response invalid and the download fails with a
    500 for everyone, the inspector scanning the QR included. Callers do sanitise
    today, but the guarantee belongs with the function that builds the header,
    not with whoever remembers to call a helper first.
    """
    ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
    ascii_name = re.sub(r"[\x00-\x1f\x7f]", "_", ascii_name)
    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"

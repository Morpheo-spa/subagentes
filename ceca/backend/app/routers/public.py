"""The QR viewer. No authentication, no indexing, no cache, no storage URLs.

An unknown token, a revoked token and a withdrawn document are indistinguishable
from outside: all three answer ``SHARE_TOKEN_UNKNOWN`` with a 404.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request, Response
from fastapi.responses import StreamingResponse

from app.deps import Db
from app.errors import NotFoundError
from app.routers import ClientIpHash, content_disposition
from app.schemas.documents import PublicDocumentView
from app.services import documents as documents_service

#: Sent on every public response, success or file.
PUBLIC_HEADERS = {
    "X-Robots-Tag": "noindex, nofollow",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}

TokenPath = Annotated[str, Path(min_length=16, max_length=64)]


def harden(response: Response) -> None:
    response.headers.update(PUBLIC_HEADERS)


router = APIRouter(prefix="/v", tags=["public"], dependencies=[Depends(harden)])


async def _resolve(db: Db, token: str):  # noqa: ANN202 - service-owned shape
    """One answer for unknown, revoked and withdrawn. Never confirm existence."""
    resolution = await documents_service.resolve_share_token(db, token)
    if resolution is None or not resolution.document.is_available:
        raise NotFoundError("SHARE_TOKEN_UNKNOWN")
    return resolution


@router.get("/{token}", response_model=PublicDocumentView)
async def view_document(
    token: TokenPath, request: Request, db: Db, ip_hash: ClientIpHash
) -> PublicDocumentView:
    resolution = await _resolve(db, token)
    document = resolution.document
    await documents_service.record_public_access(
        db,
        document=document,
        share_token=resolution.share_token,
        ip_hash=ip_hash,
        user_agent=request.headers.get("User-Agent"),
    )
    return PublicDocumentView(
        original_filename=document.original_filename,
        issued_at=document.created_at,
        revision=document.revision,
        is_valid_deca=document.is_valid_deca,
        compliance_status=document.compliance_status,
        deca=document.deca,
        file_url=f"/v/{token}/file",
        site_name=getattr(resolution, "site_name", None),
    )


@router.head("/{token}", status_code=200)
async def head_document(token: TokenPath, db: Db) -> Response:
    """Lets a scanner check the link without leaving an access-log entry."""
    await _resolve(db, token)
    return Response(status_code=200, headers=PUBLIC_HEADERS)


@router.get("/{token}/file")
async def stream_document(
    token: TokenPath, request: Request, db: Db, ip_hash: ClientIpHash
) -> StreamingResponse:
    """Always streamed through the API. A signed storage URL never leaves here."""
    resolution = await _resolve(db, token)
    document = resolution.document
    await documents_service.record_public_access(
        db,
        document=document,
        share_token=resolution.share_token,
        ip_hash=ip_hash,
        user_agent=request.headers.get("User-Agent"),
    )
    stream = await documents_service.open_stream(db, document)
    return StreamingResponse(
        stream,
        media_type="application/pdf",
        headers={
            **PUBLIC_HEADERS,
            "Content-Disposition": content_disposition("inline", document.original_filename),
        },
    )

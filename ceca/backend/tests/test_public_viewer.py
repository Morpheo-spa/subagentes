"""The public QR viewer must be uniform, uncacheable and unindexed.

A roadside check is the only legitimate use of ``/v/{token}``. Everything else -
probing for valid tokens, search engines, shared caches - must get nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROUTER = BACKEND_ROOT / "app" / "routers" / "public.py"

pytestmark = pytest.mark.skipif(
    not PUBLIC_ROUTER.exists(), reason="public viewer router not written yet"
)

STORAGE_LEAK_MARKERS = (
    "X-Amz-Signature",
    "x-amz-signature",
    "presigned",
    "storage_key",
    "storageKey",
    "minio",
    "s3.amazonaws.com",
    "blob.core.windows.net",
)


def _comparable(response) -> tuple[int, str]:  # noqa: ANN001
    return response.status_code, response.text


async def _fetch(client, token: str):  # noqa: ANN001, ANN202
    return await client.get(f"/v/{token}")


async def test_unknown_revoked_and_withdrawn_are_indistinguishable(
    client, db, make_tenant, make_document, make_share_token
) -> None:
    """Three different failures, one answer. Otherwise the URL is an oracle."""
    mm, site = await make_tenant()
    revoked_document = await make_document(mm, site, filename="revoked.pdf")
    revoked = await make_share_token(revoked_document, revoked=True)
    withdrawn_document = await make_document(mm, site, filename="withdrawn.pdf", withdrawn=True)
    withdrawn = await make_share_token(withdrawn_document)
    await db.flush()

    unknown_response = await _fetch(client, "this-token-does-not-exist-at-all")
    revoked_response = await _fetch(client, revoked.token)
    withdrawn_response = await _fetch(client, withdrawn.token)

    assert _comparable(unknown_response) == _comparable(revoked_response)
    assert _comparable(unknown_response) == _comparable(withdrawn_response)


async def test_failure_responses_carry_the_mandatory_headers(client) -> None:
    response = await _fetch(client, "still-not-a-real-token")

    assert "noindex" in response.headers.get("X-Robots-Tag", "").lower()
    assert response.headers.get("Cache-Control") == "no-store"


async def test_served_document_carries_the_mandatory_headers(
    client, db, make_tenant, make_document, make_share_token
) -> None:
    mm, site = await make_tenant()
    document = await make_document(mm, site, filename="valid.pdf")
    share = await make_share_token(document)
    await db.flush()

    response = await _fetch(client, share.token)

    assert "noindex" in response.headers.get("X-Robots-Tag", "").lower()
    assert response.headers.get("Cache-Control") == "no-store"


async def test_the_storage_location_is_never_disclosed(
    client, db, make_tenant, make_document, make_share_token
) -> None:
    """Whatever the outcome, the PDF is streamed by us; its location stays ours."""
    mm, site = await make_tenant()
    document = await make_document(mm, site, filename="valid.pdf")
    share = await make_share_token(document)
    await db.flush()

    response = await _fetch(client, share.token)
    body = response.text
    header_blob = " ".join(f"{key}: {value}" for key, value in response.headers.items())

    assert document.storage_key not in body
    assert document.storage_key not in header_blob
    for marker in STORAGE_LEAK_MARKERS:
        assert marker not in body, f"public viewer leaked '{marker}'"
    assert not response.headers.get("Location", "").startswith("http")


async def test_a_revoked_token_stops_working_for_a_live_document(
    client, db, make_tenant, make_document, make_share_token
) -> None:
    """Revocation kills the label, not the archived document."""
    mm, site = await make_tenant()
    document = await make_document(mm, site, filename="live.pdf")
    share = await make_share_token(document, revoked=True)
    await db.flush()

    response = await _fetch(client, share.token)

    assert response.status_code == 404

"""The print queue names its labels, and only ever holds documents worth a label.

Two things a real browser walk-through turned up. The queue answered
``document: null`` on every item, so the UI listed bare UUIDs and the label
preview printed "135683FB · —" instead of the name and date that
``label-template.md`` asks for. And a scan could be queued: a QR label on an
image-only PDF presents it as a valid DeCA, which is prohibition 13.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.deps import TenantContext
from app.errors import DomainError
from app.models import ComplianceStatus, DocumentOrigin
from app.models.documents import Document
from app.services import printing as printing_service

UUID_RE = re.compile(r"^[0-9a-f-]{36}$")


async def _sign_in(client: Any, make_tenant: Any, make_user: Any) -> tuple[Any, Any, Any, dict]:
    mm, site = await make_tenant()
    user = await make_user(mm, site, email="printer@estampa-demo.com", role="operator")
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "printer@estampa-demo.com", "password": "test-password"},
    )
    assert response.status_code == 200, response.text
    return mm, site, user, {"Authorization": f"Bearer {response.json()['tokens']['access_token']}"}


def _context(mm: Any, site: Any, user: Any) -> TenantContext:
    return TenantContext(
        user_id=user.id,
        mm_id=mm.id,
        site_id=site.id,
        site_prefix=site.site_prefix,
        permissions=frozenset({"printing:read", "printing:queue", "printing:print"}),
    )


# --- 1. the queue carries the document ---------------------------------------


async def test_queueing_returns_the_document_not_just_its_id(
    client: Any, db: Any, make_tenant: Any, make_user: Any, make_document: Any
) -> None:
    mm, site, _user, headers = await _sign_in(client, make_tenant, make_user)
    document = await make_document(mm, site, filename="albaran-octubre.pdf")

    response = await client.post(
        "/api/v1/printing/queue/",
        headers=headers,
        json={"document_ids": [str(document.id)], "copies": 2},
    )

    assert response.status_code == 201, response.text
    (item,) = response.json()["items"]
    assert item["document_id"] == str(document.id)
    assert item["copies"] == 2
    assert item["document"] is not None, "the queue must not answer document: null"
    assert item["document"]["original_filename"] == "albaran-octubre.pdf"
    assert item["document"]["created_at"], "the label prints the upload date"
    assert item["document"]["is_valid_deca"] is True


async def test_listing_the_queue_carries_the_document_too(
    client: Any, db: Any, make_tenant: Any, make_user: Any, make_document: Any
) -> None:
    mm, site, _user, headers = await _sign_in(client, make_tenant, make_user)
    first = await make_document(mm, site, filename="primero.pdf")
    second = await make_document(mm, site, filename="segundo.pdf")
    await client.post(
        "/api/v1/printing/queue/",
        headers=headers,
        json={"document_ids": [str(first.id), str(second.id)]},
    )

    response = await client.get("/api/v1/printing/queue/", headers=headers)

    assert response.status_code == 200, response.text
    names = [item["document"]["original_filename"] for item in response.json()["items"]]
    assert names == ["primero.pdf", "segundo.pdf"]
    assert response.json()["total"] == 2


async def test_the_queue_never_shows_another_tenants_document(
    db: Any, make_tenant: Any, make_user: Any, make_document: Any
) -> None:
    """The join that loads the document carries the tenant filter on both sides."""
    mm_a, site_a = await make_tenant(slug="tenant-a", prefix="AAA")
    mm_b, site_b = await make_tenant(slug="tenant-b", prefix="BBB")
    user_a = await make_user(mm_a, site_a, email="a@estampa-demo.com")
    document_b = await make_document(mm_b, site_b, filename="ajeno.pdf")

    with pytest.raises(DomainError) as raised:
        await printing_service.add_to_queue(
            db, _context(mm_a, site_a, user_a), document_ids=[document_b.id]
        )
    assert raised.value.code == "DOCUMENT_NOT_FOUND"

    rows, total = await printing_service.list_queue(db, _context(mm_a, site_a, user_a))
    assert rows == [] and total == 0


async def test_the_rendered_label_carries_the_name_and_the_upload_date(
    client: Any,
    db: Any,
    make_tenant: Any,
    make_user: Any,
    make_document: Any,
    make_share_token: Any,
) -> None:
    """``label-template.md``: name on two lines, short GUID and upload date below."""
    mm, site, user, headers = await _sign_in(client, make_tenant, make_user)
    document = await make_document(mm, site, filename="Albarán <2026> & Cía.pdf")
    await make_share_token(document)
    await client.post(
        "/api/v1/printing/queue/", headers=headers, json={"document_ids": [str(document.id)]}
    )
    created = await client.post(
        "/api/v1/printing/jobs/", headers=headers, json={"template_code": "thermal_50x30"}
    )
    assert created.status_code == 201, created.text

    labels = await printing_service.labels_for_job(
        db,
        _context(mm, site, user),
        await printing_service._job(db, _context(mm, site, user), uuid.UUID(created.json()["id"])),
    )
    rendered = await client.get(
        f"/api/v1/printing/jobs/{created.json()['id']}/render", headers=headers
    )

    assert labels[0]["filename"] == "Albarán <2026> & Cía.pdf"
    assert labels[0]["short_id"] == str(document.id)[:8]
    assert labels[0]["uploaded_at"] == document.created_at.date().isoformat()
    assert labels[0]["qr_url"].startswith("http://testserver/v/")
    assert rendered.status_code == 200
    assert "Albarán &lt;2026&gt; &amp; Cía.pdf" in rendered.text
    assert document.created_at.date().isoformat() in rendered.text
    assert str(document.id)[:8] in rendered.text


# --- 4. a scan never gets a label ---------------------------------------------


async def test_a_scan_is_refused_at_the_queue(
    client: Any, db: Any, make_tenant: Any, make_user: Any, make_document: Any
) -> None:
    """Prohibition 13: a QR label on a scan presents it as a valid DeCA."""
    mm, site, _user, headers = await _sign_in(client, make_tenant, make_user)
    scan = await make_document(
        mm,
        site,
        filename="foto-albaran.pdf",
        origin=DocumentOrigin.UPLOADED_SCANNED,
        compliance=ComplianceStatus.NOT_A_DECA,
    )

    response = await client.post(
        "/api/v1/printing/queue/", headers=headers, json={"document_ids": [str(scan.id)]}
    )

    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "PRINT_NOT_A_DECA"
    assert detail["params"] == {"filename": "foto-albaran.pdf"}
    assert "foto-albaran.pdf" in detail["message"]
    listed = await client.get("/api/v1/printing/queue/", headers=headers)
    assert listed.json()["total"] == 0, "nothing of the batch may be queued"


async def test_one_scan_in_a_batch_keeps_the_whole_batch_out(
    client: Any, db: Any, make_tenant: Any, make_user: Any, make_document: Any
) -> None:
    mm, site, _user, headers = await _sign_in(client, make_tenant, make_user)
    good = await make_document(mm, site, filename="bueno.pdf")
    scan = await make_document(
        mm,
        site,
        filename="escaneo.pdf",
        origin=DocumentOrigin.UPLOADED_SCANNED,
        compliance=ComplianceStatus.NOT_A_DECA,
    )

    response = await client.post(
        "/api/v1/printing/queue/",
        headers=headers,
        json={"document_ids": [str(good.id), str(scan.id)]},
    )

    assert response.status_code == 422
    assert (await client.get("/api/v1/printing/queue/", headers=headers)).json()["total"] == 0


async def test_a_superseded_revision_is_refused_at_the_queue(
    client: Any, db: Any, make_tenant: Any, make_user: Any, make_document: Any
) -> None:
    mm, site, _user, headers = await _sign_in(client, make_tenant, make_user)
    old = await make_document(mm, site, filename="v1.pdf", compliance=ComplianceStatus.SUPERSEDED)
    old.superseded_at = datetime.now(UTC)
    await db.flush()

    response = await client.post(
        "/api/v1/printing/queue/", headers=headers, json={"document_ids": [str(old.id)]}
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "PRINT_DOCUMENT_UNAVAILABLE"
    assert response.json()["detail"]["params"] == {"filename": "v1.pdf"}


async def test_a_withdrawn_document_is_refused_at_the_queue(
    client: Any, db: Any, make_tenant: Any, make_user: Any, make_document: Any
) -> None:
    mm, site, _user, headers = await _sign_in(client, make_tenant, make_user)
    gone = await make_document(mm, site, filename="retirado.pdf", withdrawn=True)

    response = await client.post(
        "/api/v1/printing/queue/", headers=headers, json={"document_ids": [str(gone.id)]}
    )

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "PRINT_DOCUMENT_UNAVAILABLE"


async def test_the_guard_compares_the_status_the_database_hands_back(
    db: Any, make_tenant: Any, make_user: Any, make_document: Any
) -> None:
    """Rows loaded from the database hold plain strings, not enum members."""
    mm, site = await make_tenant()
    user = await make_user(mm, site)
    scan = await make_document(
        mm, site, origin=DocumentOrigin.UPLOADED_SCANNED, compliance=ComplianceStatus.NOT_A_DECA
    )
    db.expunge(scan)
    reloaded = await db.get(Document, scan.id)
    assert isinstance(reloaded.compliance_status, str)

    with pytest.raises(DomainError) as raised:
        await printing_service.add_to_queue(
            db, _context(mm, site, user), document_ids=[reloaded.id]
        )

    assert raised.value.code == "PRINT_NOT_A_DECA"


async def test_an_incomplete_but_native_deca_can_still_be_labelled(
    db: Any, make_tenant: Any, make_user: Any, make_document: Any
) -> None:
    """Only a scan is refused outright; incomplete metadata is fixable later."""
    mm, site = await make_tenant()
    user = await make_user(mm, site)
    document = await make_document(
        mm, site, origin=DocumentOrigin.UPLOADED_NATIVE, compliance=ComplianceStatus.INCOMPLETE
    )

    items = await printing_service.add_to_queue(
        db, _context(mm, site, user), document_ids=[document.id]
    )

    assert [item.document.id for item in items] == [document.id]

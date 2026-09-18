"""Rows loaded from the database hold strings, not enum members.

Every status column is a plain VARCHAR. An object built in the same session
still carries the enum member it was assigned, so identity comparisons pass in
tests and fail on every real row. The public viewer answered "not available"
for every valid QR because of it. These tests load through a fresh session.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.models.documents import ComplianceStatus, Document, DocumentOrigin, DocumentStatus


async def test_availability_holds_for_a_row_loaded_fresh(
    db: Any, engine: Any, make_tenant: Any, make_document: Any
) -> None:
    mm, site = await make_tenant()
    document = await make_document(
        mm,
        site,
        origin=DocumentOrigin.GENERATED,
        status=DocumentStatus.READY,
        compliance=ComplianceStatus.COMPLIANT,
    )
    await db.commit()

    async with async_sessionmaker(engine, expire_on_commit=False)() as fresh:
        loaded = (
            await fresh.execute(select(Document).where(Document.id == document.id))
        ).scalar_one()
        assert type(loaded.status) is str, "the column really does come back as a plain string"
        assert loaded.is_available, "a ready, live document must be available"
        assert loaded.is_valid_deca, "a compliant generated document must count as a DeCA"


async def test_a_scan_is_still_refused_when_loaded_fresh(
    db: Any, engine: Any, make_tenant: Any, make_document: Any
) -> None:
    mm, site = await make_tenant()
    document = await make_document(
        mm,
        site,
        origin=DocumentOrigin.UPLOADED_SCANNED,
        compliance=ComplianceStatus.NOT_A_DECA,
    )
    await db.commit()

    async with async_sessionmaker(engine, expire_on_commit=False)() as fresh:
        loaded = (
            await fresh.execute(select(Document).where(Document.id == document.id))
        ).scalar_one()
        assert not loaded.is_valid_deca

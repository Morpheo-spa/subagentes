#!/usr/bin/env python3
"""Load a demo tenant: one MM, two sites, three users, storage, retention, documents.

Idempotent: every row is looked up by a natural key before being created, so
running it twice changes nothing.

    python scripts/seed_demo.py                 # uses DATABASE_URL from the env
    DATABASE_URL=... python scripts/seed_demo.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.models import (  # noqa: E402
    MM,
    ComplianceStatus,
    Document,
    DocumentOrigin,
    RetentionPolicy,
    ShareToken,
    Site,
    StorageBackend,
    User,
    UserSite,
)
from app.models.documents import DecaStatus, DocumentStatus  # noqa: E402
from app.models.retention import RetentionAction  # noqa: E402
from app.models.storage import StorageKind  # noqa: E402
from app.security import hash_password, new_share_token  # noqa: E402

ModelT = TypeVar("ModelT")

DEMO_PASSWORD = "estampa-demo-2026"  # noqa: S105  (local fixture, never a real secret)
MM_SLUG = "demo-logistica"
DEMO_USERS = (
    ("viewer@demo.test", "Vera Visor", "viewer"),
    ("operador@demo.test", "Olga Operaria", "operator"),
    ("admin@demo.test", "Adrián Admin", "mm_admin"),
)
DEMO_DOCUMENTS = (
    ("albaran-1001.pdf", DocumentOrigin.GENERATED, ComplianceStatus.COMPLIANT),
    ("albaran-1002.pdf", DocumentOrigin.UPLOADED_NATIVE, ComplianceStatus.COMPLIANT),
    ("albaran-1003.pdf", DocumentOrigin.UPLOADED_NATIVE, ComplianceStatus.INCOMPLETE),
    ("escaneo-1004.pdf", DocumentOrigin.UPLOADED_SCANNED, ComplianceStatus.NOT_A_DECA),
)


async def get_or_create(
    session: AsyncSession, model: type[ModelT], *, match: dict[str, Any], defaults: dict[str, Any]
) -> ModelT:
    """Fetch by natural key or insert. The whole script's idempotency lives here."""
    conditions = [getattr(model, field) == value for field, value in match.items()]
    existing = (await session.execute(select(model).where(*conditions))).scalar_one_or_none()
    if existing is not None:
        return existing
    instance = model(**match, **defaults)
    session.add(instance)
    await session.flush()
    return instance


def deca_payload(index: int, complete: bool) -> dict[str, str]:
    payload = {
        "cargador_nombre": "Distribuciones Demo SL",
        "cargador_nif": "B12345674",
        "cargador_domicilio": "Calle Mayor 1, 28013 Madrid",
        "transportista_nombre": "Transportes Demo SA",
        "transportista_nif": "A58818501",
        "origen": "Madrid",
        "destino": "Zaragoza",
        "mercancia_naturaleza": "Palés de material de oficina",
        "mercancia_peso": str(400 + index * 25),
        "mercancia_peso_unidad": "kg",
        "fecha_transporte": datetime.now(UTC).date().isoformat(),
        "matricula_vehiculo": f"1234 AB{index}",
    }
    if not complete:
        del payload["matricula_vehiculo"]
        del payload["mercancia_peso"]
    return payload


async def seed_company(session: AsyncSession) -> MM:
    return await get_or_create(
        session,
        MM,
        match={"slug": MM_SLUG},
        defaults={"name": "Demo Logística SL", "tax_id": "B12345674", "is_active": True},
    )


async def seed_sites(session: AsyncSession, mm: MM) -> list[Site]:
    specs = (("Centro Madrid", "MAD"), ("Centro Zaragoza", "ZGZ"))
    return [
        await get_or_create(
            session,
            Site,
            match={"mm_id": mm.id, "site_prefix": prefix},
            defaults={"name": name, "timezone": "Europe/Madrid", "is_active": True},
        )
        for name, prefix in specs
    ]


async def seed_users(session: AsyncSession, mm: MM, sites: list[Site]) -> list[User]:
    hashed = hash_password(DEMO_PASSWORD)
    users: list[User] = []
    for email, full_name, role in DEMO_USERS:
        user = await get_or_create(
            session,
            User,
            match={"mm_id": mm.id, "email": email},
            defaults={
                "full_name": full_name,
                "hashed_password": hashed,
                "is_active": True,
                "is_superuser": False,
                "default_site_id": sites[0].id,
                "locale": "es",
            },
        )
        # An admin works across sites; the other roles stay on the first one.
        memberships = sites if role == "mm_admin" else sites[:1]
        for site in memberships:
            await get_or_create(
                session,
                UserSite,
                match={"user_id": user.id, "site_id": site.id},
                defaults={"role": role, "extra_permissions": []},
            )
        users.append(user)
    return users


async def seed_storage(session: AsyncSession, mm: MM, site: Site) -> StorageBackend:
    return await get_or_create(
        session,
        StorageBackend,
        match={"mm_id": mm.id, "site_id": site.id, "name": "Almacén local"},
        defaults={
            "kind": StorageKind.LOCAL,
            "config": {"base_path": "/var/lib/estampa/storage/demo"},
            "is_default": True,
            "is_active": True,
        },
    )


async def seed_retention(session: AsyncSession, mm: MM, site: Site) -> RetentionPolicy:
    return await get_or_create(
        session,
        RetentionPolicy,
        match={"mm_id": mm.id, "site_id": site.id, "name": "Mínimo legal DeCA"},
        defaults={
            "retention_days": 365,
            "action": RetentionAction.WITHDRAW_FILE,
            "legal_basis": "Resolución de 5 de junio de 2026: conservación mínima de 1 año",
            "warn_days_before": 30,
            "is_default": True,
            "is_active": True,
        },
    )


async def seed_documents(
    session: AsyncSession,
    mm: MM,
    site: Site,
    uploader: User,
    backend: StorageBackend,
    policy: RetentionPolicy,
) -> list[Document]:
    now = datetime.now(UTC)
    documents: list[Document] = []
    for index, (filename, origin, compliance) in enumerate(DEMO_DOCUMENTS, start=1):
        complete = compliance is ComplianceStatus.COMPLIANT
        document = await get_or_create(
            session,
            Document,
            match={"mm_id": mm.id, "site_id": site.id, "original_filename": filename},
            defaults={
                "storage_backend_id": backend.id,
                "storage_key": f"{site.site_prefix}/{uuid.uuid4()}.pdf",
                "byte_size": 120_000 + index * 1_000,
                "sha256": f"{index:064d}",
                "page_count": 1,
                "status": DocumentStatus.READY,
                "deca": deca_payload(index, complete),
                "deca_status": DecaStatus.COMPLETE if complete else DecaStatus.INCOMPLETE,
                "deca_catalog_version": 1,
                "origin": origin,
                "compliance_status": compliance,
                "has_text_layer": origin is not DocumentOrigin.UPLOADED_SCANNED,
                "qr_embedded": origin is DocumentOrigin.GENERATED,
                "uploaded_by_id": uploader.id,
                "retention_policy_id": policy.id,
                "expires_at": now + timedelta(days=policy.retention_days),
            },
        )
        await get_or_create(
            session,
            ShareToken,
            match={"document_id": document.id},
            defaults={"token": new_share_token(), "access_count": 0},
        )
        documents.append(document)
    return documents


async def seed(session: AsyncSession) -> None:
    mm = await seed_company(session)
    sites = await seed_sites(session, mm)
    users = await seed_users(session, mm, sites)
    backend = await seed_storage(session, mm, sites[0])
    policy = await seed_retention(session, mm, sites[0])
    documents = await seed_documents(session, mm, sites[0], users[-1], backend, policy)
    print(
        f"MM {mm.slug}: {len(sites)} sites, {len(users)} users, "
        f"{len(documents)} documents. Password for every demo user: {DEMO_PASSWORD}"
    )


def refuse_outside_development(settings: Any) -> None:
    """Demo users ship with a published password. They must never reach production.

    Pass --i-know-what-i-am-doing to override, for the rare case of seeding a
    throwaway staging tenant on purpose.
    """
    if settings.environment != "production":
        return
    if "--i-know-what-i-am-doing" in sys.argv:
        print("WARNING: seeding demo data into a production environment.", file=sys.stderr)
        return
    print(
        "Refusing to run: ENVIRONMENT=production.\n"
        f"This script creates users whose password is published in {Path(__file__).name}.\n"
        "Override with --i-know-what-i-am-doing if that is genuinely what you want.",
        file=sys.stderr,
    )
    raise SystemExit(2)


async def main() -> None:
    settings = get_settings()
    refuse_outside_development(settings)
    engine = create_async_engine(str(settings.database_url))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        await seed(session)
        await session.commit()
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())

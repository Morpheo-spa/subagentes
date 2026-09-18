"""Test harness: environment, database, app client and object factories.

The suite runs against SQLite by default so it needs nothing running. Point
``TEST_DATABASE_URL`` at a Postgres instance to run the same tests there.
"""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


def _seed_environment() -> None:
    """Settings are read at import time, so the environment is set before that."""
    defaults = {
        "ENVIRONMENT": "local",
        "DEBUG": "false",
        "PUBLIC_BASE_URL": "http://testserver",
        "DATABASE_URL": "postgresql+asyncpg://estampa:estampa@localhost:5433/estampa_test",
        "REDIS_URL": "redis://localhost:6380/1",
        "JWT_SECRET_KEY": "test-jwt-secret-key-not-used-anywhere-real-000",
        "STORAGE_SECRET_KEY": Fernet.generate_key().decode(),
        "ACCESS_LOG_IP_SALT": "test-access-log-salt-0000",
        "BILLING_ENABLED": "false",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


_seed_environment()

from sqlalchemy.dialects import postgresql  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.types import JSON, Uuid  # noqa: E402

from app.models import (  # noqa: E402
    MM,
    Base,
    ComplianceStatus,
    Document,
    DocumentOrigin,
    Site,
    StorageBackend,
    User,
    UserSite,
)
from app.models.documents import DecaStatus, DocumentStatus, ShareToken  # noqa: E402
from app.models.storage import StorageKind  # noqa: E402
from app.security import hash_password, new_share_token  # noqa: E402

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


def _sqlite_url(tmp_dir: Path) -> str:
    return f"sqlite+aiosqlite:///{tmp_dir / 'estampa_test.sqlite3'}"


def _make_portable(metadata: Any) -> None:
    """Swap Postgres-only column types so the schema also builds on SQLite.

    Only the test schema is touched. Production DDL comes from the migrations.
    """
    for table in metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, postgresql.JSONB | postgresql.ARRAY):
                column.type = JSON()
            elif isinstance(column.type, postgresql.UUID):
                column.type = Uuid(as_uuid=True)


@pytest.fixture(scope="session")
def database_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    if TEST_DATABASE_URL:
        return TEST_DATABASE_URL
    return _sqlite_url(tmp_path_factory.mktemp("db"))


@pytest.fixture
async def engine(database_url: str):  # noqa: ANN201
    """One engine per test, disposed at the end.

    pytest-asyncio runs every test on its own event loop. A session-scoped
    engine hands later tests pooled asyncpg connections that belong to the first
    test's loop, which surfaces as "attached to a different loop" and "another
    operation is in progress". aiosqlite tolerates that; Postgres, the database
    CI actually runs against, does not.
    """
    if database_url.startswith("sqlite"):
        _make_portable(Base.metadata)
    engine = create_async_engine(database_url, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def db(engine) -> AsyncIterator[AsyncSession]:  # noqa: ANN001
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


# --- Factories ---------------------------------------------------------------


@pytest.fixture
def make_tenant(db: AsyncSession) -> Callable[..., Any]:
    """Create an MM with one site, the pair every scoped row needs."""

    async def factory(slug: str = "demo", prefix: str = "DEM") -> tuple[MM, Site]:
        mm = MM(name=f"MM {slug}", slug=slug, is_active=True)
        db.add(mm)
        await db.flush()
        site = Site(
            mm_id=mm.id,
            name=f"Site {prefix}",
            site_prefix=prefix,
            timezone="Europe/Madrid",
            is_active=True,
        )
        db.add(site)
        await db.flush()
        return mm, site

    return factory


@pytest.fixture
def make_user(db: AsyncSession) -> Callable[..., Any]:
    async def factory(
        mm: MM,
        site: Site,
        *,
        email: str = "user@estampa-demo.com",
        role: str = "operator",
        is_superuser: bool = False,
    ) -> User:
        user = User(
            mm_id=mm.id,
            email=email,
            full_name=email.split("@")[0],
            hashed_password=hash_password("test-password"),
            is_active=True,
            is_superuser=is_superuser,
            default_site_id=site.id,
            locale="es",
        )
        db.add(user)
        await db.flush()
        db.add(UserSite(user_id=user.id, site_id=site.id, role=role, extra_permissions=[]))
        await db.flush()
        return user

    return factory


@pytest.fixture
def make_storage_backend(db: AsyncSession) -> Callable[..., Any]:
    async def factory(mm: MM, site: Site) -> StorageBackend:
        backend = StorageBackend(
            mm_id=mm.id,
            site_id=site.id,
            name="local",
            kind=StorageKind.LOCAL,
            config={"base_path": "/tmp/estampa-test"},  # noqa: S108
            is_default=True,
            is_active=True,
        )
        db.add(backend)
        await db.flush()
        return backend

    return factory


@pytest.fixture
def make_document(db: AsyncSession, make_storage_backend: Callable[..., Any]) -> Callable[..., Any]:
    async def factory(
        mm: MM,
        site: Site,
        *,
        filename: str = "albaran.pdf",
        status: DocumentStatus = DocumentStatus.READY,
        origin: DocumentOrigin = DocumentOrigin.GENERATED,
        compliance: ComplianceStatus = ComplianceStatus.COMPLIANT,
        withdrawn: bool = False,
        backend: StorageBackend | None = None,
    ) -> Document:
        backend = backend or await make_storage_backend(mm, site)
        now = datetime.now(UTC)
        document = Document(
            mm_id=mm.id,
            site_id=site.id,
            original_filename=filename,
            storage_backend_id=backend.id,
            storage_key=f"{site.site_prefix}/{uuid.uuid4()}.pdf",
            byte_size=1024,
            sha256="0" * 64,
            page_count=1,
            status=status,
            deca={},
            deca_status=DecaStatus.COMPLETE,
            deca_catalog_version=1,
            origin=origin,
            compliance_status=compliance,
            has_text_layer=origin is not DocumentOrigin.UPLOADED_SCANNED,
            qr_embedded=origin is DocumentOrigin.GENERATED,
            expires_at=now + timedelta(days=365),
            withdrawn_at=now if withdrawn else None,
            withdrawn_reason="retention sweep" if withdrawn else None,
        )
        db.add(document)
        await db.flush()
        return document

    return factory


@pytest.fixture
def make_share_token(db: AsyncSession) -> Callable[..., Any]:
    async def factory(document: Document, *, revoked: bool = False) -> ShareToken:
        token = ShareToken(
            document_id=document.id,
            token=new_share_token(),
            access_count=0,
            revoked_at=datetime.now(UTC) if revoked else None,
        )
        db.add(token)
        await db.flush()
        return token

    return factory


# --- Application -------------------------------------------------------------


class InMemoryRedis:
    """Enough Redis for the JWT blacklist, so the suite needs no broker."""

    def __init__(self) -> None:
        self._entries: dict[str, str] = {}

    async def exists(self, key: str) -> int:
        return int(key in self._entries)

    async def setex(self, key: str, _ttl: int, value: str) -> None:
        self._entries[key] = value

    async def get(self, key: str) -> str | None:
        return self._entries.get(key)

    async def delete(self, *keys: str) -> int:
        return sum(self._entries.pop(key, None) is not None for key in keys)

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self._entries.clear()


@pytest.fixture(autouse=True)
def redis_stub(monkeypatch: pytest.MonkeyPatch) -> InMemoryRedis:
    """Swap the Redis client unless TEST_REDIS_URL points at a real one."""
    import app.cache as cache

    stub = InMemoryRedis()
    if not os.environ.get("TEST_REDIS_URL"):
        monkeypatch.setattr(cache, "_client", stub, raising=False)
    return stub


@pytest.fixture
def app():  # noqa: ANN201
    """The FastAPI app, or a skip while the routers are still being written."""
    main = pytest.importorskip("app.main", reason="app.main is not importable yet")
    return main.app


@pytest.fixture
async def client(app, db: AsyncSession) -> AsyncIterator[Any]:  # noqa: ANN001
    """ASGI client wired to the test session, so requests see the fixtures' rows."""
    import httpx

    from app.deps import get_db

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http_client:
        yield http_client
    app.dependency_overrides.pop(get_db, None)

"""Storage backends. Credentials go in encrypted and never come back out."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select, update

from app.deps import Db, TenantContext, require_permission, scoped_select
from app.errors import ConflictError, NotFoundError
from app.models.storage import StorageBackend
from app.routers import ClientIpHash, Page
from app.schemas.common import Acknowledgement, PageResponse
from app.schemas.storage import (
    StorageBackendCreate,
    StorageBackendRead,
    StorageBackendUpdate,
    StorageTestResult,
)
from app.security import encrypt_secret
from app.services import audit as audit_service
from app.services import storage as storage_service
from app.services.storage.validation import validate_config

router = APIRouter(prefix="/storage", tags=["storage"])

ReadCtx = Annotated[TenantContext, Depends(require_permission("storage:read"))]
ManageCtx = Annotated[TenantContext, Depends(require_permission("storage:manage"))]


async def _get_backend(db: Db, ctx: TenantContext, backend_id: uuid.UUID) -> StorageBackend:
    stmt = scoped_select(StorageBackend, ctx).where(StorageBackend.id == backend_id)
    backend = (await db.execute(stmt)).scalar_one_or_none()
    if backend is None:
        raise NotFoundError("STORAGE_BACKEND_NOT_FOUND")
    return backend


async def _demote_other_defaults(db: Db, ctx: TenantContext, keep_id: uuid.UUID | None) -> None:
    stmt = (
        update(StorageBackend)
        .where(
            StorageBackend.mm_id == ctx.mm_id,
            StorageBackend.site_id == ctx.site_id,
            StorageBackend.is_default.is_(True),
        )
        .values(is_default=False)
    )
    if keep_id is not None:
        stmt = stmt.where(StorageBackend.id != keep_id)
    await db.execute(stmt)


async def _audit(
    db: Db,
    ctx: TenantContext,
    backend: StorageBackend,
    action: str,
    ip_hash: str | None,
) -> None:
    await audit_service.record(
        db,
        mm_id=ctx.mm_id,
        site_id=ctx.site_id,
        actor_user_id=ctx.user_id,
        action=action,
        object_type="storage_backend",
        object_id=backend.id,
        payload={"name": backend.name, "kind": backend.kind.value},
        ip_hash=ip_hash,
    )


@router.get("/", response_model=PageResponse[StorageBackendRead])
async def list_backends(ctx: ReadCtx, db: Db, page: Page) -> PageResponse[StorageBackendRead]:
    stmt = scoped_select(StorageBackend, ctx)
    total = await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = (
        await db.execute(
            stmt.order_by(StorageBackend.is_default.desc(), StorageBackend.name)
            .offset(page.offset)
            .limit(page.limit)
        )
    ).scalars()
    return PageResponse.of([StorageBackendRead.model_validate(row) for row in rows], total, page)


@router.post("/", response_model=StorageBackendRead, status_code=status.HTTP_201_CREATED)
async def create_backend(
    payload: StorageBackendCreate, ctx: ManageCtx, db: Db, ip_hash: ClientIpHash
) -> StorageBackendRead:
    backend = StorageBackend(
        mm_id=ctx.mm_id,
        site_id=ctx.site_id,
        name=payload.name,
        kind=payload.kind,
        config=validate_config(payload.kind.value, payload.config),
        config_encrypted=(encrypt_secret(json.dumps(payload.secrets)) if payload.secrets else None),
        is_default=payload.is_default,
        is_active=payload.is_active,
    )
    db.add(backend)
    await db.flush()
    if backend.is_default:
        await _demote_other_defaults(db, ctx, backend.id)
    await _audit(db, ctx, backend, "storage_backend.created", ip_hash)
    return StorageBackendRead.model_validate(backend)


@router.get("/{backend_id}", response_model=StorageBackendRead)
async def get_backend(backend_id: uuid.UUID, ctx: ReadCtx, db: Db) -> StorageBackendRead:
    return StorageBackendRead.model_validate(await _get_backend(db, ctx, backend_id))


@router.patch("/{backend_id}", response_model=StorageBackendRead)
async def update_backend(
    backend_id: uuid.UUID,
    payload: StorageBackendUpdate,
    ctx: ManageCtx,
    db: Db,
    ip_hash: ClientIpHash,
) -> StorageBackendRead:
    backend = await _get_backend(db, ctx, backend_id)
    if payload.version is not None and payload.version != backend.version:
        raise ConflictError("VERSION_CONFLICT")

    changes = payload.model_dump(exclude_unset=True, exclude={"version", "secrets"})
    if "config" in changes and changes["config"] is not None:
        # The kind cannot change, so the stored one decides how to read the config.
        changes["config"] = validate_config(backend.kind.value, changes["config"])
    for field, value in changes.items():
        setattr(backend, field, value)
    if payload.secrets is not None:
        backend.config_encrypted = (
            encrypt_secret(json.dumps(payload.secrets)) if payload.secrets else None
        )
    await db.flush()
    if backend.is_default:
        await _demote_other_defaults(db, ctx, backend.id)
    await _audit(db, ctx, backend, "storage_backend.updated", ip_hash)
    return StorageBackendRead.model_validate(backend)


@router.delete("/{backend_id}", response_model=Acknowledgement)
async def deactivate_backend(
    backend_id: uuid.UUID, ctx: ManageCtx, db: Db, ip_hash: ClientIpHash
) -> Acknowledgement:
    """Deactivated, not deleted: archived documents still point at it."""
    backend = await _get_backend(db, ctx, backend_id)
    backend.is_active = False
    backend.is_default = False
    await db.flush()
    await _audit(db, ctx, backend, "storage_backend.deactivated", ip_hash)
    return Acknowledgement()


@router.post("/{backend_id}/test", response_model=StorageTestResult)
async def test_backend(backend_id: uuid.UUID, ctx: ManageCtx, db: Db) -> StorageTestResult:
    backend = await _get_backend(db, ctx, backend_id)
    ok = await storage_service.health_check(db, backend)
    backend.last_health_ok = ok
    await db.flush()
    return StorageTestResult(
        ok=ok,
        kind=backend.kind,
        checked_at=datetime.now(UTC),
        code=None if ok else "STORAGE_UNREACHABLE",
    )

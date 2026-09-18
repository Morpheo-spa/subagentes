"""The DECA field catalogue and dry-run validation.

Which fields a delivery note must carry is data, not code: it is served from
``deca_field_definitions`` and the frontend builds its form from the answer.
"""

from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.deps import Db, Language, TenantContext, require_permission
from app.errors import localised_message
from app.models.deca import DecaFieldDefinition
from app.models.documents import DecaStatus
from app.schemas.deca import (
    DecaCatalogResponse,
    DecaFieldErrorRead,
    DecaFieldRead,
    DecaValidateRequest,
    DecaValidationResult,
)
from app.services import deca as deca_service

router = APIRouter(prefix="/deca", tags=["deca"])

ReadCtx = Annotated[TenantContext, Depends(require_permission("documents:read"))]


def _choices(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return [str(choice) for choice in parsed] if isinstance(parsed, list) else []


def _field_read(definition: DecaFieldDefinition) -> DecaFieldRead:
    return DecaFieldRead.model_validate(definition).model_copy(
        update={"choices": _choices(definition.choices)}
    )


@router.get("/fields", response_model=DecaCatalogResponse)
async def list_fields(ctx: ReadCtx, db: Db) -> DecaCatalogResponse:
    """Global catalogue: labels in both languages, the client picks one."""
    stmt = (
        select(DecaFieldDefinition)
        .where(DecaFieldDefinition.is_active.is_(True))
        .order_by(DecaFieldDefinition.sort_order, DecaFieldDefinition.code)
    )
    definitions = list((await db.execute(stmt)).scalars())
    return DecaCatalogResponse(
        catalog_version=max((definition.catalog_version for definition in definitions), default=1),
        fields=[_field_read(definition) for definition in definitions],
    )


@router.post("/validate", response_model=DecaValidationResult)
async def validate_deca(
    payload: DecaValidateRequest, ctx: ReadCtx, db: Db, language: Language
) -> DecaValidationResult:
    """Checks the metadata without storing anything, for live form feedback."""
    validator = await deca_service.DecaValidator.load(db)
    errors = validator.validate(payload.deca)
    return DecaValidationResult(
        is_complete=not errors,
        deca_status=(DecaStatus.COMPLETE.value if not errors else DecaStatus.INCOMPLETE.value),
        catalog_version=validator.catalog_version,
        errors=[
            DecaFieldErrorRead(
                field=error.field,
                code=error.code,
                message=localised_message(error.code, language, error.params),
                params=error.params,
            )
            for error in errors
        ],
    )

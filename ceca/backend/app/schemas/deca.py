"""The DECA field catalogue and standalone validation."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from app.schemas.common import Schema


class DecaFieldRead(Schema):
    """One field of the delivery note, with both labels for the client to pick."""

    code: str
    label_es: str
    label_en: str
    help_es: str | None = None
    help_en: str | None = None
    data_type: str
    is_required: bool
    max_length: int | None = None
    pattern: str | None = None
    choices: list[str] = Field(default_factory=list)
    legal_reference: str | None = None
    sort_order: int


class DecaCatalogResponse(Schema):
    catalog_version: int
    fields: list[DecaFieldRead]


class DecaFieldErrorRead(Schema):
    field: str
    code: str
    message: str
    params: dict[str, Any] = Field(default_factory=dict)


class DecaValidateRequest(Schema):
    deca: dict[str, Any] = Field(default_factory=dict)


class DecaValidationResult(Schema):
    """``is_complete`` is what decides ``Document.deca_status``."""

    is_complete: bool
    deca_status: str
    catalog_version: int
    errors: list[DecaFieldErrorRead] = Field(default_factory=list)

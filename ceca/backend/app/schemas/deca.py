"""The DECA field catalogue and standalone validation."""

from __future__ import annotations

import json
from typing import Any

from pydantic import Field, field_validator

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

    @field_validator("choices", mode="before")
    @classmethod
    def _choices_from_storage(cls, value: object) -> list[str]:
        """The column is JSON text, or NULL when a field has no fixed options.

        Converting here, before validation, means any code path that builds this
        schema from a row gets a list. Doing it after validation, as the router
        once did, never ran: pydantic had already refused the NULL.
        """
        if value is None or value == "":
            return []
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return []
            return [str(item) for item in parsed] if isinstance(parsed, list) else []
        if isinstance(value, list | tuple):
            return [str(item) for item in value]
        return []

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

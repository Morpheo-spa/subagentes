"""Validation of DECA metadata against the catalogue in force.

Which fields a delivery note must carry is a legal question whose answer
changes, so the catalogue lives in ``deca_field_definitions`` and this module
never branches on a field code.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.deca import DecaFieldDefinition, DecaFieldType

#: A field whose code ends like this holds a Spanish tax ID. A convention of the
#: catalogue data, so a new party added to the JSON is checked without a change
#: here.
TAX_ID_SUFFIX = "_nif"
#: Art. 6 demands the contracting shipper and the actual carrier be identified
#: expressly and separately: two parties, never the same one twice.
PARTY_PREFIXES = ("cargador", "transportista")

NIF_LETTERS = "TRWAGMYFPDXBNJZSQVHLCKE"
NIE_PREFIXES = {"X": "0", "Y": "1", "Z": "2"}
CIF_CONTROL_LETTERS = "JABCDEFGHI"
CIF_LETTER_ONLY = set("KPQRSNW")
CIF_DIGIT_ONLY = set("ABEH")

_NIF_RE = re.compile(r"^\d{8}[A-Z]$")
_NIE_RE = re.compile(r"^[XYZ]\d{7}[A-Z]$")
_CIF_RE = re.compile(r"^[ABCDEFGHJKLMNPQRSUVW]\d{7}[0-9A-J]$")
_SEPARATORS = re.compile(r"[\s.\-]")


@dataclass(frozen=True)
class FieldError:
    """One problem with one field. Codes live in ``app/i18n/errors.json``."""

    field: str
    code: str
    params: dict[str, Any] = dataclass_field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """A catalogue row, detached from the session."""

    code: str
    label_es: str
    label_en: str
    data_type: DecaFieldType
    is_required: bool
    max_length: int | None
    pattern: str | None
    choices: tuple[str, ...]
    catalog_version: int

    def label(self, language: str) -> str:
        return self.label_en if language == "en" else self.label_es


class DecaValidator:
    """Validates a metadata dict against the active field catalogue."""

    def __init__(self, specs: list[FieldSpec]) -> None:
        self._specs = specs

    @classmethod
    async def load(cls, db: AsyncSession) -> DecaValidator:
        """Read the catalogue. A global table, so no tenant filter applies."""
        stmt = (
            select(DecaFieldDefinition)
            .where(DecaFieldDefinition.is_active.is_(True))
            .order_by(DecaFieldDefinition.sort_order)
        )
        rows = (await db.execute(stmt)).scalars().all()
        return cls([_spec_from(row) for row in rows])

    @property
    def catalog_version(self) -> int:
        return max((spec.catalog_version for spec in self._specs), default=1)

    @property
    def specs(self) -> list[FieldSpec]:
        return list(self._specs)

    def label_for(self, code: str, language: str = "es") -> str:
        for spec in self._specs:
            if spec.code == code:
                return spec.label(language)
        return code

    def validate(self, values: dict[str, Any]) -> list[FieldError]:
        errors: list[FieldError] = []
        for spec in self._specs:
            errors.extend(_validate_field(spec, values.get(spec.code)))
        errors.extend(self._validate_parties(values))
        return errors

    def is_complete(self, values: dict[str, Any]) -> bool:
        """True when every required field of the catalogue is present and valid."""
        return not self.validate(values)

    def _validate_parties(self, values: dict[str, Any]) -> list[FieldError]:
        """Both parties must be told apart, so the same tax ID cannot cover both."""
        by_party: dict[str, str] = {}
        for prefix in PARTY_PREFIXES:
            code = self._tax_id_code_for(prefix)
            if code is not None:
                by_party[code] = _normalise_tax_id(str(values.get(code) or ""))
        given = [value for value in by_party.values() if value]
        if len(given) < len(PARTY_PREFIXES) or len(set(given)) > 1:
            return []
        return [FieldError(field=list(by_party)[-1], code="DECA_PARTIES_NOT_DISTINCT", params={})]

    def _tax_id_code_for(self, prefix: str) -> str | None:
        for spec in self._specs:
            if spec.code.startswith(prefix) and spec.code.endswith(TAX_ID_SUFFIX):
                return spec.code
        return None


def validate_spanish_tax_id(value: str) -> bool:
    """NIF, NIE or CIF, verified against its real check character."""
    candidate = _normalise_tax_id(value)
    if _NIF_RE.match(candidate):
        return candidate[-1] == _nif_control(candidate[:8])
    if _NIE_RE.match(candidate):
        return candidate[-1] == _nif_control(NIE_PREFIXES[candidate[0]] + candidate[1:8])
    if _CIF_RE.match(candidate):
        return _cif_is_valid(candidate)
    return False


def _normalise_tax_id(value: str) -> str:
    return _SEPARATORS.sub("", value).upper()


def _nif_control(digits: str) -> str:
    return NIF_LETTERS[int(digits) % 23]


def _cif_is_valid(candidate: str) -> bool:
    body = candidate[1:8]
    odd = sum(sum(divmod(int(digit) * 2, 10)) for digit in body[0::2])
    even = sum(int(digit) for digit in body[1::2])
    control = (10 - (odd + even) % 10) % 10
    given = candidate[-1]
    organisation = candidate[0]
    if organisation in CIF_LETTER_ONLY:
        return given == CIF_CONTROL_LETTERS[control]
    if organisation in CIF_DIGIT_ONLY:
        return given == str(control)
    return given in (str(control), CIF_CONTROL_LETTERS[control])


def _spec_from(row: DecaFieldDefinition) -> FieldSpec:
    return FieldSpec(
        code=row.code,
        label_es=row.label_es,
        label_en=row.label_en,
        data_type=DecaFieldType(row.data_type),
        is_required=row.is_required,
        max_length=row.max_length,
        pattern=row.pattern,
        choices=_choices_of(row.choices),
        catalog_version=row.catalog_version,
    )


def _choices_of(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return ()
    return tuple(str(choice) for choice in parsed)


def _validate_field(spec: FieldSpec, raw: Any) -> list[FieldError]:
    if _is_blank(raw):
        if spec.is_required:
            return [FieldError(spec.code, "DECA_FIELD_REQUIRED", _label_params(spec))]
        return []
    if not _matches_type(spec, raw):
        return [FieldError(spec.code, "DECA_FIELD_INVALID", _label_params(spec))]
    if not _matches_shape(spec, raw):
        return [FieldError(spec.code, "DECA_FIELD_INVALID", _label_params(spec))]
    if spec.code.endswith(TAX_ID_SUFFIX) and not validate_spanish_tax_id(str(raw)):
        return [FieldError(spec.code, "DECA_NIF_INVALID", {"value": str(raw)})]
    return []


def _label_params(spec: FieldSpec) -> dict[str, str]:
    return {
        "label": spec.label_es,
        "label_es": spec.label_es,
        "label_en": spec.label_en,
    }


def _is_blank(raw: Any) -> bool:
    return raw is None or (isinstance(raw, str) and not raw.strip())


def _matches_type(spec: FieldSpec, raw: Any) -> bool:
    checks: dict[DecaFieldType, Callable[[Any], bool]] = {
        DecaFieldType.NUMBER: _is_positive_number,
        DecaFieldType.DECIMAL: _is_positive_number,
        DecaFieldType.DATE: _is_date,
        DecaFieldType.DATETIME: _is_datetime,
        DecaFieldType.BOOLEAN: _is_boolean,
        DecaFieldType.ENUM: lambda value: str(value) in spec.choices,
    }
    check = checks.get(spec.data_type)
    return check(raw) if check else isinstance(raw, str)


def _matches_shape(spec: FieldSpec, raw: Any) -> bool:
    if not isinstance(raw, str):
        return True
    if spec.max_length is not None and len(raw) > spec.max_length:
        return False
    return not spec.pattern or bool(re.match(spec.pattern, raw))


def _is_positive_number(raw: Any) -> bool:
    try:
        return Decimal(str(raw)) > 0
    except (InvalidOperation, ValueError):
        return False


def _is_date(raw: Any) -> bool:
    if isinstance(raw, date):
        return True
    try:
        date.fromisoformat(str(raw))
    except ValueError:
        return False
    return True


def _is_datetime(raw: Any) -> bool:
    if isinstance(raw, datetime):
        return True
    try:
        datetime.fromisoformat(str(raw))
    except ValueError:
        return False
    return True


def _is_boolean(raw: Any) -> bool:
    return isinstance(raw, bool) or str(raw).lower() in {"true", "false"}

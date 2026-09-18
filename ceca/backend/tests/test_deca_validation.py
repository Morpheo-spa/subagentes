"""DECA validation: real check digits, missing fields, and never blocking an upload.

A delivery note that lacks fields is still archived - it is just *incompleto*.
Refusing the upload would lose the very document the law asks us to keep. Wrong
data is a different matter and is refused.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.models.deca import DecaFieldDefinition

deca = pytest.importorskip("app.services.deca", reason="DECA service not written yet")

CATALOGUE_PATH = Path(__file__).resolve().parents[1] / "app" / "i18n" / "deca_fields.json"
#: The code the catalogue uses for "this required field is not there".
MISSING_FIELD_CODE = "DECA_FIELD_REQUIRED"

# Check characters computed with the official algorithms, not invented.
VALID_NIFS = ("12345678Z", "00000000T", "99999999R")
INVALID_NIFS = ("12345678A", "1234567Z", "ABCDEFGHZ", "", "12345678")
VALID_CIFS = ("B12345674", "A58818501", "Q2826000H")
INVALID_CIFS = ("B12345678", "A58818500", "Z12345674", "B1234567")
VALID_NIES = ("X1234567L", "Y0000000Z")

COMPLETE_PAYLOAD: dict[str, Any] = {
    "cargador_nombre": "Distribuciones Demo SL",
    "cargador_nif": "B12345674",
    "cargador_domicilio": "Calle Mayor 1, 28013 Madrid",
    "transportista_nombre": "Transportes Demo SA",
    "transportista_nif": "A58818501",
    "origen": "Madrid",
    "destino": "Zaragoza",
    "mercancia_naturaleza": "Palés de material de oficina",
    "mercancia_peso": "420",
    "mercancia_peso_unidad": "kg",
    "fecha_transporte": "2026-10-06",
    "matricula_vehiculo": "1234ABC",
}


@pytest.fixture
async def validator(db):  # noqa: ANN001, ANN201
    """A validator loaded from the same catalogue the migration seeds."""
    catalogue = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
    for field in catalogue["fields"]:
        choices = field.get("choices")
        db.add(
            DecaFieldDefinition(
                code=field["code"],
                label_es=field["label_es"],
                label_en=field["label_en"],
                help_es=field.get("help_es"),
                help_en=field.get("help_en"),
                data_type=field.get("data_type", "string"),
                is_required=field.get("is_required", True),
                max_length=field.get("max_length"),
                pattern=field.get("pattern"),
                choices=json.dumps(choices, ensure_ascii=False) if choices else None,
                legal_reference=field.get("legal_reference"),
                sort_order=field.get("sort_order", 0),
                is_active=True,
                catalog_version=catalogue["catalog_version"],
            )
        )
    await db.flush()
    return await deca.DecaValidator.load(db)


def _fields_in_error(errors) -> set[str]:  # noqa: ANN001
    return {error.field for error in errors}


@pytest.mark.parametrize("value", VALID_NIFS + VALID_CIFS + VALID_NIES)
def test_a_real_check_character_is_accepted(value: str) -> None:
    assert deca.validate_spanish_tax_id(value)


@pytest.mark.parametrize("value", INVALID_NIFS + INVALID_CIFS)
def test_a_wrong_check_character_is_rejected(value: str) -> None:
    assert not deca.validate_spanish_tax_id(value)


def test_tax_id_ignores_spaces_and_separators() -> None:
    assert deca.validate_spanish_tax_id(" b-12.345.674 ")


async def test_a_complete_payload_has_no_errors(validator) -> None:  # noqa: ANN001
    assert validator.validate(COMPLETE_PAYLOAD) == []
    assert validator.is_complete(COMPLETE_PAYLOAD)


async def test_a_missing_required_field_is_reported_by_name(validator) -> None:  # noqa: ANN001
    payload = dict(COMPLETE_PAYLOAD)
    del payload["matricula_vehiculo"]

    errors = validator.validate(payload)

    assert "matricula_vehiculo" in _fields_in_error(errors)
    assert not validator.is_complete(payload)


async def test_the_optional_field_may_be_absent(validator) -> None:  # noqa: ANN001
    """`observaciones` is optional: its absence must not make the note incomplete."""
    payload = dict(COMPLETE_PAYLOAD)
    payload.pop("observaciones", None)

    assert validator.is_complete(payload)


async def test_an_empty_payload_reports_every_required_field(validator) -> None:  # noqa: ANN001
    """Incomplete is a state, not an exception: validation always returns a list."""
    errors = validator.validate({})

    assert not validator.is_complete({})
    assert {"cargador_nif", "transportista_nif", "matricula_vehiculo"} <= _fields_in_error(errors)


async def test_an_invalid_tax_id_is_reported_as_invalid_not_missing(
    validator,  # noqa: ANN001
) -> None:
    payload = dict(COMPLETE_PAYLOAD) | {"cargador_nif": "B12345678"}

    errors = [error for error in validator.validate(payload) if error.field == "cargador_nif"]

    assert errors, "a tax ID with a wrong check character must be reported"
    assert all(error.code != MISSING_FIELD_CODE for error in errors)


async def test_the_two_parties_must_be_told_apart(validator) -> None:  # noqa: ANN001
    """Art. 6: shipper and carrier are identified expressly and separately."""
    payload = dict(COMPLETE_PAYLOAD) | {"transportista_nif": COMPLETE_PAYLOAD["cargador_nif"]}

    assert not validator.is_complete(payload)


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "app" / "services" / "documents.py").exists(),
    reason="documents service not written yet",
)
async def test_an_incomplete_note_is_stored_as_incompleto(
    db, validator, make_tenant, make_document  # noqa: ANN001
) -> None:
    """The upload goes through; the status carries the bad news."""
    from app.models.documents import DecaStatus

    payload = dict(COMPLETE_PAYLOAD)
    del payload["matricula_vehiculo"]

    mm, site = await make_tenant()
    document = await make_document(mm, site, filename="incompleto.pdf")
    document.deca = payload
    document.deca_status = (
        DecaStatus.COMPLETE if validator.is_complete(payload) else DecaStatus.INCOMPLETE
    )
    await db.flush()

    assert document.deca_status is DecaStatus.INCOMPLETE
    assert document.id is not None

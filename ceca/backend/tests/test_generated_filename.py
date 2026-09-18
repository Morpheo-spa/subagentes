"""A generated DeCA gets a name a person can tell apart in the archive table.

``deca-<uuid>.pdf`` made forty rows look identical. The name is now built from
the transport date and the shipper, reduced to an alphabet that is safe in a
header, on a filesystem and in a URL, and ends in the short id so two notes for
the same shipper on the same day never collide.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

import pytest

from app.deps import TenantContext
from app.models.deca import DecaFieldDefinition
from app.schemas.documents import FILENAME_PATTERN
from app.services import documents as documents_service

CATALOGUE_PATH = Path(__file__).resolve().parents[1] / "app" / "i18n" / "deca_fields.json"
SAFE = re.compile(r"^[A-Za-z0-9._-]+$")
DECA = {
    "cargador_nombre": "Transportes García e Hijos, S.L.",
    "cargador_nif": "B12345674",
    "cargador_domicilio": "Calle Mayor 1",
    "transportista_nombre": "Logística Ñandú",
    "transportista_nif": "A58818501",
    "origen": "Zaragoza",
    "destino": "Bilbao",
    "mercancia_naturaleza": "Palés",
    "mercancia_peso": "1",
    "mercancia_peso_unidad": "t",
    "fecha_transporte": "2026-10-06",
    "matricula_vehiculo": "1234 KLM",
}


@pytest.fixture
async def catalogue(db: Any) -> None:
    payload = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))
    for field in payload["fields"]:
        choices = field.get("choices")
        db.add(
            DecaFieldDefinition(
                code=field["code"],
                label_es=field["label_es"],
                label_en=field["label_en"],
                data_type=field["data_type"],
                is_required=field["is_required"],
                max_length=field.get("max_length"),
                pattern=field.get("pattern"),
                choices=json.dumps(choices, ensure_ascii=False) if choices else None,
                sort_order=field.get("sort_order", 0),
                is_active=True,
                catalog_version=payload["catalog_version"],
            )
        )
    await db.flush()


def test_the_name_reads_date_shipper_and_short_id() -> None:
    document_id = uuid.UUID("135683fb-0000-4000-8000-000000000000")

    name = documents_service.generated_filename(DECA, document_id)

    assert name == "deca-2026-10-06-Transportes-Garcia-e-Hijos-S.L-135683fb.pdf"
    assert re.match(FILENAME_PATTERN, name)


def test_nothing_outside_the_safe_alphabet_survives() -> None:
    hostile = {
        **DECA,
        "cargador_nombre": "../..\\evil/name\r\nX: y\x00 «Ñoño & Cía» 100% ünïcode ☃",
    }

    name = documents_service.generated_filename(hostile, uuid.uuid4())

    assert SAFE.match(name), name
    assert "/" not in name and "\\" not in name
    assert not re.search(r"[\x00-\x1f\x7f]", name)
    assert "Nono-Cia-100-unicode" in name


def test_the_name_never_exceeds_eighty_characters() -> None:
    document_id = uuid.uuid4()
    long = {**DECA, "cargador_nombre": "Compañía " * 60}

    name = documents_service.generated_filename(long, document_id)

    assert len(name) <= documents_service.GENERATED_FILENAME_MAX
    assert name.endswith(f"-{document_id.hex[:8]}.pdf"), "the short id is never cut"
    assert name.startswith("deca-2026-10-06-Compania-")


def test_two_notes_for_the_same_shipper_and_day_get_different_names() -> None:
    first = documents_service.generated_filename(DECA, uuid.uuid4())
    second = documents_service.generated_filename(DECA, uuid.uuid4())

    assert first != second
    assert first[:-13] == second[:-13], "everything but the short id matches"


def test_a_missing_or_unparsable_date_falls_back_without_breaking_the_name() -> None:
    no_date = {**DECA, "fecha_transporte": None}
    bad_date = {**DECA, "fecha_transporte": "el martes"}
    no_shipper = {**DECA, "cargador_nombre": "   ¡¡¡   "}

    for payload in (no_date, bad_date, no_shipper):
        name = documents_service.generated_filename(payload, uuid.uuid4())
        assert SAFE.match(name), name
        assert name.startswith("deca-") and name.endswith(".pdf")


async def test_create_from_deca_archives_the_document_under_the_derived_name(
    db: Any, catalogue: None, make_tenant: Any, make_user: Any, make_storage_backend: Any
) -> None:
    mm, site = await make_tenant()
    actor = await make_user(mm, site, email="gen@estampa-demo.com", role="operator")
    await make_storage_backend(mm, site)
    ctx = TenantContext(
        user_id=actor.id,
        mm_id=mm.id,
        site_id=site.id,
        site_prefix=site.site_prefix,
        permissions=frozenset({"documents:create"}),
    )

    document = await documents_service.create_from_deca(db, ctx, deca=DECA, actor_user_id=actor.id)

    assert document.original_filename == (
        f"deca-2026-10-06-Transportes-Garcia-e-Hijos-S.L-{document.id.hex[:8]}.pdf"
    )
    assert len(document.original_filename) <= 80
    assert re.match(FILENAME_PATTERN, document.original_filename)


async def test_a_filename_the_caller_chose_still_wins(
    db: Any, catalogue: None, make_tenant: Any, make_user: Any, make_storage_backend: Any
) -> None:
    mm, site = await make_tenant()
    actor = await make_user(mm, site, email="gen@estampa-demo.com", role="operator")
    await make_storage_backend(mm, site)
    ctx = TenantContext(
        user_id=actor.id, mm_id=mm.id, site_id=site.id, site_prefix=site.site_prefix
    )

    document = await documents_service.create_from_deca(
        db, ctx, deca=DECA, filename="pedido 4711.pdf", actor_user_id=actor.id
    )

    assert document.original_filename == "pedido 4711.pdf"

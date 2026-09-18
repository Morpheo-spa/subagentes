"""A freshly inserted row must be readable without another round trip.

Timestamps are filled by the database. Unless the mapper fetches them back in
the INSERT's RETURNING, SQLAlchemy marks them expired, and an async session
cannot lazily load an expired attribute from a plain attribute read. The
symptom in production was a 500 on every endpoint that returned a row it had
just created, with the row itself rolled back.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.models.tenancy import MM, Site

CATALOGUE_PATH = Path(__file__).resolve().parents[1] / "app" / "i18n" / "deca_fields.json"
#: Read once at import, synchronously: an async test must not block on disk.
CATALOGUE = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))


async def test_server_defaults_are_loaded_by_the_insert(db: Any) -> None:
    mm = MM(name="Eager", slug=f"eager-{uuid.uuid4().hex[:8]}")
    db.add(mm)
    await db.flush()

    # Would raise MissingGreenlet if the attribute had been expired.
    assert mm.created_at is not None
    assert mm.updated_at is not None


async def test_the_same_holds_for_models_with_optimistic_locking(db: Any) -> None:
    """OptimisticLock overrides the mapper args and must not drop the setting."""
    from app.models.tenancy import User
    from app.security import hash_password

    mm = MM(name="Locked", slug=f"locked-{uuid.uuid4().hex[:8]}")
    db.add(mm)
    await db.flush()
    site = Site(mm_id=mm.id, name="S", site_prefix="S1")
    db.add(site)
    await db.flush()
    user = User(
        mm_id=mm.id,
        email=f"eager-{uuid.uuid4().hex[:6]}@estampa-demo.com",
        full_name="Eager",
        hashed_password=hash_password("x"),
        default_site_id=site.id,
    )
    db.add(user)
    await db.flush()

    assert user.created_at is not None
    assert user.version == 1


async def test_generate_returns_the_row_it_just_created(
    client: Any, make_tenant: Any, make_user: Any, make_storage_backend: Any, db: Any
) -> None:
    """The end-to-end shape of the production failure, through the router."""
    from app.models.deca import DecaFieldDefinition

    catalogue = CATALOGUE
    for field in catalogue["fields"]:
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
                catalog_version=catalogue["catalog_version"],
            )
        )
    mm, site = await make_tenant()
    await make_user(mm, site, email="gen@estampa-demo.com", role="operator")
    await make_storage_backend(mm, site)
    await db.flush()

    login = await client.post(
        "/api/v1/auth/login", json={"email": "gen@estampa-demo.com", "password": "test-password"}
    )
    headers = {"Authorization": f"Bearer {login.json()['tokens']['access_token']}"}
    deca = {
        "cargador_nombre": "A",
        "cargador_nif": "B12345674",
        "cargador_domicilio": "x",
        "transportista_nombre": "B",
        "transportista_nif": "A58818501",
        "origen": "Z",
        "destino": "B",
        "mercancia_naturaleza": "p",
        "mercancia_peso": "1",
        "mercancia_peso_unidad": "t",
        "fecha_transporte": "2026-10-06",
        "matricula_vehiculo": "1234 KLM",
    }

    response = await client.post("/api/v1/documents/generate", headers=headers, json={"deca": deca})

    assert response.status_code in (200, 201), response.text
    body = response.json()
    assert body["created_at"] and body["compliance_status"] == "compliant"

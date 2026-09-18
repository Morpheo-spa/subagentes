"""The catalogue endpoint must serve the rows the migration seeds.

The service-level tests never went through the router, and the router failed
on every row against a migrated database: the choices column is JSON text or
NULL, and the response schema validated the row before anyone converted it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CATALOGUE = BACKEND_ROOT / "app" / "i18n" / "deca_fields.json"


@pytest.fixture
async def seeded_catalogue(db: Any) -> dict[str, Any]:
    """Seed exactly the way alembic 0003 does: choices as JSON text, or NULL."""
    from app.models.deca import DecaFieldDefinition

    payload = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    for field in payload["fields"]:
        choices = field.get("choices")
        db.add(
            DecaFieldDefinition(
                code=field["code"],
                label_es=field["label_es"],
                label_en=field["label_en"],
                help_es=field.get("help_es"),
                help_en=field.get("help_en"),
                data_type=field["data_type"],
                is_required=field["is_required"],
                max_length=field.get("max_length"),
                pattern=field.get("pattern"),
                choices=json.dumps(choices, ensure_ascii=False) if choices else None,
                legal_reference=field.get("legal_reference"),
                sort_order=field.get("sort_order", 0),
                is_active=True,
                catalog_version=payload["catalog_version"],
            )
        )
    await db.flush()
    return payload


async def _sign_in(client: Any, make_tenant: Any, make_user: Any) -> dict[str, str]:
    mm, site = await make_tenant()
    await make_user(mm, site, email="reader@estampa-demo.com", role="viewer")
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": "reader@estampa-demo.com", "password": "test-password"},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['tokens']['access_token']}"}


async def test_the_catalogue_endpoint_serves_every_seeded_row(
    client: Any, seeded_catalogue: dict[str, Any], make_tenant: Any, make_user: Any
) -> None:
    headers = await _sign_in(client, make_tenant, make_user)

    response = await client.get("/api/v1/deca/fields", headers=headers)

    assert response.status_code == 200, response.text
    items = {item["code"]: item for item in response.json()["fields"]}
    assert set(items) == {f["code"] for f in seeded_catalogue["fields"]}


async def test_choices_come_back_as_a_list_whether_stored_or_null(
    client: Any, seeded_catalogue: dict[str, Any], make_tenant: Any, make_user: Any
) -> None:
    headers = await _sign_in(client, make_tenant, make_user)
    items = {
        item["code"]: item
        for item in (await client.get("/api/v1/deca/fields", headers=headers)).json()["fields"]
    }

    assert items["mercancia_peso_unidad"]["choices"] == ["kg", "t"]
    assert items["origen"]["choices"] == []

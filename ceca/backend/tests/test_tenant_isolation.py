"""Tenant isolation, checked twice: statically and over HTTP.

Static: every ``select(Model)`` against a :class:`TenantScoped` model in
``app/services/`` and ``app/routers/`` must go through ``scoped()`` /
``scoped_select()``. A bare select is a cross-tenant read waiting to happen, and
the failure names the file and line.

Functional: asking for another tenant's document answers 404, never 403. A 403
would confirm the document exists.
"""

from __future__ import annotations

import ast
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.models.base import TenantScoped

BACKEND_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = BACKEND_ROOT / "app"
SCANNED_PACKAGES = ("services", "routers")

#: Reading by primary key cannot carry a tenant filter, so it is never allowed
#: on a scoped model.
UNSAFE_GETTERS = {"get"}
#: The sanctioned way out, for the handful of places backend.md allows: the public
#: viewer resolving a share token, and the cross-tenant retention sweep. The reason
#: is mandatory, so every exception stays readable and reviewable.
EXEMPTION_PRAGMA = "# tenant-exempt:"


def _scoped_model_names() -> set[str]:
    from app import models

    return {
        name
        for name in dir(models)
        if isinstance(getattr(models, name), type)
        and issubclass(getattr(models, name), TenantScoped)
    }


SCOPED_MODELS = _scoped_model_names()


@dataclass(frozen=True)
class Offence:
    location: str
    detail: str

    def __str__(self) -> str:
        return f"{self.location}: {self.detail}"


def _python_files() -> Iterator[Path]:
    for package in SCANNED_PACKAGES:
        yield from sorted((APP_ROOT / package).rglob("*.py"))


def _first_arg_name(node: ast.Call) -> str | None:
    if not node.args:
        return None
    first = node.args[0]
    return first.id if isinstance(first, ast.Name) else None


def _callee(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _scoped_select_nodes(tree: ast.AST) -> set[int]:
    """Identity of every ``select(...)`` that is already wrapped by ``scoped()``."""
    wrapped: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _callee(node) == "scoped" and node.args:
            wrapped.add(id(node.args[0]))
    return wrapped


def _exemption_reason(lines: list[str], node: ast.Call) -> str | None:
    """Find the pragma anywhere in the call, or on the line just above it.

    A formatter is free to wrap a call across several lines and carry a trailing
    comment to the closing paren, so anchoring to the first line alone would make
    an exemption silently evaporate the next time anyone runs the formatter.
    """
    first = max(node.lineno - 1, 1)
    last = node.end_lineno or node.lineno
    for line in lines[first - 1 : last]:
        if EXEMPTION_PRAGMA in line:
            return line.split(EXEMPTION_PRAGMA, 1)[1].strip()
    return None


def _offences_in(path: Path) -> list[Offence]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    tree = ast.parse(source, filename=str(path))
    wrapped = _scoped_select_nodes(tree)
    relative = path.relative_to(BACKEND_ROOT)
    offences: list[Offence] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = _callee(node)
        model = _first_arg_name(node)
        if model not in SCOPED_MODELS:
            continue
        location = f"{relative}:{node.lineno}"
        reason = _exemption_reason(lines, node)
        if reason is not None:
            if not reason:
                offences.append(Offence(location, "tenant-exempt pragma without a reason"))
            continue
        if callee == "select" and id(node) not in wrapped:
            offences.append(
                Offence(location, f"bare select({model}); use scoped_select({model}, ctx)")
            )
        elif callee in UNSAFE_GETTERS and not isinstance(node.func, ast.Name):
            offences.append(
                Offence(location, f".get({model}, ...) cannot filter by tenant; use scoped_select")
            )
    return offences


def test_scoped_models_are_discovered() -> None:
    """If this ever empties out, the scan below stops proving anything."""
    assert {"Document", "StorageBackend", "RetentionPolicy"} <= SCOPED_MODELS


def test_no_unscoped_query_against_a_tenant_table() -> None:
    offences = [offence for path in _python_files() for offence in _offences_in(path)]
    assert not offences, "cross-tenant query risk:\n" + "\n".join(str(o) for o in offences)


def test_scoped_helper_rejects_a_global_model() -> None:
    """The helper is the guard rail; it must fail loudly on a model without tenancy."""
    from sqlalchemy import select

    from app.deps import TenantContext, scoped
    from app.models import Plan

    ctx = TenantContext(
        user_id=uuid.uuid4(), mm_id=uuid.uuid4(), site_id=uuid.uuid4(), site_prefix="X"
    )
    with pytest.raises(TypeError):
        scoped(select(Plan), ctx, Plan)


async def test_scoped_select_filters_out_another_tenants_rows(
    db, make_tenant, make_document
) -> None:
    from app.deps import TenantContext, scoped_select
    from app.models import Document

    mm_a, site_a = await make_tenant(slug="tenant-a", prefix="AAA")
    mm_b, site_b = await make_tenant(slug="tenant-b", prefix="BBB")
    await make_document(mm_a, site_a, filename="a.pdf")
    document_b = await make_document(mm_b, site_b, filename="b.pdf")

    ctx_a = TenantContext(
        user_id=uuid.uuid4(), mm_id=mm_a.id, site_id=site_a.id, site_prefix=site_a.site_prefix
    )
    rows = (await db.execute(scoped_select(Document, ctx_a))).scalars().all()

    assert [row.original_filename for row in rows] == ["a.pdf"]
    assert document_b.id not in {row.id for row in rows}


@pytest.mark.skipif(
    not (APP_ROOT / "routers" / "documents.py").exists(),
    reason="documents router not written yet",
)
async def test_reading_another_tenants_document_answers_404(
    client, db, make_tenant, make_user, make_document
) -> None:
    """404, not 403: the API never confirms that someone else's document exists."""
    from app.security import create_token

    mm_a, site_a = await make_tenant(slug="tenant-a", prefix="AAA")
    mm_b, site_b = await make_tenant(slug="tenant-b", prefix="BBB")
    user_a = await make_user(mm_a, site_a, email="a@demo.test", role="mm_admin")
    document_b = await make_document(mm_b, site_b, filename="b.pdf")
    await db.flush()

    from app.models.tenancy import PERMISSIONS

    token = create_token(
        user_id=user_a.id,
        mm_id=mm_a.id,
        site_id=site_a.id,
        site_prefix=site_a.site_prefix,
        permissions=set(PERMISSIONS),
        is_superuser=False,
        locale="es",
    )
    response = await client.get(
        f"/api/v1/documents/{document_b.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert response.json()["detail"]["code"] != "PERMISSION_DENIED"

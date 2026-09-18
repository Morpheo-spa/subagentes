"""The generated DeCA is readable: no label ever runs into its value.

The two-column layout gave every label the same 62 mm, and "Cargador
contractual — nombre o razón social" needed more, so it was drawn straight
through the value beside it. The layout is now label above value, and the
proof here is geometric as well as textual: every string reportlab draws is
collected with its baseline, and no two strings on a page may share one.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pypdf import PdfReader

from app.services import pdf

CATALOGUE_PATH = Path(__file__).resolve().parents[1] / "app" / "i18n" / "deca_fields.json"
FIELDS: list[dict[str, Any]] = json.loads(CATALOGUE_PATH.read_text(encoding="utf-8"))["fields"]

#: Two hundred characters of wrappable prose, with the accents Spanish has.
SENTENCE = "Almacén número {n} de la mercancía, camión y señalización. "


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _values(length: int = 200) -> dict[str, str]:
    return {
        field["code"]: (SENTENCE.format(n=index) * 6)[:length].strip()
        for index, field in enumerate(FIELDS)
    }


def _render(language: str, **extra: Any) -> bytes:
    return pdf.render_deca_pdf(
        _values(),
        qr_url="http://testserver/v/token",
        document_id=uuid4(),
        site_name="Centro Logístico Demo",
        language=language,
        **extra,
    ).data


def _text(data: bytes, language: str = "es") -> str:
    """All pages squashed into one string, footers removed.

    A value may flow across a page break, and the legal note at the foot of
    every page would otherwise sit in the middle of it.
    """
    footer = _squash(pdf._say("legal_note", language))
    pages = (_squash(page.extract_text()) for page in PdfReader(BytesIO(data)).pages)
    return "".join(page.replace(footer, "") for page in pages)


def _runs(data: bytes) -> dict[tuple[int, float], list[tuple[float, str]]]:
    """Every drawn string, keyed by page and baseline, with its x position."""
    runs: dict[tuple[int, float], list[tuple[float, str]]] = defaultdict(list)
    for number, page in enumerate(PdfReader(BytesIO(data)).pages):

        def visit(
            text: str, _cm: Any, tm: Any, _font: Any, _size: Any, number: int = number
        ) -> None:
            if text.strip():
                runs[(number, round(float(tm[5]), 1))].append((float(tm[4]), text))

        page.extract_text(visitor_text=visit)
    return runs


@pytest.mark.parametrize("language", ["es", "en"])
def test_every_catalogue_label_and_every_value_comes_out_whole(language: str) -> None:
    """Long labels included, and 200-character values under them, all complete."""
    flat = _text(_render(language), language)
    label_key = "label_en" if language == "en" else "label_es"

    missing_labels = [f[label_key] for f in FIELDS if _squash(f[label_key]) not in flat]
    missing_values = [code for code, value in _values().items() if _squash(value) not in flat]

    assert missing_labels == [], f"labels cut or overdrawn: {missing_labels}"
    assert missing_values == [], f"values cut or overdrawn: {missing_values}"


@pytest.mark.parametrize("language", ["es", "en"])
def test_no_two_strings_share_a_baseline(language: str) -> None:
    """Geometric: nothing is drawn beside anything else, so nothing can overlap.

    A label that does not fit its column overlaps by landing on the same
    baseline as the value. With label above value, each baseline holds exactly
    one string - the strong form of "no overlap", checked on every page.
    """
    data = _render(language, superseded={"origen": "Valor antiguo " * 10}, change_reason="Error")

    shared = {key: runs for key, runs in _runs(data).items() if len(runs) > 1}

    assert shared == {}, f"strings drawn on the same baseline: {shared}"


def test_the_title_carries_its_accent() -> None:
    flat = _text(_render("es"))

    assert "DocumentoelectrónicodeControlAdministrativo(DeCA)" in flat
    assert "Documentoelectronico" not in flat


def test_helvetica_encodes_what_spanish_needs() -> None:
    """Latin-1 is inside the standard font: no registration needed, no boxes."""
    flat = _text(_render("es", superseded={"destino": "Ávila"}, change_reason="Añadir señas"))

    for expected in ("mercancía", "señalización", "código", "NOVÁLIDO", "Ávila", "Añadirseñas"):
        assert expected in flat, f"{expected!r} did not survive the base font"


def test_superseded_values_are_still_readable_and_marked_not_valid() -> None:
    old = "Antiguo lugar de origen, calle Mayor 1, Ávila. " * 5
    flat = _text(
        _render("es", superseded={"origen": old.strip()}, change_reason="Dirección errónea")
    )

    assert _squash(old) in flat
    assert "Lugardeorigendelenvío—NOVÁLIDO" in flat
    assert "Direcciónerrónea" in flat


def test_a_row_never_straddles_the_footer() -> None:
    """Values flow across pages line by line; nothing lands under the floor."""
    data = _render("es", superseded=_values(1000), change_reason="Todo cambió")

    lowest = min(y for (_page, y) in _runs(data) if y > pdf.MARGIN + 2 * 9)

    assert lowest >= pdf.BODY_FLOOR - pdf.VALUE_LEADING

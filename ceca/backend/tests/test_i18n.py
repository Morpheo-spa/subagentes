"""Every error code raised anywhere in app/ must be translatable.

The check is an AST walk, not a reading of the code: a new ``DomainError`` with no
entry in ``app/i18n/errors.json`` fails the build, and so does a template whose
``{placeholders}`` do not match the params the raising site passes.
"""

from __future__ import annotations

import ast
import json
import string
from dataclasses import dataclass
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

ERROR_CLASSES = {
    "DomainError",
    "NotFoundError",
    "PermissionDeniedError",
    "QuotaExceededError",
    "ConflictError",
}
DEFAULT_CODES = {"PermissionDeniedError": "PERMISSION_DENIED"}
NON_PARAM_KEYWORDS = {"status_code"}
LANGUAGES = ("es", "en")


@dataclass(frozen=True)
class RaiseSite:
    code: str
    params: frozenset[str]
    location: str


def _catalogue() -> dict[str, dict[str, str]]:
    path = APP_ROOT / "i18n" / "errors.json"
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)["byCode"]


def _callee_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _code_of(node: ast.Call, callee: str) -> str | None:
    if node.args:
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
        return None  # Dynamic code: nothing static to check.
    return DEFAULT_CODES.get(callee)


def _collect_raise_sites() -> list[RaiseSite]:
    sites: list[RaiseSite] = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            callee = _callee_name(node)
            if callee not in ERROR_CLASSES:
                continue
            code = _code_of(node, callee)
            if code is None:
                continue
            params = {
                keyword.arg
                for keyword in node.keywords
                if keyword.arg and keyword.arg not in NON_PARAM_KEYWORDS
            }
            sites.append(
                RaiseSite(
                    code=code,
                    params=frozenset(params),
                    location=f"{path.relative_to(APP_ROOT.parent)}:{node.lineno}",
                )
            )
    return sites


def _placeholders(template: str) -> set[str]:
    return {
        name
        for _, name, _, _ in string.Formatter().parse(template)
        if name
    }


RAISE_SITES = _collect_raise_sites()
CATALOGUE = _catalogue()


def test_app_raises_at_least_one_domain_error() -> None:
    """Guards the guard: an empty scan would make every assertion below vacuous."""
    assert RAISE_SITES, "no DomainError raise sites found under app/"


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_catalogue_entry_has_both_languages(language: str) -> None:
    missing = [code for code, entry in CATALOGUE.items() if not entry.get(language)]
    assert not missing, f"errors.json entries missing '{language}': {missing}"


def test_every_raised_code_is_in_the_catalogue() -> None:
    unknown = sorted(
        {f"{site.code} ({site.location})" for site in RAISE_SITES if site.code not in CATALOGUE}
    )
    assert not unknown, "codes raised in app/ with no entry in errors.json: " + ", ".join(unknown)


def test_spanish_and_english_templates_take_the_same_params() -> None:
    mismatched = {
        code: sorted(_placeholders(entry["es"]) ^ _placeholders(entry["en"]))
        for code, entry in CATALOGUE.items()
        if _placeholders(entry["es"]) != _placeholders(entry["en"])
    }
    assert not mismatched, f"ES and EN templates disagree on params: {mismatched}"


def test_templates_only_use_params_the_raising_code_supplies() -> None:
    problems: list[str] = []
    for site in RAISE_SITES:
        entry = CATALOGUE.get(site.code)
        if entry is None:
            continue
        for language in LANGUAGES:
            missing = _placeholders(entry[language]) - site.params
            if missing:
                problems.append(
                    f"{site.location} raises {site.code} without {sorted(missing)} "
                    f"required by the {language} template"
                )
    assert not problems, "\n".join(problems)


def test_raised_params_are_used_by_the_template() -> None:
    """An unused param is a message that silently drops information."""
    problems: list[str] = []
    for site in RAISE_SITES:
        entry = CATALOGUE.get(site.code)
        if entry is None or not site.params:
            continue
        unused = site.params - _placeholders(entry["es"]) - _placeholders(entry["en"])
        if unused:
            problems.append(
                f"{site.location} passes {sorted(unused)} to {site.code}, "
                "which no template interpolates"
            )
    assert not problems, "\n".join(problems)


def test_catalogue_file_parses() -> None:
    """A malformed JSON catalogue must fail here, not at the first user error."""
    path: Path = APP_ROOT / "i18n" / "errors.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "byCode" in payload
    assert all(isinstance(entry, dict) for entry in payload["byCode"].values())

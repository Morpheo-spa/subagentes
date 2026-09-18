"""Guards against source files that exist on disk but never reach the repository.

A stray ``storage/`` line in .gitignore once swallowed the whole storage adapter
package: every check passed locally, every test was green, and a clean clone
could not start the backend. Nothing in a normal test suite notices that, because
the files are right there on the developer's disk.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parents[1]

IGNORED_DIRECTORIES = {
    "__pycache__",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
    "dist",
}


def _git_available() -> bool:
    try:
        subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=REPO_ROOT,
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return True


def _shipped_sources() -> list[Path]:
    return [
        path
        for path in (BACKEND_ROOT / "app").rglob("*.py")
        if not IGNORED_DIRECTORIES.intersection(path.parts)
    ]


@pytest.mark.skipif(not _git_available(), reason="not a git checkout")
def test_every_backend_source_file_is_tracked() -> None:
    sources = _shipped_sources()
    assert sources, "found no backend sources; the glob above is wrong"

    result = subprocess.run(
        ["git", "check-ignore", "--no-index", *[str(p) for p in sources]],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    ignored = [line for line in result.stdout.splitlines() if line.strip()]
    assert not ignored, (
        "these backend sources are excluded by .gitignore, so a clean clone "
        "would not contain them:\n" + "\n".join(ignored)
    )

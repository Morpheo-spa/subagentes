#!/usr/bin/env bash
# The local gate. CI runs exactly this script, nothing more.
# Files under ceca/ are excluded from the parent repository's pre-commit hooks.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

BOLD=$'\033[1m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; OFF=$'\033[0m'

FAILED=()
SKIPPED=()

step() {
  local name="$1"; shift
  printf '%s==> %s%s\n' "$BOLD" "$name" "$OFF"
  if "$@"; then
    printf '%s    PASS%s  %s\n' "$GREEN" "$OFF" "$name"
  else
    printf '%s    FAIL%s  %s\n' "$RED" "$OFF" "$name"
    FAILED+=("$name")
  fi
}

skip() {
  printf '%s    SKIP%s  %s (%s)\n' "$YELLOW" "$OFF" "$1" "$2"
  SKIPPED+=("$1")
}

python_bin() {
  if [[ -x "$BACKEND/.venv/bin/python" ]]; then
    echo "$BACKEND/.venv/bin/python"
  else
    echo "${PYTHON:-python3}"
  fi
}

PY="$(python_bin)"
run_py() { (cd "$BACKEND" && "$PY" -m "$@"); }

has_module() { "$PY" -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('$1') else 1)" 2>/dev/null; }

# --- Backend -----------------------------------------------------------------
printf '%sBackend%s (%s)\n' "$BOLD" "$OFF" "$PY"

if has_module ruff; then
  step "ruff check" run_py ruff check .
  step "ruff format --check" run_py ruff format --check .
else
  skip "ruff" "not installed"
fi

if has_module mypy; then
  step "mypy" run_py mypy app --ignore-missing-imports
else
  skip "mypy" "not installed"
fi

if has_module bandit; then
  step "bandit" run_py bandit -q -c pyproject.toml -r app
else
  skip "bandit" "not installed"
fi

if has_module pytest; then
  step "pytest" run_py pytest
else
  skip "pytest" "not installed"
fi

# --- Environment template ----------------------------------------------------
# The template must be rejected: it is a local file full of placeholders. A green
# result here would mean the validator has stopped validating.
rejects_template() {
  ! "$PY" "$ROOT/scripts/check_env.py" "$ROOT/.env.example" >/dev/null 2>&1
}
step "check_env rejects .env.example" rejects_template

# --- Frontend ----------------------------------------------------------------
printf '\n%sFrontend%s\n' "$BOLD" "$OFF"
if [[ -d "$FRONTEND/node_modules" ]]; then
  run_npm() { (cd "$FRONTEND" && npm run --silent "$1"); }
  step "npm run typecheck" run_npm typecheck
  step "npm run lint" run_npm lint
  step "vitest" bash -c "cd '$FRONTEND' && npx --no-install vitest run"
else
  skip "frontend" "node_modules missing, run npm ci in frontend/"
fi

# --- Summary -----------------------------------------------------------------
printf '\n%sSummary%s\n' "$BOLD" "$OFF"
if ((${#SKIPPED[@]})); then
  printf '  skipped: %s\n' "${SKIPPED[*]}"
fi
if ((${#FAILED[@]})); then
  printf '%s  FAILED: %s%s\n' "$RED" "${FAILED[*]}" "$OFF"
  exit 1
fi
printf '%s  all checks passed%s\n' "$GREEN" "$OFF"

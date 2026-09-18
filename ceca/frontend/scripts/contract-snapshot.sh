#!/usr/bin/env sh
# Vuelca el OpenAPI real del backend a src/lib/openapi.snapshot.json.
#
# `contract.test.ts` contrasta routes.ts y types.ts contra ese fichero, asi que
# hay que regenerarlo cada vez que cambie el backend (README.md).
#
# `app.main` necesita configuracion para importarse: pydantic-settings lee
# backend/.env solo; si no existe, exporta DATABASE_URL, REDIS_URL,
# JWT_SECRET_KEY, STORAGE_SECRET_KEY y ACCESS_LOG_IP_SALT con valores de relleno
# de la longitud minima.
set -eu

FRONTEND_DIR=$(cd "$(dirname "$0")/.." && pwd)
BACKEND_DIR=${BACKEND_DIR:-"$FRONTEND_DIR/../backend"}
PYTHON=${PYTHON:-"$BACKEND_DIR/.venv/bin/python"}
OUT="$FRONTEND_DIR/src/lib/openapi.snapshot.json"

cd "$BACKEND_DIR"
"$PYTHON" -c "import json; from app.main import app; print(json.dumps(app.openapi()))" > "$OUT"
echo "OpenAPI volcado en $OUT"

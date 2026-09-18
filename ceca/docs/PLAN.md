# Plan de construcción

Estado real a **18 de septiembre de 2026**. Aquí no se marca nada como hecho hasta que el gate
(`bash scripts/ci.sh`) lo respalda.

Leyenda: **Hecho** · **En curso** · **Pendiente**

---

## Fase 0 — Cimientos

| Entregable | Estado | Nota |
|------------|--------|------|
| `CLAUDE.md` y `.claude/rules/*.md` | Hecho | Reglas por área |
| `docs/DECA.md` | Hecho | Con niveles de confianza y fuentes pendientes de contrastar |
| `design-system/estampa/` | Hecho | MASTER + páginas |
| Modelos SQLAlchemy 2.x | Hecho | 17 tablas, mixins `TenantScoped` / `OptimisticLock` |
| `config.py`, `db.py`, `errors.py`, `deps.py`, `security.py` | Hecho | |
| Catálogo de errores ES/EN | Hecho | Verificado por `tests/test_i18n.py` |

## Fase 1 — Infraestructura y esquema

| Entregable | Estado | Nota |
|------------|--------|------|
| `backend/pyproject.toml` (ruff, mypy estricto, bandit, pytest) | Hecho | |
| Alembic async (`env.py`, `script.py.mako`) | Hecho | URL desde `app.config`, metadatos desde `app.models` |
| `0001_initial.py` | Hecho | Escrita a mano; verificada columna a columna contra los modelos |
| `0002_seed_plans.py` | Hecho | free / pro / business, idempotente |
| `0003_seed_deca_fields.py` | Hecho | Lee `app/i18n/deca_fields.json`, no lo duplica |
| `docker-compose.yml` + override de desarrollo | Hecho | traefik, postgres, redis, minio, api, worker, frontend |
| Traefik estático + dinámico | Hecho | Cabeceras de seguridad, `noindex` en `/v/`, rate limit en login y visor |
| `.env.example` + `scripts/check_env.py` | Hecho | Validado: acepta un entorno correcto y rechaza la plantilla |
| `scripts/ci.sh` | Hecho | Gate local y de CI |
| `scripts/seed_demo.py` | Hecho | Idempotente; **sin ejecutar contra una BD real todavía** |
| `.github/workflows/ceca-ci.yml` | Hecho | Se dispara solo con cambios en `ceca/**` |

## Fase 2 — Dominio

| Entregable | Estado | Nota |
|------------|--------|------|
| `services/deca.py` (validación NIF/CIF/NIE y catálogo) | Hecho | Cubierto por `tests/test_deca_validation.py` |
| `services/documents.py`, `pdf.py`, `qr.py`, `quota.py` | En curso | Ver "Deuda conocida" |
| `services/storage/` (local, s3, ftp, unavailable) | En curso | |
| `services/retention.py`, `printing.py`, `billing.py`, `audit.py` | En curso | |
| `tasks/` (broker, documents, retention) | En curso | |

## Fase 3 — API

| Entregable | Estado | Nota |
|------------|--------|------|
| `schemas/` | En curso | |
| `routers/` (auth, sites, users, documents, deca, printing, storage, retention, billing, public) | En curso | El visor público tiene un fallo abierto, más abajo |

## Fase 4 — Frontend

| Entregable | Estado | Nota |
|------------|--------|------|
| Shell, router, cliente de API, i18n | En curso | |
| `features/` (documents, upload, printing, deca, billing, admin, public) | En curso | `npm run typecheck` y `npm run lint` en rojo |
| Tests de Vitest | Pendiente | Vitest no encuentra todavía ningún `*.test.tsx` |

## Fase 5 — Operación

| Entregable | Estado | Nota |
|------------|--------|------|
| `docs/RUNBOOK.md` | Hecho | Copias, restauración, rotación de clave, retención, Stripe |
| Despliegue en staging con TLS real | Pendiente | Traefik tiene el resolutor ACME comentado |
| Barrido de retención programado | Pendiente | El actor existe; falta el planificador |
| Copia de seguridad automatizada y probada | Pendiente | El procedimiento está escrito; falta automatizarlo |

---

## Deuda conocida (estado del gate)

Medido con `bash scripts/ci.sh`. Backend sobre SQLite, sin Postgres levantado.

| Comprobación | Resultado | Quién lo cierra |
|--------------|-----------|-----------------|
| `pytest` | 47 pasan, 3 fallan | Ver los tres puntos siguientes |
| `tests/test_public_viewer.py` (2 fallos) | `routers/public.py::_resolve` espera un objeto con `.document`, pero `documents_service.resolve_share_token` devuelve una tupla `(document, share)`. El visor responde 500 con un token válido | API |
| `tests/test_tenant_isolation.py` (1 fallo) | Seis consultas sin ámbito: `db.get(StorageBackend, ...)` ×4, `db.get(Document, ...)` y un `select(Document)` pelado en el barrido de retención. Cada una se arregla con `scoped_select` o se marca con `# tenant-exempt: <motivo>` si es una de las excepciones legítimas | Dominio |
| `ruff check` | 37 avisos, todos en `app/` | Dominio / API |
| `ruff format --check` | 28 ficheros sin formatear, todos en `app/` | Dominio / API |
| `mypy --strict` | 129 errores en 29 ficheros de `app/` | Dominio / API |
| `bandit` | 3 avisos de severidad baja, falsos positivos: B105/B106 sobre los literales `"access"` y `"refresh"` de `token_type` en `security.py` y `routers/auth.py`. Se cierran con `# nosec B105` en la línea | API |
| Frontend `typecheck` / `lint` / `vitest` | En rojo | Frontend |

Ninguna de esas comprobaciones se ha relajado para ponerla en verde: el gate dice la verdad.

## Siguiente paso

1. Cerrar los tres fallos de `pytest` (visor público y ámbito de tenant). Son los que tocan
   seguridad y corrección, no estilo.
2. `ruff format` + `ruff check --fix` sobre `app/`, y bajar los 129 errores de mypy.
3. Primeros tests de Vitest en el frontend.
4. Levantar el stack completo con Docker y ejecutar `make migrate` + `make seed` de verdad:
   las migraciones están verificadas en modo offline (`alembic upgrade head --sql`), todavía no
   contra un Postgres vivo.

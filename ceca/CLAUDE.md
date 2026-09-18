# CLAUDE.md — Estampa (registro DECA de albaranes)

Guía para Claude Code en `ceca/`. Deliberadamente corto: solo lo transversal.
El detalle por área vive en `.claude/rules/*.md` y el diseño de UI en
`design-system/estampa/MASTER.md`.

---

## 1. Qué es Estampa

SaaS multi-tenant para el **DeCA**: el Documento electrónico de Control Administrativo del
transporte de mercancías por carretera, obligatorio en formato electrónico para el transporte
interior desde el **5 de octubre de 2026**. Un albarán puede hacer de DeCA si lleva los datos
del art. 6 de la Orden FOM/2861/2012.

La app genera el PDF desde los datos (o acepta uno nativo del ERP del cliente), lo archiva con
nombre GUID en el storage del tenant, le embebe un QR con una URL única, e imprime etiquetas
(una a una o en cuadrante). Quien escanea el QR ve el PDF sin login. Todo queda registrado y
sujeto a una política de retención.

**Lo que condiciona todo el producto:** el PDF debe ser **nativo, generado desde datos
estructurados**. Una foto o un escaneo **no son un DeCA válido**, por mucho QR que se le
ponga. Ver `docs/DECA.md`, y el aviso sobre el nivel de verificación de esa información.

Modelo de datos **tenant-per-site bajo empresa-per-MM**, igual que Meerkat:

```text
MM (Empresa)      ->  aislamiento por mm_id en toda tabla con ámbito
  |__ Site         ->  aislamiento por site_id (tenant_id); site_prefix numera los albaranes
        |__ User   ->  puede pertenecer a varios sites; tiene default_site_id
```

El JWT lleva `mm_id`, `tenant_id` (site), `site_prefix`, `permissions`, `is_superuser`.
El contexto de site se fija al login (site por defecto) o vía `POST /api/v1/auth/switch-site`.

Monolito modular FastAPI (no microservicios) + SPA React/Vite, Postgres, Redis + Dramatiq,
Traefik, Docker Compose. El porqué está en `docs/DECISIONES.md` (ADR-001).

---

## 2. Comandos

```bash
# Stack local completo
docker compose up --build

# Migraciones
docker compose exec api alembic upgrade head
docker compose exec api alembic revision --autogenerate -m "mensaje"

# Tests
cd backend && pytest -v
cd frontend && npm run lint && npm run typecheck && npx vitest run

# Gate local de CI (lo mismo que ejecuta CI)
bash scripts/ci.sh

# Validación de entorno de producción - obligatoria antes de desplegar
python scripts/check_env.py .env.production
```

---

## 3. Reglas duras transversales

**Git y ramas**

- `main` = producción. Se trabaja en `dev` o `feat/...`.
- Merge a `main` solo con CI verde **y** confirmación explícita del usuario.
- Antes de commitear, mira `git status --short` verbatim y commitea solo tus ficheros.
- Nunca `Co-Authored-By: Claude` en el mensaje de commit.

**Prohibiciones (nunca, sin excepción)**

1. Dependencias vetadas: `axios`, `moment.js`, `lodash`, `Redux`, componentes React de clase,
   patrones SQLAlchemy 1.x, `requests` dentro de FastAPI async (usa `httpx`).
2. Cambiar el stack (tabla en `.claude/rules/arquitectura.md`) sin aprobación explícita.
3. Confiar en el `mm_id` / `site_id` del body de la petición: se leen siempre de `current_user`.
4. Query contra tabla con ámbito de tenant sin `mm_id` **y** `site_id` en el `where`.
5. Seguridad solo en el frontend: el backend siempre valida con `require_permission`.
6. Guardar tokens en `localStorage` / `sessionStorage` / `window.*` - solo en memoria.
7. Meter el JWT del usuario en un payload de job en background o en el broker.
8. `raise HTTPException(detail="string")` - siempre `detail={"code", "message"}`. En servicios,
   nunca `raise ValueError("prosa")`: `raise DomainError("CODIGO", **params)` (`app/errors.py`)
   y en el router `detail=error_detail(exc)`. Cada `CODIGO` nuevo lleva su entrada ES/EN en
   `app/i18n/errors.json` con los `{params}` interpolados.
9. Devolver al público la URL firmada del storage: el PDF se sirve **siempre** por streaming
   desde la API. El storage nunca se expone.
10. Hardcodear catálogos de dominio (campos DECA, estados, tipos de storage, planes): vienen
    de la API.
11. Imprimir directamente sin registrar el `PrintJob` antes. Toda copia queda trazada.
12. Borrar un `Document` de la base de datos por retención. Se retira el fichero y se conserva
    el registro (`withdrawn_at` + motivo). El registro legal sobrevive al PDF.
13. Presentar un escaneo como DeCA válido. Sin capa de texto -> `origin=UPLOADED_SCANNED`,
    `compliance_status=NOT_A_DECA`, y la UI lo dice con todas las letras.
14. Editar un DeCA en sitio. Modificar es **crear una revisión nueva** con `change_reason`
    obligatorio; la anterior se conserva marcada como sustituida. Ver `docs/DECA.md` §5.

**Seguridad del visor público**

- El token del QR (`share_tokens.token`) **no** es el GUID del documento. Es un secreto
  independiente, revocable, y no se deriva del GUID.
- `/v/{token}` no revela si un token no existe o fue revocado: misma respuesta para ambos.
- Cabeceras obligatorias: `X-Robots-Tag: noindex`, `Cache-Control: no-store`.

---

## 4. Índice de reglas por área

| Fichero | Se carga al tocar | Contenido |
|---------|-------------------|-----------|
| `.claude/rules/arquitectura.md` | `backend/`, `frontend/`, `docker-compose.yml` | Stack cerrado, puertos, layout, límites de módulo |
| `.claude/rules/backend.md` | `backend/` | Contrato de endpoints, errores, aislamiento de tenant, permisos, storage, jobs |
| `.claude/rules/db-migrations.md` | `backend/app/models/`, `backend/alembic/` | Patrones de BD, mixins, bloqueo optimista, pitfalls de Alembic |
| `.claude/rules/frontend.md` | `frontend/` | Comandos, tokens, componentes, reglas de UX |
| `.claude/rules/deca.md` | `app/services/deca.py`, `app/models/deca.py` | Campos obligatorios del albarán, validación, retención legal |
| `.claude/rules/i18n.md` | `app/i18n/`, `frontend/src/locales/` | ES/EN de entrada, catálogo de errores, qué no se traduce |

Otros documentos:

- `docs/DECA.md` - qué exige la norma, de dónde sale cada campo y **qué no se ha podido
  verificar literalmente**. Léelo antes de tocar nada de cumplimiento.
- `docs/DECISIONES.md` - ADRs. No revertir una decisión Aceptada sin sustituirla por otro ADR.
- `docs/PLAN.md` - fases de construcción y estado.
- `design-system/estampa/MASTER.md` - fuente de verdad de UI. `pages/*.md` la sobreescriben.

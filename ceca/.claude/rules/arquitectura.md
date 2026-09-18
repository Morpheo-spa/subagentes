---
paths: ["backend/**", "frontend/**", "docker-compose.yml", "scripts/**"]
---

# Arquitectura

## Stack cerrado

Cambiarlo requiere aprobación explícita del usuario y un ADR nuevo en `docs/DECISIONES.md`.

| Capa | Elección | Versión | Nota |
|------|----------|---------|------|
| API | FastAPI (async) | 0.115+ | Monolito modular, un solo proceso |
| ORM | SQLAlchemy | 2.x async + asyncpg | Nunca patrones 1.x (`query()`, `Column` suelto) |
| Migraciones | Alembic | 1.13+ | Una cabeza. Sin ramas paralelas |
| BD | PostgreSQL | 16 | Un solo esquema. Aislamiento por fila |
| Cache / broker | Redis | 7 | Blacklist de JWT + broker Dramatiq |
| Jobs | Dramatiq | 1.17+ | Subida, QR, retención, limpieza |
| HTTP cliente | httpx | - | `requests` prohibido |
| Validación | Pydantic | 2.x | pydantic-settings para config |
| Front | React + Vite + TypeScript | 19 / 6 | Sin componentes de clase |
| Estilos | Tailwind + shadcn/ui | 4 / cli 4 | Tokens en `src/styles/tokens.css` |
| Tablas | TanStack Table | 8 | Server-side sort/filter/paginate |
| Formularios | TanStack Form | 1.x | Label visible siempre |
| Iconos | Phosphor | - | Sin emojis como iconos |
| PDF (visor) | pdf.js | - | Fallback a descarga |
| QR | segno (py) | - | PNG + SVG |
| Pagos | Stripe | - | Desactivable con `BILLING_ENABLED` |
| Proxy | Traefik | 3 | TLS y routing |

## Puertos

| Servicio | Interno | Expuesto en local |
|----------|---------|-------------------|
| traefik | 80/443 | 8080 (dashboard), 80 |
| api | 8000 | via traefik `/api` |
| frontend (dev) | 5173 | via traefik `/` |
| postgres | 5432 | 5433 |
| redis | 6379 | 6380 |
| worker | - | - |
| minio (Garage/S3 local) | 9000/9001 | 9000/9001 |

## Layout

```text
ceca/
  backend/
    app/
      main.py          # composición de la app, middlewares, routers
      config.py        # settings, una sola fuente de env
      db.py            # engine, sesión, base declarativa
      errors.py        # DomainError + error_detail + catálogo de códigos
      deps.py          # get_db, current_user, require_permission, TenantContext
      security.py      # JWT, hashing, tokens públicos
      models/          # SQLAlchemy. Un fichero por agregado
      schemas/         # Pydantic in/out. Nunca exponer el modelo ORM
      routers/         # HTTP. Sin lógica de negocio
      services/        # Lógica de negocio. Sin objetos Request/Response
        storage/       # Adaptadores: local, s3, ftp. Registro por tipo
      tasks/           # Actores Dramatiq
      i18n/errors.json # Textos ES/EN por código de error
    alembic/
    tests/
  frontend/src/
    app/               # router, providers, shell
    features/<area>/   # documents, upload, printing, billing, admin, public
    components/ui/     # shadcn generado
    lib/               # api client, auth, i18n, utils
    styles/tokens.css  # tokens del design system
  docs/
  design-system/estampa/
  scripts/
```

## Límites de módulo

- `routers/` llama a `services/`. Nunca al revés.
- `services/` no importa `fastapi`. Recibe y devuelve tipos de dominio o Pydantic.
- `models/` no importa `services/`.
- Un servicio no lee el `Request`. Si necesita la IP, se la pasa el router.
- El adaptador de storage no sabe qué es un `Document`. Recibe bytes y una clave.

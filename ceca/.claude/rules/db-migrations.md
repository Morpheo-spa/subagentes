---
paths: ["backend/app/models/**", "backend/alembic/**"]
---

# Base de datos y migraciones

## Mixins (`app/models/base.py`)

- `TimestampMixin` - `created_at`, `updated_at` con `server_default=func.now()`.
- `TenantScoped` - `mm_id`, `site_id` + índice compuesto. Heredarlo marca la tabla como
  filtrable por `scoped()`. Si una tabla tiene ámbito y no lo hereda, es un bug.
- `OptimisticLock` - columna `version`, `__mapper_args__ = {"version_id_col": version}`.

## Patrones

- SQLAlchemy 2.x: `Mapped[...]` + `mapped_column(...)`. Nunca `Column()` suelto ni `.query()`.
- Claves primarias `UUID` (`uuid4`) salvo catálogos, que usan un `code` corto legible.
- Enums de dominio como `str, Enum` en Python y `sa.Enum(..., native_enum=False)` en la BD:
  añadir un valor no requiere migración de tipo.
- Dinero en enteros de céntimos. Nunca `float`.
- Fechas siempre `timezone=True`, guardadas en UTC.
- Índice explícito en toda FK y en `(mm_id, site_id, created_at)` de las tablas que se listan.

## Alembic

- Una sola cabeza. Antes de generar: `alembic heads` y, si hay dos, se fusiona a mano.
- `--autogenerate` no detecta renombrados ni cambios de tipo de enum no nativo: revisa el
  fichero generado siempre, línea a línea.
- Toda migración tiene `downgrade()` real. Si no se puede deshacer, se documenta por qué.
- Los datos semilla (planes, permisos, definiciones DECA) van en migraciones de datos
  separadas, idempotentes (`ON CONFLICT DO NOTHING`).

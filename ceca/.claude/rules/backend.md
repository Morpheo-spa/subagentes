---
paths: ["backend/**"]
---

# Backend

## Aislamiento de tenant (lo más importante)

Toda tabla con ámbito lleva `mm_id` **y** `site_id`. Toda consulta contra ellas filtra por
ambos, tomados de `current_user`, nunca del body ni de la query string.

```python
# BIEN
stmt = select(Document).where(
    Document.mm_id == ctx.mm_id,
    Document.site_id == ctx.site_id,
    Document.id == document_id,
)

# MAL - fuga entre tenants
stmt = select(Document).where(Document.id == document_id)
```

Usa el helper `scoped(select(Document), ctx)` de `app/deps.py`: aplica los dos filtros y falla
en tiempo de import si el modelo no es `TenantScoped`. Si escribes un `select()` a mano contra
una tabla con ámbito, el test `tests/test_tenant_isolation.py` te lo va a cazar.

Excepciones legítimas, y solo estas: `users` por email en el login, `share_tokens` por token en
el visor público, y los catálogos globales (`plans`, `deca_field_definitions`).

## Permisos

`require_permission("documents:create")` en el router, siempre, aunque el frontend ya lo oculte.
Formato `<recurso>:<accion>`. Catálogo en `app/models/tenancy.py::PERMISSIONS`.
`is_superuser` salta la comprobación pero **no** el filtro de tenant.

## Errores

```python
# servicio
raise DomainError("DOCUMENT_NOT_PDF", filename=name)

# router
except DomainError as exc:
    raise HTTPException(status_code=exc.status_code, detail=error_detail(exc))
```

El handler global de `main.py` ya hace esa conversión: en el router normalmente no hace falta
capturar nada. Cada código nuevo va en `app/i18n/errors.json` con texto ES y EN y los mismos
`{params}` que pasa el servicio. Sin entrada en el JSON, el test de i18n falla.

## Endpoints

- Prefijo `/api/v1`. POST **con** barra final en rutas de colección (`POST /documents/`).
- Paginación siempre `{items, total, page, page_size}`. Nunca una lista pelada.
- El body nunca trae `mm_id`, `site_id` ni `owner_id`. Si llega, se ignora.
- 401 sin token o token inválido. 403 autenticado sin permiso. 404 si existe pero es de otro
  tenant (nunca 403: no confirmamos que el objeto exista).

## Storage

- Un adaptador por tipo en `app/services/storage/`, registrado en `REGISTRY`.
- Interfaz: `put(key, data, content_type)`, `get_stream(key)`, `delete(key)`, `health()`.
- El adaptador no conoce `Document`. Recibe una clave y bytes.
- Las credenciales del backend se cifran con `STORAGE_SECRET_KEY` (Fernet) antes de guardarse
  en `storage_backends.config_encrypted`. Nunca se devuelven por la API, ni enmascaradas.
- Un adaptador no implementado lanza `DomainError("STORAGE_KIND_UNAVAILABLE")`. No se simula.

## Jobs (Dramatiq)

- El payload lleva IDs y `mm_id`/`site_id`, **nunca** el JWT ni credenciales.
- Todo actor es idempotente: repetir la misma tarea no duplica documentos ni impresiones.
- Actores en `app/tasks/`. La lógica vive en `services/`; el actor solo orquesta.

## Ficheros subidos

- Solo `application/pdf`, verificado por cabecera mágica `%PDF-`, no por la extensión ni por el
  `content-type` que manda el navegador.
- Límite de tamaño de `settings.max_upload_mb`, comprobado durante el streaming, no después.
- `sha256` de cada fichero. Duplicado dentro del mismo site = aviso, no error: el usuario decide.
- El nombre en el storage es el GUID (`documents.id`). El nombre original solo vive en la BD.

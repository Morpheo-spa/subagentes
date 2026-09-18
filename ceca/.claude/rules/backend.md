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

## Ámbito de administración (`users:manage`)

Tener `users:manage` **no** es poder administrar a toda la empresa. El alcance real lo
resuelve `AdminScope` (`app/deps.py`), construido con las membresías vivas del actor —nunca
con los claims del JWT, que pueden ir por detrás de la realidad:

| Actor | Sites que administra | Permisos que puede conceder |
|-------|----------------------|------------------------------|
| `mm_admin` (o `is_superuser`) | todos los de su MM | todos |
| cualquier otro con `users:manage` | solo aquellos donde es miembro | solo los que él tiene **en ese site** |

Tres reglas, y las tres se comprueban en `routers/users.py`, no en el esquema:

1. **Nadie edita su propio rol ni sus propios permisos.** `PATCH /users/{propio_id}` con
   `memberships` es `SELF_ROLE_CHANGE_FORBIDDEN` (403) incluso para `mm_admin` y para un
   superusuario. Sin esta regla, `users:manage` es una escalada de un solo POST.
2. **Un site fuera del ámbito es de otro inquilino**: `SITE_NOT_FOUND` (404), nunca 403, igual
   que cualquier otro objeto ajeno. Un usuario que no comparte site con el actor tampoco existe
   para él (`USER_NOT_FOUND`), ni en el detalle ni en el listado.
3. **Ninguna concesión supera al que la concede**: `ROLE_PERMISSIONS[rol] | extra_permissions`
   tiene que ser subconjunto de lo que el actor tiene en ese mismo site, o
   `ROLE_ESCALATION_FORBIDDEN` / `PERMISSION_ESCALATION_FORBIDDEN` (403).

Al sustituir membresías solo se toca lo que el actor administra: las de otros sites se
conservan intactas, para que un `site_admin` no pueda dejar a un compañero fuera de una
delegación ajena omitiéndola de la lista.

## Revalidación de sesión

Los permisos viajan dentro del access token, así que cambiarlos en la base de datos no basta.
`app/cache.py` guarda una **marca de invalidación por usuario** (`jwt:epoch:{user_id}`) que se
escribe al desactivar una cuenta, al cambiar rol o permisos, al tocar membresías y al cambiar
la contraseña; `get_current_context` la contrasta contra el `iat` del token y responde
`SESSION_STALE` (401). Es una lectura de Redis por petición, la misma forma que la blacklist —
y, como ella, **falla cerrada**: si Redis no contesta, la petición se deniega.

El token de refresco **no** se contrasta contra la marca: `/auth/refresh` reconstruye los
claims desde la base de datos, y es así como una sesión legítima recoge sus permisos nuevos en
lugar de quedarse fuera. Por eso `iat` lleva fracción de segundo (`app/security.py`): con
segundos enteros no se distingue el token emitido justo antes del cambio del emitido justo
después, y el refresco honrado se rechazaría también.

Quien añada una escritura que cambie privilegios (nuevas rutas de membresías, desactivación
masiva, un job de RRHH) tiene que llamar a `invalidate_user_sessions(user_id)`. Si no, el
cambio no surte efecto hasta 30 minutos después.

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

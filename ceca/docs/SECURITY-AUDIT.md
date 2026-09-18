# Auditoría de seguridad — backend Estampa

**Alcance:** `backend/app/**`, `docker-compose.yml`, `docker-compose.override.yml`, `infra/traefik/**`, `scripts/**`, `.env.example`.
**Método:** lectura de código. Se ha usado el intérprete de `backend/.venv` para comprobar tres hipótesis concretas (entropía del token, validación de cabeceras de uvicorn, regex de `HEADER_VALUE_RE`). **No se ha ejecutado la aplicación ni se ha atacado ningún despliegue.**
**Nada ha sido modificado.**

Cada hallazgo indica si está **[VERIFICADO]** leyendo el código o **[SOSPECHA]** cuando depende de una condición del entorno que no he podido observar.

---

## Resumen ejecutivo

El aislamiento entre empresas está **bien resuelto**: el helper `scoped()`, el test AST que lo vigila y las dos exenciones `# tenant-exempt` son correctos, y `is_superuser` **no** salta el filtro de tenant. No hay inyección SQL. El visor público tiene 192 bits de entropía en el token y respuesta uniforme. Esa parte del diseño aguanta.

El riesgo real está en otro sitio: **la configuración de storage que el propio inquilino escribe no se valida en absoluto**, y de ahí sale una SSRF que puede terminar en robo de las credenciales de nube del host. Es lo primero que hay que arreglar. Después vienen una escalada de privilegios intra-empresa, varios vectores de agotamiento de recursos en el event loop, y una infraestructura de despliegue que hoy no es apta para producción (dashboard de Traefik abierto, Redis sin contraseña, sin TLS).

**Bloqueantes antes de producción:** E-01, E-02, E-03, E-04, E-05, E-06.

| # | Severidad | Área | Título |
|---|-----------|------|--------|
| E-01 | Crítica | Storage | SSRF y robo de credenciales de nube vía `endpoint_url` del backend S3 |
| E-02 | Alta | Storage | `base_path` del backend local es escritura arbitraria en el contenedor |
| E-03 | Alta | AuthZ | Escalada de privilegios: `users:manage` se auto-asciende y se auto-asigna a todos los sites |
| E-04 | Alta | DoS | `deca` sin límite → generación de PDF ilimitada en el event loop |
| E-05 | Alta | DoS | Parseo de PDF subido bloquea el event loop (PDF bomb) |
| E-06 | Alta | Infra | Dashboard de Traefik abierto, Redis sin auth, puertos publicados, sin TLS |
| E-07 | Media | Visor | El PDF público se sirve tal cual: sin limpieza de metadatos, sin CSP, sin `nosniff` propio |
| E-08 | Media | Auth | Login se rompe (500) si dos empresas comparten un email |
| E-09 | Media | HTTP | CRLF en `Content-Disposition` deja el documento permanentemente inservible |
| E-10 | Media | Auditoría | `X-Forwarded-For` falsificable → `ip_hash` del registro legal no es fiable |
| E-11 | Media | Visor | `HEAD /v/{token}` valida tokens sin dejar rastro |
| E-12 | Media | Sesión | Los claims del access token no se revalidan durante 30 minutos |
| E-13 | Media | DoS | `export.csv` sin tope de filas |
| E-14 | Media | DoS | El multipart se parsea entero antes de comprobar ningún límite |
| E-15 | Media | Infra | `docker-compose.override.yml` se carga solo y corre el target `dev` como root |
| E-16 | Baja | Visor | Canal lateral temporal: documento retirado vs token inexistente |
| E-17 | Baja | Auth | Enumeración de usuarios por tiempo de respuesta en `/login` |
| E-18 | Baja | DoS | Comodines `%` y `_` sin escapar en los filtros `search` |
| E-19 | Baja | Errores | `error_detail` devuelve `params` sin filtro |
| E-20 | Baja | Billing | Webhook de Stripe sin deduplicación por id de evento |
| E-21 | Baja | Secretos | `DEBUG=true` hace que SQLAlchemy registre tokens y hashes |

---

# 1. Arreglar antes de producción

## E-01 · Crítica · SSRF con robo de credenciales de nube vía `endpoint_url`

**Ficheros:** `backend/app/schemas/storage.py:15` · `backend/app/routers/storage.py:100,130-132` · `backend/app/services/storage/s3.py:18-48,80-86` · `backend/app/services/storage/ftp.py:118-138,175-181`

**[VERIFICADO]** `StorageBackendCreate.config` es `dict[str, Any]` con `default_factory=dict` y **ningún validador**. Ese diccionario llega intacto a la fila y de ahí al adaptador:

```python
# s3.py:35-38
self._client_kwargs: dict[str, Any] = {
    "region_name": config.get("region"),
    "endpoint_url": config.get("endpoint_url"),
}
```

`endpoint_url` es la URL base a la que aioboto3/botocore envía **todas** las peticiones firmadas. Un inquilino con `storage:manage` (rol `site_admin` o `mm_admin`) la controla por completo. Lo mismo ocurre con `host`/`port` en `ftp.py:118-119`.

**Por qué es explotable aquí:** hay un disparador síncrono y con respuesta, `POST /api/v1/storage/{backend_id}/test` (`routers/storage.py:157-168`), que llama a `health()` → `head_bucket()` → petición HTTP al `endpoint_url` elegido, y devuelve `ok: true/false`. Eso ya es un escáner de red interna autenticado. Pero lo grave es el segundo paso: en `s3.py:21-25` la sesión se construye así:

```python
return aioboto3.Session(
    aws_access_key_id=credentials.get("access_key_id"),   # None si no se envían secrets
    aws_secret_access_key=credentials.get("secret_access_key"),
    aws_session_token=credentials.get("session_token"),
)
```

Si el inquilino **no** envía `secrets`, `credentials_of()` devuelve `{}` (`base.py:290-295`) y los tres argumentos van a `None`. Botocore trata `None` como "no proporcionado" y recorre su cadena de credenciales: variables de entorno → perfil compartido → rol de contenedor → **IMDS**. La petición se firma con las credenciales del *host* y se envía al servidor del atacante, con `Authorization: AWS4-HMAC-SHA256 Credential=ASIA.../...` y, si son temporales, la cabecera `X-Amz-Security-Token` — **que es la credencial completa, no solo una firma**.

**Escenario de ataque, paso a paso:**
1. El atacante es `site_admin` de cualquier empresa cliente (o compromete una cuenta con ese rol).
2. `POST /api/v1/storage/` con `{"name":"x","kind":"s3","config":{"bucket":"probe","endpoint_url":"http://169.254.169.254","force_path_style":true},"secrets":{}}`.
3. `POST /api/v1/storage/{id}/test` → `ok:true/false` le dice si el servicio de metadatos responde. Repitiendo con distintos `endpoint_url` mapea la red interna (`http://postgres:5432`, `http://redis:6379`, rangos privados) desde dentro del perímetro.
4. Repite el paso 2 apuntando `endpoint_url` a un servidor HTTP propio en Internet.
5. `POST /{id}/test` → su servidor recibe `HEAD /probe` con las cabeceras de firma SigV4 del rol de instancia del host, incluido `X-Amz-Security-Token`.
6. Con esas credenciales temporales accede a los recursos de nube de Estampa desde fuera.

El paso 5–6 es **[SOSPECHA]** en un punto: depende de que el host despliegue con un rol de instancia/contenedor y sin credenciales estáticas en el entorno. No he podido observar el entorno de producción. Los pasos 1–4 (SSRF ciega y escaneo interno) son **[VERIFICADO]** e independientes de eso.

**Corrección:**
- Validar `config` con un modelo Pydantic por `kind`, no un `dict[str, Any]`.
- Lista blanca de `endpoint_url`: exigir `https://`, resolver el nombre y **rechazar toda IP privada, loopback, link-local (`169.254.0.0/16`), CGNAT y IPv6 equivalente**, comprobándolo tras la resolución DNS y de nuevo en la conexión (defensa contra rebind). Lo mismo para `host` de FTP.
- Cortar la cadena de credenciales implícita: si no hay `secrets`, pasar un proveedor vacío explícito (`botocore.credentials` con `aws_access_key_id=""`) o rechazar la configuración. El host nunca debe firmar con su propio rol una petición a un endpoint que elige un inquilino.
- Desplegar la API con `AWS_EC2_METADATA_DISABLED=true` salvo que se use IMDS a propósito; si se usa, exigir IMDSv2 con `hop-limit=1`.

---

## E-02 · Alta · `base_path` del backend local: escritura en ruta arbitraria

**Ficheros:** `backend/app/services/storage/local.py:199-201,213-218,241-248`

**[VERIFICADO]**

```python
self._root = Path(backend.config.get("base_path") or DEFAULT_BASE_PATH)
```

`StorageKind.LOCAL` está en el enum público de `StorageBackendCreate.kind`, así que cualquier usuario con `storage:manage` puede crear un backend local con la raíz que quiera. `health()` escribe `{base_path}/.estampa-health` y `put()` hace `path.parent.mkdir(parents=True)` antes de escribir.

**Escenario:** un `site_admin` crea un backend `{"kind":"local","config":{"base_path":"/app/app/services"}}`, lo marca `is_default`, y llama a `/test`. La API crea y escribe ficheros fuera del volumen previsto. El contenido controlable es limitado (`b"ok"` en `health`, y PDFs bajo un nombre GUID), pero el **primitivo de creación de directorios y escritura en cualquier ruta con permiso del uid 10001** sí es real, y además permite que los documentos de un sitio se archiven fuera del volumen persistente: al reiniciar el contenedor, **los albaranes desaparecen sin que quede rastro de error**. Para un sistema con valor probatorio eso es pérdida de prueba, no solo un fallo técnico.

**Corrección:** `base_path` no debe ser configurable por el inquilino. Fijarlo por variable de entorno del despliegue y, si se mantiene configurable, resolverlo con `Path.resolve()` y exigir `is_relative_to(ALLOWED_ROOT)`. Considerar retirar `LOCAL` del enum expuesto en la API y dejarlo solo como backend sembrado por el operador.

---

## E-03 · Alta · Escalada de privilegios intra-empresa vía `users:manage`

**Ficheros:** `backend/app/routers/users.py:34-42,84-110,201-225` · `backend/app/models/tenancy.py:235-247`

**[VERIFICADO]** `ROLE_PERMISSIONS["site_admin"]` incluye `users:manage`. `_get_user` filtra **solo por `mm_id`**, nunca por `site_id`. `_replace_memberships` reescribe la lista completa de membresías sin comprobar (a) que el objetivo no sea el propio actor, ni (b) que el rol concedido no supere el del actor.

```python
def _company_users(ctx: TenantContext) -> Select[tuple[User]]:
    return select(User).where(User.mm_id == ctx.mm_id)   # sin site_id
```

**Escenario:**
1. Ana es `site_admin` únicamente del Site A de la empresa M. Su JWT lleva `permissions` sin `billing:*`.
2. `GET /api/v1/users/{su_propio_id}` → 200, porque el filtro es por empresa.
3. `PATCH /api/v1/users/{su_propio_id}` con `{"memberships":[{"site_id":"<A>","role":"mm_admin"},{"site_id":"<B>","role":"mm_admin"},{"site_id":"<C>","role":"mm_admin"}]}`. `MembershipWrite` valida que el rol exista en `ROLE_PERMISSIONS` — `mm_admin` existe — y `_assert_sites_belong_to_company` solo comprueba que los sites sean de M, cosa que son.
4. `POST /api/v1/auth/switch-site` con `site_id = B`. `_pick_membership` encuentra la membresía recién creada y emite un JWT con `tenant_id = B` y `permissions = PERMISSIONS` completo.
5. Ana lee, exporta y retira los albaranes del Site B y del Site C, y accede a `billing:manage`.

No cruza la frontera entre empresas (`mm_id` sigue viniendo de `user.mm_id`), pero **sí cruza la frontera de site, que `CLAUDE.md` define como `tenant_id`**. En la práctica, cada delegación de una empresa con varios centros deja de estar aislada de las demás.

`extra_permissions` está correctamente validado contra `PERMISSIONS` (`schemas/tenancy.py:57-63`) y `is_superuser` no es asignable por la API — esos dos flancos están bien cerrados. El agujero es el rol y el conjunto de membresías.

**Corrección:**
- Prohibir que un usuario edite sus propias membresías (`if user.id == ctx.user_id and payload.memberships is not None: raise PermissionDeniedError`).
- Exigir que el rol concedido sea un subconjunto del del actor: `set(ROLE_PERMISSIONS[wanted.role]) <= ctx.permissions`.
- Restringir `users:manage` a los sites donde el actor es administrador, o mover la gestión de roles a un permiso `users:manage_roles` exclusivo de `mm_admin`.

---

## E-04 · Alta · `deca` sin límite → generación de PDF ilimitada

**Ficheros:** `backend/app/schemas/documents.py:363-366` · `backend/app/services/pdf.py:186-190,237-243,333-338` · `backend/app/services/documents.py:627-656`

**[VERIFICADO]** `DocumentGenerateRequest.deca` es `dict[str, Any]` sin `max_length` ni límite de tamaño de valor. `DecaValidator.validate()` solo itera sobre los códigos **del catálogo** (`deca.py:102-107`): las claves desconocidas **no se validan ni se rechazan**. Y `pdf._ordered_items` las dibuja igualmente:

```python
codes += [code for code in values if code not in known and values[code] not in (None, "")]
```

`_draw_fields` → `_row` → `_page_break` genera páginas mientras haya contenido. La comprobación de tamaño `_reject_oversized` (`documents.py:637`) ocurre **después** de renderizar, cuando el coste ya se ha pagado. Todo esto corre dentro de la corrutina del endpoint, sin `to_thread`.

**Escenario:** `POST /api/v1/documents/generate` con `{"deca": {"k0":"X…(100 KB)", "k1":"…", … "k999":"…"}}` — 100 MB de texto en un JSON que pasa la validación sin una sola advertencia. reportlab genera decenas de miles de páginas, consumiendo CPU y memoria, y como es `async def` sin offload **bloquea el event loop entero**: ningún otro cliente de ninguna empresa recibe respuesta mientras dura. Con `documents:create` (rol `operator`, el más bajo que crea documentos) y unas pocas peticiones concurrentes, la API queda inutilizable.

**Corrección:** rechazar claves fuera del catálogo en `DecaValidator.validate()` (o al menos no renderizarlas); limitar `deca` a N claves y M bytes por valor en el esquema Pydantic; comprobar un presupuesto de páginas dentro de `_page_break` y abortar con `DomainError`; mover `render_deca_pdf` a `asyncio.to_thread`.

---

## E-05 · Alta · El parseo de PDF subido bloquea el event loop

**Ficheros:** `backend/app/services/pdf.py:83-101,136-163` · `backend/app/services/documents.py:146,168,594-596`

**[VERIFICADO]** `ingest_upload` llama, sobre bytes enteramente controlados por el atacante y desde la corrutina del endpoint:

```python
text_layer = pdf.has_text_layer(payload)   # PdfReader + extract_text() de 5 páginas
...
page_count=pdf.page_count(payload),        # PdfReader completo
```

`embed_qr` (`pdf.py:136`) hace además `PdfReader` + `merge_page` + reescritura completa, y `stamp_qr` carga el fichero entero en memoria con `b"".join([chunk async for chunk in ...])` (`documents.py:594`).

**Por qué es explotable aquí:** el límite de 5 MB se aplica sobre los bytes **comprimidos**. Un PDF de 5 MB con streams `FlateDecode` anidados, un árbol de páginas con miles de nodos o fuentes patológicas hace que `extract_text()` de pypdf tarde minutos y consuma memoria en órdenes de magnitud superiores. Como no hay `to_thread`, ese tiempo es tiempo en el que **todo el proceso uvicorn está parado**. Y `max_files_per_upload = 100`: una sola petición puede encadenar 100 de esos ficheros en serie.

**Escenario:** un `operator` sube un lote de 100 PDFs bomba de 5 MB. La API deja de responder a todos los inquilinos durante el proceso; el healthcheck de Docker falla y el contenedor se reinicia, abortando las subidas a medias (documentos en `PROCESSING` con `storage_key` ya asignado).

**Corrección:** ejecutar todo el parseo y el renderizado con `asyncio.to_thread` y un `asyncio.timeout` estricto (p. ej. 10 s); mejor aún, mover el análisis al worker Dramatiq —la infraestructura ya existe (`app/tasks/documents.py`)— y dejar el endpoint solo con la comprobación de cabecera mágica y el almacenamiento. Limitar además el número de páginas antes de extraer texto.

---

## E-06 · Alta · Infraestructura no apta para producción

**Ficheros:** `infra/traefik/traefik.yml:23-39` · `docker-compose.yml:9-11,27-28,38-45,52-68` · `infra/traefik/dynamic/middlewares.yml`

**[VERIFICADO]**, todos los puntos leídos en el fichero **base**, no en el override de desarrollo:

1. **Dashboard de Traefik abierto.** `traefik.yml:23-25` declara `api.dashboard: true` e `api.insecure: true`, y `docker-compose.yml:9-11` publica `"8080:8080"`. El comentario dice "Local only", pero está en la configuración estática que usa producción. Cualquiera que alcance el puerto 8080 ve todos los routers, servicios y middlewares, es decir, el mapa completo del despliegue.
2. **Docker socket montado en Traefik** (`docker-compose.yml:15`). El `:ro` protege el fichero, no la API: quien controle Traefik controla el demonio Docker y, por tanto, el host. Con el dashboard abierto al lado, la superficie es desproporcionada.
3. **Redis sin contraseña y publicado** (`docker-compose.yml:41-43`): `redis-server --appendonly yes`, sin `requirepass`, `"6380:6379"`. Redis guarda **la blacklist de JWT y el broker de Dramatiq**. Quien lo alcance puede (a) borrar entradas de blacklist y resucitar tokens revocados, y (b) encolar mensajes `withdraw_document(document_id, mm_id, site_id, reason)` con los ids que quiera — `tenant_context()` en `tasks/broker.py:42-51` construye un contexto con `is_superuser=True` a partir de esos valores sin comprobar nada. Es retirada de albaranes de cualquier empresa desde Redis.
4. **Postgres publicado** en `"5433:5432"` con `POSTGRES_PASSWORD` por defecto `estampa` si la variable no está.
5. **MinIO publicado** en 9000/9001 con `estampa` / `estampa-dev-secret` por defecto.
6. **Sin TLS.** Solo el entrypoint `web` en :80 está en uso; la redirección a `websecure` está comentada (`traefik.yml:30-35`) y no hay `certificatesResolvers`. El middleware pone `stsSeconds: 31536000`, pero HSTS sobre HTTP plano se ignora. Access tokens, cookie de refresco y PDFs viajan en claro.

**Corrección:** `api.insecure: false` y quitar el puerto 8080 del compose base; no publicar 5433/6380/9000/9001 (dejarlos en la red interna); `requirepass` en Redis y `REDIS_URL` con credenciales; activar el resolver ACME y la redirección a `websecure`; considerar un proxy de socket Docker de solo lectura para Traefik. Añadir `security_opt: [no-new-privileges:true]` y `cap_drop: [ALL]` a los servicios.

**Bien resuelto y conviene no tocarlo:** el rate limit de login (5/min por IP, router de prioridad 200 sobre `Path(/api/v1/auth/login)`) está correctamente cableado, `ipStrategy.depth: 1` es el valor adecuado para un único salto de proxy, y el `Dockerfile` del target `runtime` corre como uid 10001 no privilegiado.

---

# 2. Arreglar pronto

## E-07 · Media · El PDF público se sirve sin sanear

**Ficheros:** `backend/app/routers/public.py:92-99` · `backend/app/services/documents.py:428-442` · `backend/app/main.py:115-131`

**[VERIFICADO]** `ingest_upload` almacena `payload` byte a byte tal como llega. No hay eliminación de metadatos ni de JavaScript embebido. `stream_document` lo devuelve con `media_type="application/pdf"`, `Content-Disposition: inline` y las tres cabeceras de `PUBLIC_HEADERS` (`X-Robots-Tag`, `Cache-Control`, `Referrer-Policy`). **No hay `Content-Security-Policy` ni `X-Content-Type-Options` en la respuesta de la aplicación.**

Tres problemas distintos:

- **Fuga de metadatos.** El PDF nativo del ERP del cliente conserva `/Author`, `/Producer`, `/Creator` y el bloque XMP. Es habitual que ahí aparezcan rutas de red internas, nombres de usuario de Windows, versiones de software y nombres de cliente. Todo eso se publica a cualquiera que escanee el QR. Para un sistema que se presume "sin login, indexable, enumerable", es fuga de información interna del inquilino. **[VERIFICADO]** que no se limpia; **[SOSPECHA]** el contenido concreto, que depende de cada ERP.
- **`nosniff` depende de Traefik.** `contentTypeNosniff: true` está en el middleware `security-headers`, pero la aplicación no la emite por su cuenta. Cualquier despliegue que exponga uvicorn sin Traefik delante, o que olvide el middleware en un router nuevo, pierde la protección. Con `Content-Disposition: inline` y un PDF políglota (`%PDF-` en los primeros bytes seguido de HTML), un navegador que husmee el tipo ejecutaría HTML **en el origen de la API**.
- **Sin CSP.** Un PDF con `/OpenAction /JS` se abre en el visor del navegador sin ninguna directiva que lo acote. El sandbox de PDFium limita mucho el daño hoy, pero esto se sirve en el mismo origen que la API y no hay nada que lo impida si el visor cambia o el usuario usa otro.

**Corrección:** normalizar el PDF en la ingesta (pypdf ya está como dependencia: reescribir con `PdfWriter` sin `/Names`, `/OpenAction`, `/AA`, `/JavaScript` ni `/EmbeddedFiles`, y vaciar `metadata`/XMP). Emitir desde la aplicación `X-Content-Type-Options: nosniff` y `Content-Security-Policy: default-src 'none'; object-src 'self'; sandbox` en `PUBLIC_HEADERS`. Considerar servir el visor desde un subdominio distinto del de la API.

## E-08 · Media · El login se rompe si dos empresas comparten un email

**Ficheros:** `backend/app/routers/auth.py:50-53` · `backend/app/models/tenancy.py:287`

**[VERIFICADO]** El índice único es `("mm_id", "email")`, así que el mismo correo puede existir en dos empresas. Pero la búsqueda de login es global y usa `scalar_one_or_none()`:

```python
stmt = select(User).where(User.email == email.lower())
return (await db.execute(stmt)).scalar_one_or_none()
```

Con dos filas, SQLAlchemy lanza `MultipleResultsFound`, que el handler genérico de `main.py:195-209` convierte en **500 para todos los intentos de login de ambos usuarios, de forma permanente**.

**Escenario:** el `mm_admin` de la empresa A crea en su propia empresa un usuario con el correo del administrador de la empresa B (`POST /api/v1/users/` valida unicidad solo dentro de su `mm_id`, `users.py:174-177`). Desde ese momento el administrador de B no puede entrar en el sistema. Es denegación de servicio dirigida y cruzada entre inquilinos, con un único POST y sin dejar nada anómalo en los logs salvo el 500.

**Corrección:** el login debe resolver la empresa antes del usuario (subdominio, slug de MM en el cuerpo, o un identificador de tenant en la URL). Como mínimo inmediato, cambiar a `.scalars().first()` con `order_by` determinista **no** arregla el problema de fondo (elegiría un usuario arbitrario, que es peor); lo correcto es hacer el email globalmente único o exigir el MM en el login.

## E-09 · Media · CRLF en el nombre de fichero inutiliza el documento

**Ficheros:** `backend/app/routers/__init__.py:41-44` · `backend/app/routers/documents.py:332` · `backend/app/routers/public.py:97`

**[VERIFICADO], incluida la mitigación.**

```python
ascii_name = filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
```

`\r` y `\n` son ASCII, sobreviven al saneado y acaban crudos en el valor de la cabecera. Lo he comprobado ejecutando la función: devuelve `'inline; filename="a\r\nX-Injected: yes\r\n\r\n<script>…'`. Starlette tampoco valida (`raw_headers` conserva los bytes).

**La división de respuesta NO es explotable hoy**: uvicorn 0.53 con httptools valida el valor con `HEADER_VALUE_RE = re.compile(b"[\x00-\x08\x0a-\x1f\x7f]")` (`httptools_impl.py:498-499`) y lanza `RuntimeError`; h11 también lo rechaza (`LocalProtocolError`). Lo he verificado contra los paquetes instalados. La defensa es del servidor, no del código.

**Lo que sí ocurre:** `create_from_deca` acepta `filename` desde JSON (`DocumentGenerateRequest.filename`, solo `max_length=255`), donde meter `\r\n` es trivial. El documento queda creado y archivado, pero **cualquier descarga posterior revienta con 500** — tanto `GET /documents/{id}/file` para el dueño como `GET /v/{token}/file` para el inspector que escanea el QR. Un albarán que existe, está en storage, aparece en el listado y **no se puede abrir nunca**. Para un documento con valor probatorio eso es un problema.

**Corrección:** en `content_disposition`, filtrar el nombre a caracteres imprimibles antes de componer la cabecera: `re.sub(r"[^\x20-\x7e]", "_", ascii_name)`. Validar `filename` en el esquema con un patrón que excluya caracteres de control.

## E-10 · Media · `X-Forwarded-For` falsificable contamina el registro legal

**Ficheros:** `backend/app/routers/__init__.py:25-34` · `backend/app/security.py:97-102`

**[VERIFICADO]**

```python
forwarded = request.headers.get("X-Forwarded-For")
if forwarded:
    return forwarded.split(",")[0].strip()
```

Se toma el elemento **más a la izquierda**, que es precisamente el que el cliente controla. Traefik añade la IP real al final de la lista, no al principio. El resultado se convierte en `ip_hash` y se guarda en `document_accesses` y en `audit_logs`.

**Escenario:** quien escanea un QR envía `X-Forwarded-For: 8.8.8.8`. El registro de accesos del documento —la traza que el inquilino enseñaría ante la Inspección para demostrar quién consultó el albarán— queda envenenado con hashes de IPs inventadas, y el acceso real es indistinguible. Vale igual para `auth.login` y para todas las acciones auditadas.

Obsérvese la incoherencia: Traefik usa `ipStrategy.depth: 1` (el elemento correcto, contando desde la derecha) para el rate limit, pero la aplicación usa el opuesto para la auditoría.

**Corrección:** contar desde la derecha con el número de proxies de confianza, igual que Traefik, o usar directamente `request.client.host` con `--proxy-headers --forwarded-allow-ips` configurado en uvicorn.

## E-11 · Media · `HEAD /v/{token}` valida tokens sin dejar rastro

**Fichero:** `backend/app/routers/public.py:70-74`

**[VERIFICADO]** El docstring lo declara abiertamente: *"Lets a scanner check the link without leaving an access-log entry"*. `head_document` llama a `_resolve()` y devuelve 200 o 404, pero **no** llama a `record_public_access`.

**Por qué importa aquí:** el producto vende que toda consulta del albarán queda registrada. Quien obtenga tokens (foto de una etiqueta, historial del navegador, un QR fotografiado en un muelle) puede comprobar indefinidamente cuáles siguen vivos y cuáles se han revocado, sin generar ni una fila en `document_accesses` ni incrementar `access_count`. Es un punto ciego deliberado en la traza que el inquilino usará como prueba.

**Corrección:** registrar también los HEAD, quizá con un tipo de acceso distinto (`method: "HEAD"`) para no contaminar la estadística de escaneos reales, o retirar el método HEAD si ningún cliente lo necesita.

## E-12 · Media · Los claims del access token no se revalidan

**Ficheros:** `backend/app/deps.py:77-95,223-233` · `backend/app/config.py:288`

**[VERIFICADO]** `get_current_context` construye el `TenantContext` exclusivamente con los claims del JWT y no consulta la base de datos. `require_permission` depende solo de él. `get_current_user` —que sí comprueba `is_active`— **no lo usa ningún router de recursos**; solo los de `auth` verifican el usuario, y a través de `_active_user`.

Consecuencia, durante `access_token_minutes` (30 por defecto): desactivar un usuario, bajarle el rol o quitarle la membresía de un site **no tiene ningún efecto**. Sigue leyendo, exportando y retirando documentos del site que lleva en el token. El único mecanismo de revocación es la blacklist por `jti`, y `jti` solo se conoce si el propio usuario llama a `/logout`.

Un despido o un compromiso de cuenta deja una ventana de 30 minutos sin forma de cerrarla desde la aplicación.

**Corrección:** revalidar en `get_current_context` que el usuario sigue activo y que la membresía `(user_id, site_id)` existe, contra una caché corta en Redis para no pagar una consulta por petición. Alternativamente, una lista de revocación por `user_id` con marca temporal ("todos los tokens emitidos antes de T son inválidos") que se escriba al desactivar o cambiar de rol.

## E-13 · Media · `export.csv` sin tope

**Ficheros:** `backend/app/routers/documents.py:203-213` · `backend/app/services/documents.py:444-456`

**[VERIFICADO]** `export_csv` hace `scoped_select(...).where(*conditions).order_by(...)` sin `.limit()`. Usa `db.stream()`, lo cual evita cargar todo en memoria del proceso —bien—, pero mantiene abierta una transacción y un cursor mientras recorre el archivo entero, y por cada documento serializa además todos los códigos del catálogo DECA.

El resto de la API está correctamente acotada (`MAX_PAGE_SIZE = 200`), así que este es el único endpoint por el que se puede pedir todo de una vez. Varias peticiones concurrentes agotan el pool (`pool_size=10, max_overflow=20`, `db.py:19-21`) y bloquean al resto de inquilinos.

**Corrección:** tope de filas con paginación por cursor, o encolar la exportación como job y entregar el resultado por descarga diferida. Rate limit específico para este endpoint en Traefik.

## E-14 · Media · El multipart se parsea entero antes de cualquier límite

**Ficheros:** `backend/app/routers/documents.py:128-146` · `backend/app/services/documents.py:592-614`

**[VERIFICADO]** `_read_upload` sí aplica el límite **durante** el streaming, chunk a chunk (`documents.py:594-608`) — eso está correctamente hecho, tal como exige `backend.md`. El problema está antes: cuando el cuerpo de la función se ejecuta, Starlette ya ha parseado **todo** el multipart y ha volcado cada fichero a un `SpooledTemporaryFile` en disco. La comprobación `len(files) > max_files_per_upload` (`documents.py:140`) ocurre después de ese volcado.

**Escenario:** un `operator` envía un POST multipart de 50 GB. El disco del contenedor se llena antes de que ninguna comprobación de la aplicación llegue a ejecutarse. No hay `buffering` ni límite de tamaño de cuerpo en Traefik (`middlewares.yml` no define `buffering.maxRequestBodyBytes`).

**Corrección:** middleware de Traefik `buffering: { maxRequestBodyBytes: <max_files × max_upload_mb + margen> }`, y comprobar `Content-Length` en un middleware ASGI propio antes de que el parser toque nada.

## E-15 · Media · El override de desarrollo se carga solo

**Fichero:** `docker-compose.override.yml:1-3,146-163`

**[VERIFICADO]** Docker Compose carga `docker-compose.override.yml` automáticamente. Ese fichero cambia el build a `target: dev` —que corre **como root**, sin el `USER estampa` del target `runtime`—, monta el código fuente desde el host, fija `DEBUG: "true"` y `ENVIRONMENT: local`, y añade `--api.insecure=true` a Traefik.

El aviso está en un comentario de la primera línea. Un `docker compose up -d` en el servidor de producción arranca ese perfil sin decir nada. `DEBUG=true` además activa `echo` de SQLAlchemy (ver E-21) y reactiva `/docs` y `/openapi.json` (`main.py:151-152`).

**Corrección:** renombrar a `docker-compose.dev.yml` y exigir `-f` explícito, o añadir un `profiles:` que no se active por defecto. Que `check_env.py` se ejecute como parte del arranque, no solo como paso manual del despliegue.

---

# 3. Menor, pero anotado

**E-16 · Baja · Canal lateral temporal en el visor** (`documents.py:469-492`). **[VERIFICADO]** por lectura: un token inexistente o revocado sale tras **una** consulta (`select(ShareToken)` → `None`); un documento retirado o sustituido requiere **tres** (share token + `db.get(Document)` + `db.get(Site)`) antes de devolver el mismo 404. Código, cuerpo, longitud y cabeceras son idénticos —eso está bien resuelto— pero la diferencia de latencia (dos viajes extra a Postgres) es medible. Permite distinguir "este token fue válido y el documento se retiró" de "este token nunca existió", que es justo lo que `CLAUDE.md` promete no revelar. **[SOSPECHA]** que sea explotable de forma fiable sobre Internet con ruido de red; sobre una red cercana, sí. *Corrección:* resolver documento y sitio en un único `select().join()` y devolver el 404 tras un tiempo constante.

**E-17 · Baja · Enumeración de usuarios por tiempo en `/login`** (`auth.py:129-137`). **[VERIFICADO]** Si `_user_by_email` devuelve `None`, `verify_password` no llega a ejecutarse y la respuesta sale en ~1 ms; con un usuario existente, argon2 tarda decenas de milisegundos. La diferencia es de dos órdenes de magnitud. El rate limit de 5/min por IP lo ralentiza, no lo impide. *Corrección:* verificar siempre contra un hash señuelo precomputado cuando el usuario no exista.

**E-18 · Baja · Comodines LIKE sin escapar** (`documents.py:812-821`, `users.py:157-158`, `sites.py:62`). **[VERIFICADO]** `f"%{search}%"` pasa `%` y `_` del usuario al patrón. No es inyección SQL (el parámetro va enlazado), pero `search="%"` fuerza un recorrido completo de la tabla del inquilino, y `search="_"*50` genera un patrón caro. *Corrección:* escapar `%`, `_` y `\` y usar `ESCAPE`.

**E-19 · Baja · `error_detail` devuelve `params` sin filtro** (`errors.py:303-311`). **[VERIFICADO]** `detail["params"] = exc.params` se serializa entero al cliente. Hoy los `params` que se usan son inocuos (nombres de fichero, etiquetas, límites). Pero es una decisión de diseño que convierte cualquier futuro `DomainError("X", host=..., key=...)` en una fuga automática. Nótese que `STORAGE_UNREACHABLE` ya lleva `name=self._name` —el nombre del backend, no una credencial—, y que `decrypt_secret` lanza `STORAGE_SECRET_UNREADABLE` **sin** parámetros, que es lo correcto. *Corrección:* lista blanca explícita de claves publicables por código de error.

**E-20 · Baja · Webhook de Stripe sin deduplicación** (`billing.py:257-283,302-311`). **[VERIFICADO]** `stripe.Webhook.construct_event` verifica HMAC-SHA256 y la tolerancia temporal por defecto de 300 s, así que la firma y la resistencia a repetición básica **están bien**. No hay registro de `event.id`, de modo que un evento capturado puede reenviarse dentro de esos 5 minutos; los handlers son asignaciones idempotentes de estado, así que el impacto es nulo hoy. Anoto también que `_mm_id_of` (`billing.py:431-436`) confía en `data.metadata.mm_id`: si algún día ese metadato fuera editable por el cliente desde el portal de Stripe, `_target_of` permitiría a una empresa mutar la suscripción de otra. Con `BILLING_ENABLED=false` nada de esto está activo. *Corrección:* tabla de `processed_events` con el `event.id`.

**E-21 · Baja · `DEBUG=true` registra tokens y hashes** (`db.py:16`, `.env.example:209`). **[VERIFICADO]** `echo=_settings.debug` hace que SQLAlchemy escriba en stdout todas las sentencias **con sus parámetros enlazados**: `hashed_password` en el login, `share_tokens.token` en cada resolución del visor. `.env.example` reparte `DEBUG=true` como valor por defecto. `check_env.py:117-118` lo rechaza en producción —bien—, pero solo si alguien ejecuta el script; nada en el arranque lo comprueba. *Corrección:* que `Settings` rechace `debug=True` cuando `environment == "production"`, en un validador de modelo.

**Nota sobre `.env.example`:** no induce a una configuración insegura en los secretos (los tres llevan `CHANGE_ME` con el comando exacto para generarlos, y `check_env.py` los caza). Sí induce a error en dos puntos menores: `POSTGRES_PASSWORD=estampa` no lleva marca `CHANGE_ME` —aunque `WEAK_VALUES` lo atrapa— y `DEBUG=true`/`ENVIRONMENT=local` son los valores repartidos por defecto.

---

# 4. Lo que está bien resuelto (no romper)

Verificado leyendo el código. Estas son las defensas que sostienen el sistema hoy:

1. **Aislamiento entre empresas.** `scoped()` / `scoped_select()` (`deps.py:236-250`) aplican siempre `mm_id` **y** `site_id`, y fallan en tiempo de ejecución si el modelo no hereda `TenantScoped`. He revisado todas las consultas de `services/` y `routers/`: no he encontrado ni una sola lectura de tabla con ámbito sin ambos filtros. El test AST de `tests/test_tenant_isolation.py` vigila estáticamente `select()` y `db.get()` sobre modelos con ámbito y exige una pragma `# tenant-exempt:` razonada. Es un buen control; conviene que siga en el gate de CI.
2. **`is_superuser` no salta el filtro de tenant.** `TenantContext.has()` (`deps.py:157-158`) solo puentea el permiso; `scoped()` no consulta ese flag en ningún punto, y `_permissions_of` (`auth.py:95-96`) concede permisos pero toma `mm_id`/`site_id` de la membresía real. Comprobado explícitamente.
3. **Las dos exenciones `# tenant-exempt` son legítimas.** La del visor (`documents.py:480`) resuelve por un secreto de 192 bits sin sesión. La del barrido (`retention.py:433-436`) escribe cada fila bajo el `mm_id`/`site_id` que la propia fila ya lleva; no hay mezcla posible.
4. **`tenant_backend()`** (`storage/ownership.py:361-375`) es ejemplar: tras un `db.get` por clave primaria **vuelve a comprobar** que el backend pertenece al mismo tenant y lanza un 500 si no. Exactamente lo que hay que hacer con un `db.get`.
5. **Entropía del token del visor.** `secrets.token_urlsafe(24)` = **192 bits** de un CSPRNG (comprobado ejecutándolo: 32 caracteres url-safe). Independiente del GUID, revocable, con `UniqueConstraint`. La enumeración no es viable ni de lejos; el rate limit del visor no es lo que protege aquí, y está bien que así sea.
6. **Respuesta uniforme del visor.** Desconocido, revocado, expirado, retirado y sustituido devuelven todos `SHARE_TOKEN_UNKNOWN` con 404, mismo cuerpo y mismas cabeceras (`public.py:37-42`, `documents.py:882-885`), y las cabeceras se aplican también a los errores gracias a `PublicViewerHeadersMiddleware` (`main.py:122-131`) y a la dependencia `harden` del router. Salvo el matiz temporal de E-16, esto está bien hecho.
7. **Sin inyección SQL.** No hay ni un `text()`, ni un `execute("…")`, ni SQL construido con formato de cadena en todo `app/`. Todo son expresiones de SQLAlchemy Core con parámetros enlazados.
8. **El storage nunca se expone.** Todo el contenido se transmite por streaming desde la API (`open_stream`); no se genera ninguna URL firmada, y `normalise_key` (`storage/base.py:298-304`) rechaza `.` y `..`. Además `storage_key_for` compone la clave solo con UUIDs del contexto, sin nada del usuario: no hay traversal posible por esa vía.
9. **Sesión.** El refresh token viaja en cookie `HttpOnly` + `Secure` (fuera de local) + `SameSite=strict` + `Path` acotado a `/auth`, con verificación de origen adicional en `/refresh` (`cookies.py`). La rotación pone el token viejo en la blacklist, y `switch-site` invalida **ambos** tokens, cerrando la fijación de sesión. El access token va en la cabecera `Authorization`, así que el resto de la API no es vulnerable a CSRF. CORS con un único origen exacto.
10. **JWT.** Lista de algoritmos fija (`algorithms=[settings.jwt_algorithm]`, sin `none`), firma verificada, `exp` comprobado por PyJWT, y **confusión de tipo access/refresh cerrada explícitamente** con el claim `type` (`security.py:87-88`). Argon2 para contraseñas con `check_needs_rehash`.
11. **La blacklist falla cerrada.** Si Redis no responde, `is_blacklisted` propaga la excepción de conexión, que se convierte en 500 y **deniega el acceso**. No falla abierta. (Es ruidoso, pero es la dirección correcta.)
12. **Secretos de storage.** Fernet en `config_encrypted`; `StorageBackendRead` **no tiene** campo `secrets`, ni siquiera enmascarado (`schemas/storage.py:304-316`); `credentials_of` no registra nada; no hay un solo `logger` ni `print` que toque credenciales en todo `app/`. El procedimiento de rotación de `STORAGE_SECRET_KEY` está documentado en `docs/RUNBOOK.md §3` con el script de re-cifrado.
13. **Comprobación de PDF.** Cabecera mágica `%PDF-` en el offset 0, nunca la extensión ni el `content-type` del navegador, que se registra pero no se usa (`documents.py:196`). No hay ningún parser XML en el camino de la subida, así que **no hay superficie XXE**.
14. **Límite de subida durante el streaming.** `_read_upload` corta en cuanto se supera el máximo, sin esperar a terminar de leer.
15. **Escapado en el HTML de etiquetas.** `_label_cell` (`printing.py:460-469`) pasa `html.escape` a filename, short_id y fecha. El único contenido sin escapar es el SVG del QR, generado por segno a partir de una URL que compone el servidor. Correcto.
16. **404 y no 403** para objetos de otro tenant, en todos los servicios revisados.
17. **Paginación acotada** a `MAX_PAGE_SIZE = 200` en todas partes salvo `export.csv` (E-13).
18. **Imagen de runtime no root** (uid 10001) y `.gitignore` que excluye `.env` y `.env.*` salvo el ejemplo; `git ls-files` confirma que no hay ningún `.env` real versionado.
19. **`check_env.py`** cubre placeholders, valores triviales, longitudes mínimas, validez de la clave Fernet, `DEBUG`, `ENVIRONMENT`, `PUBLIC_BASE_URL` con https y el mínimo legal de retención.

---

# 5. Orden de trabajo sugerido

**Antes de producción, sin excepción:** E-01 (validar `config` y cortar la cadena de credenciales de botocore), E-06 (cerrar dashboard, Redis con contraseña, dejar de publicar puertos, activar TLS), E-03 (auto-ascenso), E-02 (`base_path`), E-04 y E-05 (agotamiento de recursos).

**En el primer sprint posterior:** E-07 (limpieza del PDF público y cabeceras propias), E-12 (revalidación de sesión), E-08 (login multi-empresa), E-09, E-10, E-11, E-14, E-15.

**Cuando toque:** el resto, y el endurecimiento de E-19 antes de añadir cualquier código de error nuevo que lleve parámetros.

**Recomendación de proceso:** los controles que hoy funcionan bien (el test AST de aislamiento, `check_env.py`, el catálogo de permisos centralizado) lo hacen porque son automáticos. Merece la pena añadir al mismo gate un test que verifique que `StorageBackendCreate.config` no acepte hosts privados y otro que compruebe que ninguna respuesta del visor público contiene metadatos del PDF original.

# Auditoría de seguridad 2 — revisión de los arreglos de E-01..E-21

**Alcance:** únicamente los cambios hechos para cerrar `docs/SECURITY-AUDIT.md` (commits `3094a46`..`6bf969f`, rama `claude/ceca-pdf-qr-manager-uf3ga3`; el rango `a933312..HEAD` indicado en el encargo sólo contiene la cola de esos arreglos, así que se ha revisado el árbol resultante completo de `backend/app`, `infra/traefik`, `docker-compose*.yml` y `scripts/`).
**Método:** lectura del código y, donde se indica, ejecución de funciones aisladas con `backend/.venv/bin/python`. No se ha levantado la aplicación ni Traefik. **Nada ha sido modificado.**

Cada afirmación lleva una de tres marcas:

- **[EJECUTADO]** — comprobado ejecutando código (la salida está en §3).
- **[LECTURA]** — comprobado leyendo el código o la fuente del componente citado.
- **[SOSPECHA]** — depende de una condición del entorno que no he podido observar.

---

## Estado de los arreglos (2026-09-18, misma rama, tras la auditoría)

Añadido después de la auditoría. Cada línea dice qué se cambió y qué test lo pina;
nada de lo que sigue estaba hecho cuando se escribió el resto del documento.

| # | Estado | Qué se hizo | Test |
|---|--------|-------------|------|
| N-01 | **Cerrado** | `login-ratelimit` y `viewer-ratelimit` sin `ipStrategy`: clave = peer TCP, que con Traefik en el borde es el cliente. La app sigue con `TRUSTED_PROXY_COUNT=1` | `test_infra_hardening.py::test_the_proxy_hop_count_matches_the_rate_limit_strategy` |
| N-02 | **Cerrado en la API** | El plazo se comprueba **dentro** de la página, por operador (`visitor_operand_before`), no solo entre páginas: el hilo se para al vencer, no solo la petición. Antes de tokenizar, una página con más de 3 MB de contenido inflado se rechaza (`PDF_PAGE_TOO_COMPLEX`), que es la fase que ningún hook interrumpe. Medido: 150 000 operadores con plazo de 0,2 s → el hilo termina en 0,65 s; 600 000 con texto → rechazo en < 1 s | `test_pdf_hardening.py::test_a_content_stream_that_never_ends_stops_at_the_deadline`, `::test_a_page_with_megabytes_of_operators_is_refused_before_parsing` |
| N-03 | **Cerrado** | `update_user`: antes de tocar contraseña, `is_active` o membresías de otro, el objetivo no puede tener en ningún site del actor más permisos que el actor (`USER_OUTRANKS_ACTOR`, 403); contraseña e `is_active` exigen además que el objetivo no pertenezca a ningún site fuera del ámbito del actor; un superusuario solo lo edita otro superusuario. El `mm_admin` sigue administrando a todos | `test_security_audit_2.py` (cuatro tests: mm_admin intocable, colega con site ajeno intocable, operador sí, mm_admin sobre site_admin sí) |
| N-04 | **Cerrado** | `AioConfig(http_session_cls=…)` con una `aiohttp.ClientSession` que fuerza `allow_redirects=False` en toda petición del cliente S3 | `test_security_audit_2.py::test_the_s3_http_session_refuses_redirects` |
| N-05 | **Cerrado** | `validate_host()` para FTP (mismas reglas que el endpoint S3, cualquier puerto 1–65535), aplicada en `validate_config("ftp")` y de nuevo en el constructor del adaptador; `connection_timeout=10`, `socket_timeout=30` en aioftp | `::test_an_internal_ftp_host_is_refused`, `::test_the_ftp_adapter_bounds_its_connections` |
| N-06 | **Cerrado** | Un solo `Config` con timeouts, reintentos y `addressing_style` | `::test_the_s3_client_config_keeps_its_timeouts_with_path_style` |
| N-07 | Abierto | Sin cambio. El tope global de cuerpo (501 MB) y el de Traefik siguen siendo los únicos durante la recepción. Deuda documentada en `GO-LIVE.md` §4 | — |
| N-08 | Abierto | Sin cambio: `getaddrinfo` sigue siendo síncrono en `S3Storage.__init__`. Mitigado por N-04 y por el hecho de que solo afecta a backends S3 con nombre de host. Deuda en `GO-LIVE.md` §4 | — |
| N-09 | **Cerrado** | `100.64.0.0/10` se trata como interno en `_is_forbidden` | `::test_carrier_grade_nat_is_not_public` |
| N-10 | **Cerrado** | `apply_due` confirma tras cada documento retirado, no al final del lote | ruta cubierta por `test_retention_lock.py` y el barrido real de `GO-LIVE.md` |
| N-11 | Abierto (baja) | Sin cambio: `X-Request-ID` del cliente sin acotar. Sin inyección posible (h11 + JsonFormatter); solo relleno de logs | — |
| N-12 | **Cerrado** | `logout` y `switch-site` ignoran una cookie de refresco caducada o inválida y la borran igual | `::test_logout_with_a_broken_refresh_cookie_still_clears_it` |
| N-13 | **Cerrado** | `check_env.py::check_storage_egress` rechaza `ALLOW_PRIVATE_STORAGE_ENDPOINTS=true` | `::test_check_env_rejects_private_storage_endpoints` |

Además, un defecto encontrado al escribir los tests: `_load_adapters()` tomaba el
registro de storage por completo en cuanto contenía **un** adaptador, así que
importar `s3` a mano dejaba el adaptador `local` sin registrar
(`STORAGE_KIND_UNAVAILABLE`). Ahora usa una bandera propia.

---

## Resumen

Los arreglos son, en general, de buena factura: la cookie de refresco, el ámbito de administración, la marca de época de sesión, la deduplicación de Stripe, el lock de Redis y la infraestructura base están bien hechos. Pero **dos de los seis bloqueantes originales siguen abiertos por otra puerta** y el arreglo de E-10 ha consolidado una premisa falsa sobre Traefik que convierte los rate limits en un único cubo global:

1. **N-01 (Alta)** `ipStrategy.depth: 1` con Traefik en el borde produce clave `""` para todo cliente público: el login de toda la plataforma se bloquea con 10 peticiones por minuto y el visor con 60.
2. **N-02 (Alta)** El "techo de 10 s" del análisis PDF no acota nada: un fichero de 70 KB mantiene un hilo a 100 % de CPU más de 8 minutos, y como pypdf es Python puro el GIL degrada el event loop. E-05 sigue abierto.
3. **N-03 (Alta)** Un `site_admin` puede cambiar la contraseña, desactivar o degradar al `mm_admin` que comparta un site con él: E-03 por otra puerta, un PATCH y un login.
4. **N-04 / N-05 (Alta)** El guardarraíl SSRF se salta con una redirección HTTP (comprobado) y el backend FTP no se valida en absoluto y no tiene timeout (comprobado): E-01 queda cerrado sólo en su parte más grave (robo de credenciales del host).

---

## 1. Veredicto por hallazgo original

| # | Veredicto | Evidencia |
|---|-----------|-----------|
| E-01 SSRF `endpoint_url` | **CERRADO A MEDIAS** | Cerrado lo grave: `s3.py:30-33` exige `access_key_id`/`secret_access_key` (**[EJECUTADO]** `STORAGE_CREDENTIALS_REQUIRED` sin secretos), así que botocore nunca recorre la cadena de credenciales del host. `validation.py:52-87` rechaza privadas/loopback/link-local/multicast/reservadas/no especificadas, en escritura (`routers/storage.py:101,134`) y al construir el adaptador (`s3.py:60`), y cubre `::ffff:169.254.169.254`, `2130706433`, `0x7f000001`, `127.1`, `localhost` **[EJECUTADO]**. Residual: redirección HTTP (N-04), FTP sin validar (N-05), CGNAT permitido (N-09), rebinding DNS (TOCTOU entre `getaddrinfo` en validación y la resolución propia de aiohttp, **[LECTURA]**), y `_no_metadata_lookup()` (`s3.py:42-46`) no desactiva nada: es sólo timeouts, y se pierde con `force_path_style` (N-06). |
| E-02 `base_path` | **CERRADO** | `validation.py:90-110` resuelve con `Path.resolve()` (sigue symlinks) y exige `root` en `candidate.parents`; `local.py:21` lo re-aplica a filas antiguas. **[EJECUTADO]** rechaza `../../etc`, `/etc/passwd`, `sub/../..` y el falso prefijo `/var/lib/estampa/storage2`. |
| E-03 auto-ascenso | **CERRADO A MEDIAS** | Cerrado lo descrito: `users.py:310-313` prohíbe editar las propias membresías; `77-90` exige que rol+extras ⊆ lo que el actor tiene en ese site; `AdminScope` (`deps.py:128-179`) se construye de la BD, no del JWT; `_replace_memberships` no toca sites fuera del ámbito. Residual: **no se comprueba el rango del objetivo** — contraseña, `is_active` y degradación de un superior (N-03). |
| E-04 `deca` sin límite | **CERRADO** | `schemas/documents.py:29-50` (40 campos, clave `^[a-z][a-z0-9_]*$` ≤64, valor escalar ≤1000); `documents.py:999-1015` rechaza códigos fuera del catálogo; `1018-1031` presupuesta caracteres **antes** de renderizar; `pdf.py:594-602` aborta a 20 páginas; render en `to_thread`. **[LECTURA]** |
| E-05 PDF bomb | **CERRADO A MEDIAS** | Offload y techos declarados existen (`pdf.py:148-175`), pero el plazo sólo se mira **entre páginas** (`pdf.py:238-239`), `/Count` y `/Size` son afirmaciones del atacante y `len(reader.pages)` (`227-232`) recorre el árbol real sin plazo. **[EJECUTADO]**: una página de 70 KB → la petición responde `PDF_ANALYSIS_TIMEOUT` a los 12 s y el hilo sigue >8 min. Ver N-02. |
| E-06 infra | **CERRADO** | `traefik.yml:37-39` dashboard e `insecure` a `false`, sin entrypoint 8080; compose publica sólo 80/443 (`:28-30`), Postgres/Redis/MinIO con `expose` (`:58,84,102`), Redis `--requirepass` obligatorio (`:76-81`), TLS+ACME+redirección (`traefik.yml:41-73,86-93`, `tls.yml`), `no-new-privileges` y `cap_drop: ALL` en api/worker/scheduler. **[LECTURA]** Socket Docker sigue montado (documentado como aceptado). `forwardedHeaders.trustedIPs` con rangos privados: ver N-01. |
| E-07 visor sin sanear | **CERRADO A MEDIAS** (por decisión) | La app emite `nosniff` y CSP con `sandbox` (`public.py:32-41`) y limpia los metadatos del PDF **generado** (`pdf.py:355-366`). El PDF **subido** no se toca: sólo se avisa (`pdf.py:256-275`, `documents.py:213-219`); decisión registrada en el commit `a933312`. La fuga de `/Author`, `/Producer`, XMP y de `/OpenAction`/`/JS` sigue existiendo para nativos del ERP. Observación: la SPA renderiza vía `fetch` + pdf.js (`pdf-viewer.tsx:36-39`), así que la CSP de la respuesta del fichero no afecta al visor; el enlace `<a href={file_url} target="_blank">` (`public-viewer-page.tsx:87`) navega con `Accept: text/html` y Traefik lo enruta a la SPA, no a la API. |
| E-08 email duplicado | **CERRADO** | Migración `0004` crea `ix_users_email` único y **aborta si ya hay duplicados** (`_reject_duplicates`); `users.py:266-272` devuelve 409 antes; `auth.py:50-61` documenta por qué `scalar_one_or_none` es seguro ahora. **[LECTURA]** |
| E-09 CRLF en nombre | **CERRADO** | `routers/__init__.py:71-73` sustituye `[\x00-\x1f\x7f]` en el constructor de cabecera; `documents.py:984-996` sanea lo ya archivado; `schemas/documents.py:39` rechaza en entrada. **[EJECUTADO]**: `a\r\nX-Injected: yes\r\n.pdf` → `filename="a__X-Injected: yes__.pdf"; filename*=UTF-8''a__X-Injected%3A%20yes__.pdf` (el `filename*` va percent-encoded, sin CR/LF posible). |
| E-10 `X-Forwarded-For` | **CERRADO** (lado app) | `routers/__init__.py:45-51` cuenta desde la derecha. **[EJECUTADO]** con `TRUSTED_PROXY_COUNT=1`: `atacante, 203.0.113.9` → `203.0.113.9`; sin cabecera → peer. **[LECTURA de fuente]**: Traefik borra el XFF de un peer no confiable (`forwardedheaders/forwarded_header.go`) y el peer lo añade `httputil.ReverseProxy` de Go al reenviar (`reverseproxy.go`, Go 1.22), es decir **después** de los middlewares. Correcto para la app; incorrecto para los rate limits (N-01). **[SOSPECHA]**: si el host publica 80/443 vía docker-proxy (p. ej. IPv6 sin `ip6tables`), Traefik ve como peer la pasarela `172.x`, que está en `trustedIPs`, y el `ip_hash` registrado sería la pasarela para todos. |
| E-11 `HEAD /v/{token}` | **CERRADO** | `public.py:86-108` registra el acceso igual que GET. **[LECTURA]** |
| E-12 claims sin revalidar | **CERRADO** | `cache.py:77-110` marca `jwt:epoch:{user}` con TTL = vida del access + 60 s; `deps.py:90` la contrasta en cada petición; se escribe en `users.py:332-335` (`is_active`, `memberships`, `password`) y `sites.py:132-133`. **[EJECUTADO]**: `iat == epoch` pasa (`<` estricto), `iat` con fracción de segundo; no hay carrera en el mismo milisegundo salvo igualdad exacta, que se resuelve a favor del token nuevo (correcto, es el que lleva los claims nuevos). El refresh no se contrasta a propósito y reconstruye de BD comprobando `is_active` (`auth.py:172-181`). |
| E-13 export sin tope | **CERRADO** | `documents.py:56,496-508` `.limit(10_000)` + fila marcador; cabeceras `X-Export-*` (`routers/documents.py:355-362`). **[LECTURA]** |
| E-14 multipart | **CERRADO A MEDIAS** | Cerrado lo descrito: cuerpo leído a mano, `Content-Length` + contador durante el streaming (`routers/documents.py:157-200`), tope en Traefik (`middlewares.yml:10-14`). Residual: el tope **por fichero** (5 MB) sólo se aplica tras el parseo; ver N-07. |
| E-15 override | **CERRADO** | `docker-compose.dev.yml` exige `-f`; `traefik.dev.yml` separado; `config.py:79-94` impide `DEBUG=true` con `production`. **[LECTURA]** |
| E-16 canal temporal visor | **NO ABORDADO** | `documents.py:529-545` sigue haciendo 1 consulta (token inexistente) frente a 3 (retirado). |
| E-17 tiempo en `/login` | **NO ABORDADO** | `auth.py:142` cortocircuita `verify_password` si el usuario no existe. |
| E-18 comodines LIKE | **NO ABORDADO** | `documents.py:874`, `users.py:249`, `sites.py:63` siguen con `f"%{search}%"` sin `ESCAPE`. |
| E-19 `params` sin filtro | **NO ABORDADO** | `errors.py:78-79` sigue serializando `exc.params` entero. |
| E-20 webhook sin dedup | **CERRADO** | `billing.py:164-225` + migración `0005`: `db.get` para la repetición común; INSERT bajo savepoint para la carrera (la segunda inserción espera el lock de PK y falla al confirmar la primera → duplicado → 200); el handler corre dentro del savepoint externo, así que un fallo deshace el registro y la excepción sale como no-2xx → Stripe reintenta. **[LECTURA]** Correcto. |
| E-21 `DEBUG` en producción | **CERRADO** | `config.py:79-94`. Nota: sólo con `ENVIRONMENT=production`; `staging` con `DEBUG=true` sigue haciendo `echo`. **[LECTURA]** |

---

## 2. Hallazgos nuevos

### N-01 · Alta · Los rate limits de login y del visor usan un único cubo global

**Ficheros:** `infra/traefik/dynamic/middlewares.yml:44-62` · `infra/traefik/traefik.yml:52-73` · `backend/tests/test_infra_hardening.py:150-163`

**[LECTURA de fuente, no ejecutado contra Traefik]** La cadena, componente a componente:

1. `forwardedheaders/forwarded_header.go` (Traefik v3.1): si el peer no está en `trustedIPs` e `insecure` es falso, **borra** `X-Forwarded-For` (y el resto de `X-Forwarded-*`). `rewrite()` sólo fija `X-Real-Ip`, `X-Forwarded-Proto/Host/Port/Server`; **no añade el peer a `X-Forwarded-For`**.
2. `ip/strategy.go`: `DepthStrategy.GetIP` hace `strings.Split(xff, ",")`; con cabecera ausente devuelve `[""]`, `len 1 ≥ depth 1`, y retorna `""`.
3. `middlewares/extractor.go`: el extractor de `ipStrategy` devuelve `strategy.GetIP(req)` sin fallback a `RemoteAddr`; el rate limiter usa esa cadena como clave del cubo.
4. El peer se añade a `X-Forwarded-For` en `httputil.ReverseProxy.ServeHTTP` de Go (`reverseproxy.go`), es decir, al reenviar al backend, **después** de todos los middlewares. Por eso la app (E-10) sí lo ve y Traefik no.

Consecuencia: todo cliente de Internet (fuera de 10/8, 172.16/12, 192.168/16) comparte la clave `""`. Y un cliente **dentro** de esos rangos (otro contenedor, la red de oficina si el servidor está en ella, o cualquier peer visto tras docker-proxy) envía el `X-Forwarded-For` que quiera y elige su propia clave.

**Escenario:** el atacante envía 10 `POST /api/v1/auth/login` en un minuto (burst 10) y luego 5 por minuto. Todo usuario de todas las empresas recibe 429 al intentar entrar, indefinidamente, con un coste de 5 peticiones/minuto sin autenticar. Con 60 `GET /v/x` por minuto, ningún inspector puede abrir ningún DeCA.

La auditoría original dio `depth: 1` por correcto; es un error de aquella auditoría. Pero el arreglo de E-10 lo ha **consolidado**: `test_infra_hardening.py:161` exige `depth == 1`, y los comentarios de `traefik.yml:52-55`, `middlewares.yml:40-43` y `routers/__init__.py:35-40` enuncian la premisa falsa ("Traefik appends the peer address on the right… matching `ipStrategy.depth: 1`"). El próximo que lo toque lo dejará como está.

**Corrección:** quitar `sourceCriterion.ipStrategy` de `login-ratelimit` y `viewer-ratelimit` (el defecto, `RemoteAddr`, es el correcto cuando Traefik es el borde); dejar `TRUSTED_PROXY_COUNT=1` en la app, que **sí** es correcto; reducir `trustedIPs` a la red del balanceador real si lo hay, o quitarlo; cambiar el test para que exija la **ausencia** de `depth` y corregir los tres comentarios. Si algún día se pone un CDN delante, entonces `depth: 1` en Traefik y `TRUSTED_PROXY_COUNT=2` en la app.

### N-02 · Alta · El techo de tiempo del análisis PDF no acota el hilo; el GIL degrada el loop

**Ficheros:** `backend/app/services/pdf.py:156-175,227-253,278-294` · `backend/app/services/documents.py:209`

**[EJECUTADO]** con un PDF de **una** página cuyo stream de contenido comprime 600 000 operadores `Tj` (70 KB en disco, 25 MB inflados, muy por debajo del tope de 75 MB de pypdf):

- `inspect_offloaded()` devuelve `PDF_ANALYSIS_TIMEOUT` a los 12,0 s.
- El hilo de `to_thread` **sigue vivo** y no había terminado a los 500 s cuando el script fue matado.
- Con 200 000 operadores (23 KB): 24,2 s y +275 MB de RSS. Con 100 000 ops × 5 páginas (13 KB): 6,1 s.
- Latencia del event loop (`await asyncio.sleep(0.005)`) con **dos** de esos hilos corriendo: mediana 15,5 ms, p95 41,8 ms, máximo 381 ms, frente a 5,2 / 5,2 / 6,1 ms en reposo. pypdf es Python puro: `to_thread` no libera el GIL, sólo reparte la penalización.

Por qué: el plazo se comprueba **antes** de cada página (`pdf.py:238-239`) y nunca dentro de `extract_text()`; los techos "declarados" (`/Count`, `/Size`) son valores que escribe el atacante; `_real_page_count` recorre el árbol real sin plazo.

**Escenario:** un `operator` sube en un solo lote 8 ficheros de 70 KB. Cada uno "falla" a los 12 s con un error limpio, y deja un hilo a 100 % de CPU durante más de 8 minutos. El pool por defecto de `to_thread` es `min(32, cpu+4)` = 8 hilos en 4 núcleos: a partir del octavo, **todo** `to_thread` del proceso espera (cada chunk de `LocalStorage.get_stream`, `put`, la comprobación de storage de `/health/ready`). El readiness falla su `wait_for(1.5 s)` → 503 → el healthcheck de Docker (5 × 15 s) reinicia el contenedor con las subidas en curso a medias. Mientras tanto el loop, compartiendo el GIL con 8 hilos, atiende a todas las empresas con latencias de cientos de milisegundos. Repetible cada 10 minutos por un usuario legítimo de rango mínimo. Memoria: ~1,3 KB por operador medidos → un fichero de 200 KB (≈1,7 M ops, aún bajo el tope de 75 MB inflados de pypdf) ≈ 2 GB por hilo **[extrapolado, no medido]**.

**Corrección:** mover el análisis al worker Dramatiq, como proponía la auditoría original: el `time_limit` del actor (10 min por defecto; ponerlo a 30 s) interrumpe de verdad, y el proceso del worker puede morir sin tirar la API. Si se mantiene en la API, usar un `ProcessPoolExecutor` con `kill` al vencer el plazo, no hilos. En cualquier caso: bajar el tope de descompresión de pypdf (`pypdf.Configuration`, hoy 75 MB) a unos 10 MB, rechazar antes de `extract_text` un `/Contents` cuyo tamaño comprimido supere N KB por página, y pasar un `visitor_operand_before` a `extract_text` que lance al vencer el plazo. Corregir el test `test_work_that_overruns_its_budget_fails_with_a_domain_error`, que sólo prueba el lado de la petición.

### N-03 · Alta · Un `site_admin` toma el control del `mm_admin` cambiándole la contraseña

**Ficheros:** `backend/app/routers/users.py:53-65,184-189,300-336`

**[LECTURA]** (requiere BD para ejecutar; no probado). Las tres reglas nuevas acotan **lo que se concede**; ninguna mira **quién es el objetivo**:

- `update_user` aplica `password` (`:323-324`) e `is_active` (`:320-322`) a cualquier usuario visible, y visible es "comparte un site conmigo" (`:53-65`).
- `_replace_memberships` (`:184-189`) rebaja el rol o borra la membresía de cualquier usuario en los sites que el actor administra, sin comparar con el rol que ese usuario tiene ahí.

**Escenario:**
1. Ana es `site_admin` del Site A. El administrador de la empresa, Boss, tiene una membresía en A con rol `mm_admin` (lo habitual: fue quien creó el site).
2. `GET /api/v1/users/` → Boss aparece (comparte A).
3. `PATCH /api/v1/users/{boss}` `{"password":"NuevaClave123456"}` → 200; `invalidate_user_sessions(boss)` le cierra la sesión a Boss.
4. `POST /api/v1/auth/login` como Boss → JWT `mm_admin` en todos los sites, `billing:manage` incluido. Es E-03 con un PATCH y un login, y además deja a Boss fuera.

Variantes: `{"is_active": false}` deja a la empresa sin administrador; `{"memberships":[{"site_id":A,"role":"operator"}]}` le quita a Boss el rol que le da el ámbito de empresa (`deps.py:173-174`), y ya nadie en la empresa puede volver a conceder `mm_admin`. Los tests de `test_user_admin_scope.py` sólo cubren concesiones.

**Corrección:** antes de aplicar `password`, `is_active` o `memberships`, exigir que **cada** membresía actual del objetivo en los sites que el actor administra sea ⊆ de lo que el actor tiene ahí (`scope.permissions_in(site)`), y que el objetivo no tenga rol de empresa salvo que el actor lo tenga (`company_wide`). Un `site_admin` administra a sus operadores y viewers, no a sus superiores ni a sus pares de otros sites. Registrar además el `actor_user_id` en el audit del cambio de contraseña (ya se hace) y avisar por email al afectado.

### N-04 · Alta · El guardarraíl SSRF se salta con una redirección HTTP

**Ficheros:** `backend/app/services/storage/s3.py:71-72,104-110` · `backend/app/services/storage/validation.py:52-87`

**[EJECUTADO]** Con dos servidores HTTP locales (uno que responde 307 hacia otro puerto, otro que registra lo que recibe), `S3Storage.health()` devolvió `True` y el segundo servidor recibió la petición `HEAD /probe`. aiobotocore no fija `allow_redirects` y aiohttp lo tiene a `True` por defecto (`aiohttp/client.py:549`). aiohttp sí retira `Authorization` al cambiar de origen (comprobado: llegó sin ella), así que ni las credenciales del inquilino ni las del host se exponen; lo que queda es una **SSRF ciega con oráculo** (`ok: true/false` según el destino final responda 2xx) hacia cualquier host y **cualquier puerto**: la lista blanca de puertos y la comprobación de dirección sólo se aplican a la URL inicial, no al destino de la redirección.

**Corrección:** la corrección estructural, que cierra a la vez N-04, N-05, N-09 y el rebinding DNS, es de red: una política de egreso en el contenedor `api` (y `worker`) que deniegue destinos en rangos privados, link-local y CGNAT. En código, además: pasar al cliente HTTP `allow_redirects=False` (aiobotocore lo permite a través de una sesión propia o de un `http_session_cls` personalizado) y tratar cualquier 3xx del endpoint como fallo de salud.

### N-05 · Alta · Backend FTP: `host`/`port` sin validar y sin timeout

**Ficheros:** `backend/app/services/storage/validation.py:113-124` · `backend/app/services/storage/ftp.py:26-27,37-46,83-89` · `backend/app/db.py:31-39`

**[EJECUTADO]** `validate_config("ftp", {"host": "169.254.169.254", "port": 80})` devuelve el diccionario intacto: sólo `s3` y `local` se validan, aunque E-01 nombraba explícitamente `host`/`port` de FTP. `FtpStorage.health()` contra una dirección que no responde seguía colgado a los 15 s (`aioftp.Client.context` se crea sin `socket_timeout` ni `connection_timeout`, cuyo defecto es `None`); contra un puerto cerrado devuelve `False` en 1 ms.

Consecuencia doble: un oráculo de conexión TCP hacia la red interna (abierto/filtrado frente a rechazado, por tiempo de respuesta) para cualquier usuario con `storage:manage`, y un **agotamiento del pool de Postgres**: `POST /storage/{id}/test` ya ha ejecutado `_get_backend` cuando llama a `health()`, así que la sesión mantiene su conexión hasta el `commit` final de `get_session`; con `pool_size=10, max_overflow=20`, treinta peticiones colgadas dejan a todas las empresas sin base de datos (el checkout del pool falla a los 30 s con 500).

**Corrección:** validar `host` con las mismas reglas que `endpoint_url` (sin lista blanca de puertos, o con 21/990); pasar `socket_timeout` y `connection_timeout` (10 s) a `aioftp.Client.context` y envolver `health()` en `asyncio.timeout`; y en `test_backend` liberar la sesión antes de la prueba de salud o no abrir transacción hasta después.

### N-06 · Media · `force_path_style` descarta los timeouts del cliente S3

**Fichero:** `backend/app/services/storage/s3.py:58-64`

**[EJECUTADO]** Sin `force_path_style`: `connect_timeout=5, read_timeout=30, retries={'max_attempts': 2}`. Con `force_path_style: true` (lo normal con MinIO/Garage): `connect_timeout=60, read_timeout=60, retries=None`, porque la línea 64 **sustituye** el `Config` en lugar de fusionarlo. El mismo efecto de retención de conexión que N-05, acotado a minutos por operación. **Corrección:** `_no_metadata_lookup().merge(_path_style_config())`, y renombrar la función: no desactiva la búsqueda de metadatos, sólo fija timeouts.

### N-07 · Media · El tope por fichero del multipart sólo se aplica tras volcar el cuerpo a disco

**Ficheros:** `backend/app/routers/documents.py:142-200` · `backend/app/services/documents.py:750-772` · `infra/traefik/dynamic/middlewares.yml:10-14`

**[LECTURA]** `MultiPartParser` limita con `max_part_size` únicamente las partes **sin** fichero (`starlette/formparsers.py:184-188`); cada parte con `filename` va a un `SpooledTemporaryFile` (`:230`) sin tope propio. El único tope durante la recepción es el global de 501 MB (`_max_upload_body_bytes`), así que una sola parte de 500 MB se escribe entera en el disco de la API antes de que `_read_upload` la rechace a los 5 MB. Traefik, con `memRequestBodyBytes: 1 MB` y `maxRequestBodyBytes: 600 MB`, hace lo mismo en **su** contenedor antes de reenviar. Ninguno de los dos acota el número de cuerpos simultáneos: `api-ratelimit` es 300/min y no hay `inFlightReq`. El disco que E-14 protegía sigue siendo alcanzable, ahora con un factor 600 MB × peticiones concurrentes en lugar de ilimitado por petición.

**Corrección:** un parser que corte cada parte con fichero a `max_upload_mb` (subclase de `MultiPartParser` contando en `on_part_data` cuando `self._current_part.file` no es `None`); bajar el `maxRequestBodyBytes` de Traefik al mismo 501 MB; añadir `inFlightReq` por IP al router de la API; y montar un `tmpfs` con tamaño en ambos contenedores para que el desbordamiento sea de esa petición y no del host.

### N-08 · Media · Resolución DNS síncrona en el event loop en cada uso de un backend S3

**Ficheros:** `backend/app/services/storage/validation.py:44-49,77-80` · `backend/app/services/storage/s3.py:56-60` · `backend/app/routers/public.py:125`

**[LECTURA]** `socket.getaddrinfo` es bloqueante y se llama desde corrutinas: en `create_backend`/`update_backend`, y en `S3Storage.__init__`, que se ejecuta en **cada** `build_adapter`, es decir, en cada subida, descarga, borrado y **cada escaneo público** de un documento archivado en S3 (`open_stream` → `build_adapter`). No hay caché. Un inquilino cuyo `endpoint_url` apunte a un nombre cuyo DNS autoritativo no responda bloquea el loop entero durante el timeout del resolver (glibc: 5 s × intentos × servidores) en cada una de esas peticiones; una caída del DNS local bloquea todo el proceso. No ejecutado: depende de la red.

**Corrección:** `await loop.getaddrinfo(...)` en un helper asíncrono; validar y resolver **una vez** al guardar, persistir la dirección resuelta junto al `endpoint_url` y conectar contra ella (lo que además cierra la ventana de rebinding), con una re-resolución periódica fuera del camino de la petición.

### N-09 · Media · `100.64.0.0/10` (CGNAT) pasa la validación

**Fichero:** `backend/app/services/storage/validation.py:32-41`

**[EJECUTADO]** `validate_endpoint_url("http://100.64.1.1")` devuelve la URL. `ipaddress.is_private` de Python 3.12 no incluye el rango CGNAT, y la auditoría original pedía rechazarlo explícitamente. Es el rango de metadatos de Alibaba Cloud (100.100.100.200) y de muchas redes de servicio (Tailscale, VPC internas). **Corrección:** añadir comprobación explícita contra `100.64.0.0/10`, `192.0.0.0/24` y `198.18.0.0/15`.

### N-10 · Baja · La lease del barrido no cubre una batch parcialmente aplicada

**Ficheros:** `backend/app/tasks/locks.py:60-91` · `backend/app/tasks/retention.py:24-49` · `backend/app/tasks/broker.py:26-39`

**[LECTURA]** El lock es correcto: `SET NX EX`, token de propiedad, liberación atómica por script Lua sólo si el token coincide, `finally` que libera también en excepción. El TTL de 15 min supera el `time_limit` por defecto de Dramatiq (10 min), que interrumpe el actor antes de que la lease expire, así que hoy no hay dos barridos concurrentes. Lo que queda: `run()` confirma la transacción **una vez al final** de la batch, y `_due_statement` no usa `FOR UPDATE SKIP LOCKED`. Un barrido interrumpido (time limit, reinicio del worker) ya ha borrado ficheros del storage cuyas filas no se han confirmado como retiradas; hasta el barrido siguiente, esos documentos responden `STORAGE_OBJECT_MISSING` (410) en el visor en lugar del 404 uniforme. Los borrados de storage son idempotentes, así que la noche siguiente lo cierra. **Corrección:** confirmar por documento (o por lotes pequeños) dentro de `apply_due`, y mantener `SWEEP_LOCK_TTL_SECONDS > time_limit` explícitamente documentado, o fijar `time_limit` en el actor.

### N-11 · Baja · `X-Request-ID` del cliente sin acotar

**Fichero:** `backend/app/main.py:50-58`

**[LECTURA]** Se acepta cualquier valor, sin límite de longitud ni formato, se devuelve en la respuesta y se escribe en todas las líneas de log de la petición. No hay inyección de líneas: uvicorn/h11 rechazan CR/LF en cabeceras y `JsonFormatter` escapa el valor (`logging.py:214`). Queda el relleno (hasta el límite de cabecera de uvicorn por línea) y la suplantación de correlación entre peticiones. **Corrección:** aceptar sólo `^[A-Za-z0-9._-]{1,64}$` y generar uno nuevo en caso contrario.

### N-12 · Baja · `logout` y `switch-site` fallan con 401 si la cookie de refresco ha caducado, sin borrarla

**Fichero:** `backend/app/routers/auth.py:194-198,223-227`

**[LECTURA]** `decode_token(cookie, expected_type=REFRESH)` lanza `TOKEN_EXPIRED`/`TOKEN_INVALID` **después** de poner el access token en la blacklist y **antes** de `clear_refresh_cookie`. El usuario queda con sesión revocada, un 401 en pantalla y una cookie muerta que el navegador seguirá enviando. En `switch_site` el efecto es un cierre de sesión inesperado. No es explotable; es un arreglo (la cookie) que rompe un flujo propio. **Corrección:** capturar `DomainError` alrededor del decode de la cookie en ambas rutas y limpiar la cookie igualmente.

### N-13 · Baja · `check_env.py` no vigila `ALLOW_PRIVATE_STORAGE_ENDPOINTS`

**Ficheros:** `backend/app/config.py:57-60` · `backend/app/services/storage/validation.py:74-75` · `scripts/check_env.py` · `.env.example`

**[LECTURA]** Con la opción activada la validación retorna **antes** de mirar la dirección: cualquier inquilino puede apuntar su S3 a `169.254.169.254:80`. La variable no aparece en `.env.example` ni la comprueba `check_env.py` para producción (grep vacío en ambos). **Corrección:** documentarla y que `check_env.py` la rechace en producción salvo un `--allow-private-storage` explícito.

### Verificado y correcto (no tocar)

- **Cookie de refresco** (`cookies.py`): `Path=/api/v1/auth` coincide con el prefijo que Traefik reenvía sin recortar (`PathPrefix(/api)`); `delete_cookie` usa el mismo `path`, así que el navegador sí la borra; `SameSite=strict` no afecta al `fetch` de la SPA porque el iniciador es el propio documento; `Origin: null` se rechaza (**[EJECUTADO]**); `Origin` vacío cae al `Referer` (irrelevante: ningún navegador lo envía así); no hay fijación de sesión (login sobreescribe, refresh rota y pone el anterior en la blacklist). Dos matices: la comparación con `PUBLIC_BASE_URL` es sensible a mayúsculas y a una ruta en la base (un `PUBLIC_BASE_URL` con path daría 403 a todos los refresh), y `login` no revoca el refresh token de una sesión previa capturada.
- **`client_ip`** y **E-12** como se ha detallado en la tabla.
- **`/health/ready`**: no es alcanzable desde fuera. Traefik enruta `/api` y `/v/` a la API y todo lo demás a nginx (`try_files … /index.html`), y el puerto 8000 no se publica; sólo el healthcheck de Docker lo consulta en `127.0.0.1`. El cuerpo, en cualquier caso, sólo dice `ok`/`failed` por comprobación.
- **Visor y `Accept`**: la negación `!HeaderRegexp(Accept, text/html)` sólo cambia qué servicio recibe la petición; no permite saltarse `viewer-ratelimit` (que tiene su propio problema, N-01).
- **Dedup de Stripe** y **lock de Redis**: correctos en lo que prometen.

---

## 3. Qué se ha ejecutado y qué no

**Ejecutado en `backend/.venv` (aislado, sin BD, sin Redis, sin red externa):**

- `validation.validate_endpoint_url` con 10 formas de dirección (IPv4-mapped, decimal, hex, `127.1`, `localhost`, NAT64, CGNAT, puerto fuera de lista) y `validate_base_path` con 6 rutas.
- `content_disposition` + `header_filename` con CR/LF, barra invertida y acentos.
- `client_ip` con `TRUSTED_PROXY_COUNT=1` y 5 cadenas `X-Forwarded-For`.
- `require_same_origin` con 9 combinaciones de `Origin`/`Referer`; `_cookie_path`.
- `reject_if_stale` con `iat` igual, justo menor y justo mayor que la marca; ida y vuelta de `create_token`/`decode_token` con `iat` fraccionario.
- `S3Storage.__init__` sin credenciales (rechaza) y con/sin `force_path_style` (timeouts).
- `S3Storage.health()` contra un endpoint local que redirige a otro puerto (la sigue).
- `FtpStorage.health()` contra una dirección que no responde (cuelga ≥15 s) y contra un puerto cerrado (1 ms); `validate_config("ftp", …)` (no valida).
- `pdf.inspect` / `inspect_offloaded` con PDFs de una y cinco páginas y streams comprimidos de 23 KB a 233 KB; medición de tiempo, RSS y latencia del event loop con dos hilos activos.

**Verificado por lectura de fuente de terceros:** Traefik v3.1 (`forwarded_header.go`, `ip/strategy.go`, `middlewares/extractor.go`), Go 1.22 (`net/http/httputil/reverseproxy.go`), Starlette 1.6 (`formparsers.py`), aiohttp (`client.py`), aioftp 0.28 (`client.py`), pypdf 6.19 (`filters.py`).

**No ejecutado:** ninguna petición contra la aplicación levantada ni contra Traefik; nada que requiera Postgres o Redis (N-03, E-08, E-20, N-10 son lectura); la resolución DNS lenta de N-08; la extrapolación de memoria de N-02 más allá de 275 MB medidos; y la condición de docker-proxy señalada en E-10, que es del entorno de despliegue.

---

## 4. Orden de trabajo sugerido

1. **N-01**: quitar `ipStrategy` de los dos rate limits y corregir test y comentarios. Es un cambio de cuatro líneas y hoy el login se puede cerrar desde fuera.
2. **N-03**: comprobar el rango del objetivo en `update_user` antes de contraseña, `is_active` y membresías.
3. **N-02**: llevar el análisis PDF al worker con `time_limit`, o a procesos con `kill`; bajar el tope de descompresión de pypdf.
4. **N-04, N-05, N-09, N-08**: política de egreso de red para `api` y `worker`, timeouts en FTP y validación de su `host`, `allow_redirects=False`, CGNAT, DNS asíncrono con resolución pinada.
5. **N-06, N-07** y el resto.
6. Los cuatro **NO ABORDADO** (E-16..E-19) siguen siendo bajos y pueden esperar; E-19 conviene cerrarlo antes de añadir códigos de error con parámetros nuevos, como ya se dijo.

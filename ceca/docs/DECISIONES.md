# Decisiones de arquitectura (ADR)

Cada decisión con consecuencias estructurales vive aquí, numerada y con estado. Una decisión
**Aceptada** no se revierte editándola: se escribe un ADR nuevo que la sustituya y el antiguo
pasa a **Sustituido por ADR-NNN**.

| ADR | Título | Estado |
|-----|--------|--------|
| [ADR-001](#adr-001-monolito-modular-en-vez-de-microservicios) | Monolito modular en vez de microservicios | Aceptado |
| [ADR-002](#adr-002-doble-vía-generar-o-subir-pdf-nativo-y-rechazo-del-escaneo) | Doble vía generar/subir PDF nativo, rechazo del escaneo | Aceptado |
| [ADR-003](#adr-003-aislamiento-por-fila-con-mm_id--site_id-en-un-solo-esquema) | Aislamiento por fila con `mm_id` + `site_id` | Aceptado |
| [ADR-004](#adr-004-el-token-del-qr-es-independiente-del-guid) | Token de share independiente del GUID | Aceptado |
| [ADR-005](#adr-005-facturación-desactivable-por-flag) | Facturación desactivable por flag | Aceptado |
| [ADR-006](#adr-006-el-catálogo-deca-vive-en-datos-no-en-código) | Catálogo DECA en datos, no en código | Aceptado |

---

## ADR-001: Monolito modular en vez de microservicios

**Estado:** Aceptado · 2026-09

### Contexto

Estampa la construye el mismo equipo que mantiene Meerkat, que arrancó partido en servicios.
La experiencia de Meerkat es concreta: la mayoría de las incidencias no venían de la lógica de
negocio sino de la coordinación entre servicios — transacciones repartidas, despliegues que
había que ordenar, un cambio de esquema que obligaba a tocar tres repositorios, y trazas que
se cortaban en el salto de red. El equipo es pequeño y el tráfico esperado es de decenas de
peticiones por segundo, no de miles.

### Decisión

Un solo proceso FastAPI con fronteras internas explícitas: `routers/` → `services/` →
`models/`, sin llamadas en sentido contrario, más un `worker` Dramatiq que ejecuta los mismos
módulos de `services/` fuera del ciclo de petición.

Los límites se mantienen por disciplina y por tests, no por red: `services/` no importa
`fastapi`, `models/` no importa `services/`, y el adaptador de almacenamiento no sabe qué es un
`Document`.

### Consecuencias

- Una transacción de base de datos cubre una operación de negocio entera. Sin sagas.
- Un despliegue, una migración, una traza.
- El escalado es horizontal por réplicas del proceso completo, no por servicio. Aceptable:
  el cuello de botella real es Postgres y el almacenamiento, no la CPU de la API.
- Si un módulo llegara a necesitar su propio ciclo de vida, las fronteras ya están donde
  habría que cortar. Extraerlo sería un trabajo acotado, y requeriría un ADR nuevo.

---

## ADR-002: Doble vía generar o subir PDF nativo, y rechazo del escaneo

**Estado:** Aceptado · 2026-09

### Contexto

La Resolución de 5 de junio de 2026 exige que el DeCA se genere por transformación de datos
estructurados en signos de escritura legibles, y que el QR vaya **dentro** del PDF apuntando a
una URL única por documento. Una foto o un escaneo no cumplen.

El mercado, en cambio, pide justo eso: "tengo el albarán en papel, ponme el QR". Vender eso como
cumplimiento sería vender una sanción.

### Decisión

Dos vías, ambas conformes, y una tercera explícitamente marcada como no conforme:

1. **Generar** (`origin = generated`): el usuario rellena los campos del art. 6, Estampa compone
   el PDF y le incrusta el QR. Vía recomendada.
2. **Subir PDF nativo** (`origin = uploaded_native`): el ERP del cliente ya emite un PDF con capa
   de texto. Se acepta, se valida contra el catálogo DECA y se le incrusta el QR.
3. **Escaneo** (`origin = uploaded_scanned`): un PDF sin capa de texto extraíble. Se **archiva**
   — el cliente quiere conservarlo — pero se marca `compliance_status = not_a_deca`, la interfaz
   lo advierte sin ambigüedad y `Document.is_valid_deca` devuelve `False` pase lo que pase.

La detección es técnica (presencia de capa de texto), no una casilla que marque el usuario.

### Consecuencias

- `origin` y `compliance_status` son dos campos distintos: de dónde viene y si vale.
- Nunca se "arregla" un escaneo añadiéndole metadatos. Para convertirlo en DeCA hay que
  regenerarlo por la vía 1.
- Las modificaciones siguen el apartado quinto de la Resolución: versionado inmutable con
  `supersedes_id` y `change_reason` obligatorio. Editar y sobrescribir no es una opción.

---

## ADR-003: Aislamiento por fila con `mm_id` + `site_id` en un solo esquema

**Estado:** Aceptado · 2026-09

### Contexto

El modelo es empresa (MM) → centro (site) → usuario. La alternativa clásica es un esquema de
Postgres por MM, que da aislamiento fuerte a costa de que cada migración se multiplique por el
número de clientes.

### Decisión

Un solo esquema. Toda tabla con ámbito hereda `TenantScoped`, que aporta `mm_id`, `site_id` y el
índice `(mm_id, site_id, created_at)`. Toda consulta pasa por `scoped_select(Model, ctx)`, y el
contexto sale **siempre** del JWT, nunca del cuerpo de la petición.

Las excepciones son tres y están cerradas: `users` por email en el login, `share_tokens` por
token en el visor público, y los catálogos globales (`plans`, `deca_field_definitions`).

### Consecuencias

- Una migración, no N. El coste de incorporar un cliente es una fila.
- El aislamiento depende del código, así que el código se verifica: `tests/test_tenant_isolation.py`
  recorre el AST de `services/` y `routers/` y falla si encuentra un `select(Modelo)` pelado o un
  `db.get(Modelo, ...)` contra una tabla con ámbito. Una excepción legítima se marca en la propia
  línea con `# tenant-exempt: <motivo>`, de modo que toda excepción es visible y revisable.
- Pedir un objeto de otro tenant devuelve **404, nunca 403**: un 403 confirmaría que existe.
- Si algún cliente exigiera aislamiento físico, la salida sería una instancia dedicada, no
  esquemas por cliente. Requeriría un ADR nuevo.

---

## ADR-004: El token del QR es independiente del GUID

**Estado:** Aceptado · 2026-09

### Contexto

El fichero se guarda con nombre GUID (`documents.id`) y el QR tiene que apuntar a una URL única
por documento. Lo cómodo sería publicar `/v/{document_id}`.

### Decisión

El QR publica `share_tokens.token`, un secreto aleatorio de 24 bytes url-safe que **no se deriva
del GUID**, con su propia caducidad y su propio `revoked_at`.

### Consecuencias

- Una etiqueta filtrada o mal impresa se revoca sin tocar el documento archivado.
- El identificador interno nunca sale al exterior, así que la superficie pública no revela ni
  volumen ni orden de creación.
- Un documento puede tener varios tokens a lo largo de su vida: reimprimir no obliga a reutilizar
  el secreto anterior.
- `/v/{token}` responde exactamente igual para un token inexistente, uno revocado y un documento
  retirado. Distinguirlos convertiría la URL en un oráculo de tokens válidos.

---

## ADR-005: Facturación desactivable por flag

**Estado:** Aceptado · 2026-09

### Contexto

La primera fase se despliega en instalaciones donde no se cobra: pruebas, piloto con un cliente,
y previsiblemente alguna instalación autogestionada. Meter Stripe en el camino crítico de la
subida de documentos habría hecho que una caída de Stripe parase el negocio de alguien.

### Decisión

`BILLING_ENABLED` (por defecto `false`). Apagado, las cuotas no se aplican, las suscripciones
quedan en `disabled` y los endpoints de facturación responden que la función no está activa. El
modelo de datos existe siempre: `plans`, `subscriptions` y `usage_counters` se siembran y se
mantienen aunque nadie cobre.

Encendido **sin** `STRIPE_SECRET_KEY` y `STRIPE_WEBHOOK_SECRET`, la aplicación **no arranca**:
`Settings.require_billing_config()` revienta en el arranque, y `scripts/check_env.py` lo detecta
antes, en el despliegue.

### Consecuencias

- Fallo ruidoso y temprano, en vez de un cliente que descubre que no se le cobra.
- Los contadores de uso se llevan siempre, así que activar la facturación no empieza de cero.
- Stripe es un detalle de implementación detrás de `services/billing.py`, no un acoplamiento del
  dominio.

---

## ADR-006: El catálogo DECA vive en datos, no en código

**Estado:** Aceptado · 2026-09

### Contexto

Qué campos debe llevar un albarán es una pregunta **jurídica**, y su respuesta cambia: el art. 6
de la Orden FOM/2861/2012 ya ha sido modificado por la Orden TRM/282/2026, y `docs/DECA.md`
documenta que hay campos cuya exigibilidad no está contrastada. Un `if campo == "matricula"`
repartido por el código convierte cada cambio normativo en un despliegue de urgencia.

### Decisión

El catálogo vive en `app/i18n/deca_fields.json` y se siembra en `deca_field_definitions` mediante
una migración de datos idempotente (`0003_seed_deca_fields.py`, que **lee el JSON**, no lo
duplica). `DecaValidator` se construye leyendo la tabla. Cada documento guarda el
`deca_catalog_version` con el que se validó.

### Consecuencias

- Añadir un campo es editar el JSON, subir `catalog_version` y añadir una migración de datos.
  Cero cambios de lógica.
- Un documento validado con la versión 1 sigue siendo auditable cuando exista la versión 2: se
  sabe con qué reglas se aceptó.
- El frontend pinta el formulario desde la API. No hay lista de campos duplicada en TypeScript.
- Mismo criterio para los demás catálogos: planes, tipos de almacenamiento, estados.

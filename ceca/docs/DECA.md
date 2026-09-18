# DeCA — Documento electrónico de Control Administrativo

> **Estado de la verificación.** Lo que sigue se recopiló desde resúmenes de páginas oficiales
> (boe.es, transportes.gob.es). El entorno de desarrollo tiene bloqueado el acceso directo a
> `boe.es`, así que **ningún artículo está transcrito literalmente**. Cada punto lleva su nivel
> de confianza. Antes de usar esto en material comercial o en una auditoría, hay que contrastar
> los consolidados enlazados al final. Lo marcado como "no verificado" no se ha comprobado.

## 1. Qué es

**DeCA = Documento electrónico de Control Administrativo.** Es el documento de control del
**transporte público de mercancías por carretera**, que ya existía en papel desde la Orden
FOM/2861/2012 y que pasa a ser **exclusivamente electrónico el 5 de octubre de 2026** para el
transporte **interior**. Se formaliza **por cada envío**.

No es un registro público: **no hay ninguna sede donde "dar de alta" el albarán**. Es
documentación propia de la empresa, generada antes del transporte, verificable online mediante
un QR y conservada durante un plazo mínimo.

### Relación con el albarán

El documento de control es de **libre edición**: modelo, formato y denominación libres. Por eso
**un albarán puede hacer de DeCA**, siempre que lleve todos los datos del artículo 6 e
identifique de forma **expresa y diferenciada** al cargador contractual y al transportista
efectivo.

### Las dos consecuencias que condicionan este producto

1. **El PDF debe ser nativo**, generado por transformación de datos estructurados en signos de
   escritura legibles. **Una foto o un escaneo no cumplen.** Un flujo de "sube tu albarán
   escaneado y te pongo un QR" **no produce un DeCA válido**.
2. **El QR va embebido dentro del PDF** y apunta a una **URL única por documento**, consultable
   online. El agente en carretera la abre desde su móvil.

Cómo lo resuelve Estampa: ver ADR-002 en `DECISIONES.md`. En corto, dos vías — generar el PDF
desde los datos (vía conforme) o admitir un PDF nativo ya emitido por el ERP del cliente — y
rechazo explícito de los escaneos.

## 2. Normas

| Norma | Rol | URL |
|-------|-----|-----|
| Resolución de 5 de junio de 2026, DG Transporte por Carretera y Ferrocarril (BOE-A-2026-12784) | Norma técnica: formato, QR, URL, conservación | <https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-12784> |
| Orden FOM/2861/2012 (BOE-A-2013-154) | Define los campos obligatorios (art. 6) y los sujetos obligados (art. 4) | <https://www.boe.es/buscar/act.php?id=BOE-A-2013-154> |
| Ley 9/2025 de Movilidad Sostenible (BOE-A-2025-24545) | D.T. 8.ª: obliga a digitalizar en 10 meses | <https://www.boe.es/buscar/doc.php?id=BOE-A-2025-24545> |
| RD 1211/1990 (ROTT), art. 222 | Obligación de llevar el documento a bordo | <https://www.boe.es/buscar/act.php?id=BOE-A-1990-24442> |
| Ley 16/1987 (LOTT), art. 141.17 | Régimen sancionador | <https://www.boe.es/buscar/act.php?id=BOE-A-1987-17803> |
| Orden TRM/282/2026 (BOE-A-2026-7128) | Modifica la FOM/2861/2012 | <https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-7128> |

Páginas del Ministerio: [DeCA](https://www.transportes.gob.es/transporte-terrestre/profesionales-transporte/servicios-transportista/documento-electronico-control-administrativo-deca)
· [FAQ](https://www.transportes.gob.es/transporte-terrestre/profesionales-transporte/servicios-transportista/documento-electronico-control-administrativo-deca/preguntas-frecuentes-faq-deca)

La Resolución de 2026 **no crea campos nuevos**: remite al art. 6 de la Orden FOM/2861/2012.

## 3. Campos obligatorios (art. 6 Orden FOM/2861/2012)

Estos son los `code` que siembra `backend/app/i18n/deca_fields.json`.

| Código | Campo | Oblig. | Validación | Artículo | Confianza |
|--------|-------|--------|-----------|----------|-----------|
| `cargador_nombre` | Nombre o razón social del cargador contractual | Sí | Texto | 6.a | Alta |
| `cargador_nif` | NIF del cargador contractual | Sí | NIF/CIF con dígito de control | 6.a | Alta |
| `cargador_domicilio` | Domicilio del cargador contractual | Sí | Dirección postal | 6.a | Alta |
| `transportista_nombre` | Nombre o razón social del transportista efectivo | Sí | Texto | 6.b | Alta |
| `transportista_nif` | NIF del transportista efectivo | Sí | NIF/CIF con dígito de control | 6.b | Alta |
| `origen` | Lugar de origen del envío | Sí | Texto | 6.c | Alta |
| `destino` | Lugar de destino del envío | Sí | Texto | 6.c | Alta |
| `mercancia_naturaleza` | Naturaleza de la mercancía | Sí | Texto | 6.d | Alta |
| `mercancia_peso` | Peso de la mercancía | Sí | Decimal > 0 | 6.d | Alta |
| `mercancia_peso_unidad` | Unidad del peso | Sí | `kg` \| `t` | 6.d | Alta |
| `fecha_transporte` | Fecha de realización del transporte | Sí | Fecha | 6.e | Alta |
| `matricula_vehiculo` | Matrícula del vehículo | Sí | Matrícula ES/UE | 6.f | Alta |
| `observaciones` | Observaciones o reservas de las partes | No | Texto libre | 6.g | **Media — una sola fuente** |

**Requisito transversal.** Cargador contractual y transportista efectivo se identifican
**siempre de forma expresa y diferenciada**. En la UI son dos bloques separados y etiquetados,
nunca un genérico "cliente" / "proveedor".

**No verificado:** si el art. 6 termina en f), g) o más allá. Aparecieron menciones sueltas a
"número de bultos" y "distancia" que no se pudieron situar. Si al contrastar el consolidado
aparecen más campos, se añaden al JSON y se sube `catalog_version`. Nada de tocar código.

## 4. Requisitos técnicos del fichero (Resolución 5/06/2026)

| Requisito | Detalle | Confianza |
|-----------|---------|-----------|
| Formato | PDF | Alta |
| Tamaño máximo | **5 MB** por fichero | Alta |
| Generación | Digital nativa, desde datos estructurados. **No foto ni escaneo** | Alta |
| QR | **Embebido en el PDF**, contiene la URL única del documento | Alta |
| URL | Única y específica por documento, consultable online | Alta |
| Entrega | Al conductor **antes del inicio efectivo del servicio** | Alta |
| Control en carretera | El conductor presenta el DeCA con el QR o, en su defecto, solo el QR | Alta |

## 5. Modificaciones (apartado quinto de la Resolución)

Solo hay dos vías válidas. Confianza media-alta.

| Vía | Mecanismo | URL / QR |
|-----|-----------|----------|
| A. Modificar el fichero | Se añaden los datos nuevos, se hace constar el **motivo del cambio** y los datos antiguos **se conservan marcados como no válidos** | Se mantienen |
| B. Fichero nuevo | Nuevo fichero completo; **se conserva el original** | URL y QR nuevos |

Consecuencia de producto: **versionado inmutable**, campo obligatorio "motivo de modificación"
y marcado visual de los datos anulados. Editar y sobrescribir no es una opción.

## 6. Conservación y plazos

| Concepto | Plazo | Confianza |
|----------|-------|-----------|
| Conservación de los ficheros | **Mínimo 1 año**, cargador contractual y transportista efectivo | Alta |
| A disposición de | Inspección de Transporte Terrestre | Alta |
| Generación | Antes del inicio efectivo del servicio | Alta |
| Formalización | Por cada envío | Alta |
| Obligatoriedad del formato electrónico | **5 de octubre de 2026**, transporte interior | Alta |

**No existe plazo de "registro tras la operación"**: no hay registro centralizado.

El valor por defecto de Estampa es **365 días** (el mínimo legal), configurable por site. Se
recomienda subirlo por prudencia probatoria; la UI lo advierte al dejarlo en el mínimo.

## 7. Sujetos obligados

- **Transportista efectivo**: titular de la autorización al amparo de la cual se realiza
  materialmente el transporte.
- **Cargador contractual**: quien contrata directamente con el transportista efectivo. Puede
  ser el cargador efectivo u otro transportista, cooperativa, agencia de transporte,
  transitario, almacenista-distribuidor u operador logístico.

Ambos son responsables de formalizarlo. Se emiten dos ejemplares, uno para cada uno.

**Exclusiones (art. 2, lista parcial, confianza media):** transportes sin título habilitante
preceptivo; paquetería y similares con reducido número de bultos manipulables por una persona.

**Ámbito:** interior. En internacional el eCMR **no** es obligatorio.

## 8. Sanciones

Tipo infractor: **LOTT art. 141.17**, "carencia, falta de diligenciado o falta de datos
esenciales de la documentación de control (…) cuya cumplimentación resulte obligatoria".
Rangos vistos: 401–600 € y 801–1.000 € según el punto del art. 141.

> **Confianza baja-media en las cuantías.** El tipo está identificado; la cuantía exacta y su
> posible degradación por el art. 142 no se pudieron confirmar. **No publicar cifras en
> material comercial sin contrastar los arts. 140–143 LOTT.**
>
> **No verificado:** no se encontró en el BOE un tipo infractor nuevo y específico por
> incumplir el formato electrónico. Que llevarlo solo en papel desde el 5/10/2026 sea
> sancionable es una lectura razonable del art. 141.17, pero es interpretación.

## 9. Pendiente de contrastar

1. Resolución consolidada: <https://www.boe.es/buscar/pdf/2026/BOE-A-2026-12784-consolidado.pdf>
2. Orden FOM/2861/2012 consolidada, art. 6 completo: <https://www.boe.es/buscar/pdf/2013/BOE-A-2013-154-consolidado.pdf>
3. Código del Transporte de Mercancías por Carretera: <https://www.boe.es/biblioteca_juridica/codigos/abrir_pdf.php?fich=327_Codigo_del_Transporte_de_Mercancias_por_Carretera.pdf>
4. FAQ del Ministerio, para dudas de implementación.

Si se dejan esos PDF en `docs/fuentes/`, se pueden contrastar campo a campo sin depender de la red.

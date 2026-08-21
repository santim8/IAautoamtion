# Flujo actual de Solicitud de Cupo — pantallas y servicios

Trazado con evidencia real: `evidences/login-credito_2026-08-21_130658/` (caso **aprobado en firme**, CC 1032410060, idCaso **298672**, 2026-08-21). Es la **línea base sobre la que se va a injertar Gestión Documental** ([project_gestion_documental_zona_gris.md](project_gestion_documental_zona_gris.md)).

Host de servicios: `https://platform-test-external.colsubsidio.com`
Host del front: `https://dev.colsubsidio.com/creditos/solicitud/...`

---

## Mapa pantalla → servicio

| # | Ruta | Stepper | Servicios (en orden) |
|---|---|---|---|
| 0 | `/solicitud/login` | — | ninguno |
| 1 | `/cupo-de-credito/validaciones` | — | `POST /loans/eligibility/external/v2/affiliation-validations` (SAP-AFILIACIONES) · `POST /loans/eligibility/external/v1/card-validations` (ASCARD-TMS-CUPO) · `POST /loans/eligibility/external/v1/product-validations` (SIIF-OBLIGACIONES) |
| 2 | `/cupo-de-credito/politicas` | — | `POST /loans/req-mgr/external/v1/product/2/request/validate-request` → **crea el caso** · `GET /loans/eligibility/external/v1/campaigns/{tipo}/{doc}` |
| 3 | `/cupo-de-credito/informacion-personal` | **Paso 1 de 4** · Información personal | `POST /loans/req-mgr/external/v1/product/2/request/request-data` → `guardarDatosPersona` |
| 4 | `/cupo-de-credito/personalizacion-oferta` | **Paso 2 de 4** · Personalización de la solicitud | `POST .../request/decision-engine/start` → responde `iniciarBiometria` · `GET /loans/loan-offer/external/v1/product/2/request/offer/{idCaso}` · `POST /loans/loan-util/external/modification-quota-amount` |
| 5 | `/cupo-de-credito/datos-adicionales` | **Paso 3 de 4** · Datos finales | `POST .../request/offer-config` → `configurarOferta` |
| 6 | `/cupo-de-credito/biometria` | Paso 4 de 4 | **0 requests capturables** (proveedor externo en iframe) |
| 7 | `/cupo-de-credito/fin` | — | 0 requests |

**Microservicios:** `loans/eligibility` (validaciones + campañas) · `loans/req-mgr` (orquestador del caso, `product/2`) · `loans/loan-offer` (oferta) · `loans/loan-util` (recálculo de cupo).

**Pantallas (contenido real):**
- **Paso 1** — "¿Cómo podemos contactarte?": celular + confirmación, celular secundario (opcional), correo + confirmación. Encima, modal de bienvenida "¡Hola {nombre}, tienes un aprobado!" con `Cupo máximo aprobado` = `MONTO` de la campaña y la fecha de `FECHA_VIGENCIA`.
- **Paso 2** — "¡Felicidades {nombre}, este es el cupo aprobado para tu solicitud!": cupo, cuota de manejo, seguros, y dos opciones de pago (CUOTA_FIJA / CUOTA_VARIABLE) con tasas. CTA `Aceptar el Cupo de Crédito`.
- **Paso 3** — "Cuéntanos si aplicas para alguno de estos casos": 3 preguntas SARLAFT (recursos públicos, poder político, reconocimiento público).

---

## Datos clave que ya viajan en el contrato

### 1. `GESTION_DOCUMENTAL` ya existe

Llega en la campaña y el front lo reenvía a Bizagi. **La tubería ya está construida.**

```
GET /eligibility/external/v1/campaigns/1/{doc}
→ campanas[0]: { SUBPRODUCTO: 54, TIPO_CAMPANA: 2, CODIGO_CAMPANA: 750,
                 NOMBRE_CAMPANA: "Oferta en firme prueba 20261213",
                 MONTO: 2250000, FECHA_VIGENCIA: "20261206",
                 GESTION_DOCUMENTAL: 2 }

POST .../request/request-data
→ informacionCampanas: { gestionDocumental: "2", fechaVigencia: "2026-12-06", monto: "2250000" }
```

⚠️ Es un atributo **de la campaña**, resuelto **antes** del motor de decisión. No es necesariamente lo mismo que el veredicto Zona Gris de uFlow (pregunta abierta 1.1). **Falta confirmar qué significa el valor `2`**: este caso es aprobado en firme y pasó de largo sin carga documental.

### 2. `tipoTrabajador` llega de SAP pero está enterrado

Está en `affiliation-validations` → `resultadoValidacion.datosSinProcesar` — que es un **JSON serializado como string** — en `afiliado.afiliacion.tipoTrabajador`. Valor real observado: **`ZTRA`**.

**No está en `datosAdicionales`** (la parte ya procesada), donde solo hay `tipoAfiliacion: "D"`. Por eso el backlog tiene tareas [FE] y [BE] de "Captura de dato tipo de trabajador": el trabajo real es **promoverlo a campo de primer nivel**.

🔴 **Impacto en pruebas:** SAP retorna **códigos** (`ZTRA`), no `Dependiente`/`Independiente`/`Pensionado`. Los casos TC001-TC003 de [project_hu217172_pantalla_ingresos.md](project_hu217172_pantalla_ingresos.md) dicen *"SAP retorna el campo Tipo trabajador con el valor 'Dependiente'"* — **eso no es lo que retorna SAP**. Falta la tabla de mapeo código→perfil, y sin ella la pregunta abierta 2.1 (tipo de trabajador no parametrizado) no se puede cerrar.

### 3. `datosFinancieros` ya existe, en null

```
datosPersona.datosFinancieros: { salario: null, otrosIngresosLaborales: null, ingresosAdicionales: null }
```

Mapean 1:1 a los tres primeros campos de la pantalla de ingresos: `salario` → *Salario básico mensual* (item 8) · `otrosIngresosLaborales` → *Ingresos adicionales en tu trabajo* (item 9) · `ingresosAdicionales` → *Ingresos mensuales adicionales* (item 12).

**No hay campo para `Tipo de actividad` ni `Origen específico del ingreso`** — y el origen es justamente el que alimenta el cruce de la matriz de documentos. El contrato de `request-data` **tiene que extenderse**.

### 4. SAP ya trae el salario

En el mismo blob: `salario: "2450000"`, `salarioOtros: "0"`, `tipoSalario: "02"`, `categoria: "A"`, `grupo: "ZGRP"`.
❓ **Pregunta nueva:** ¿la pantalla de ingresos **prellena** el salario básico con este valor o el usuario lo digita libre? Cambia los casos de prueba (editable, validación contra SAP, discrepancias).

### 5. Estado Civil ya se envía en null

SAP lo trae (`estadoCivil: "1"`) pero el front manda `datosPersonales.estadoCivil: null`. **La eliminación del campo ya está hecha en este flujo**; queda verificar novedades.

### 6. Motor y biometría se disparan juntos

`POST .../request/decision-engine/start` responde con la clave **`iniciarBiometria`**. Arrancar el motor y arrancar la biometría son el mismo disparo.

---

## Dónde se injerta Gestión Documental

- **Caso 1 (el motor manda a Zona Gris):** entre el Paso 1 (información personal) y el Paso 2 (personalización de oferta). La pantalla de ingresos es una **extensión del Paso 1**, y tras el motor el flujo se desvía a carga documental en vez de a la oferta.
- **Caso 2 (aprobado en firme con soportes):** en el Paso 2, sobre la pantalla "¡Felicidades…!" junto al CTA `Aceptar el Cupo de Crédito`. Esa pantalla **ya permite modificar el monto hacia abajo** vía `modification-quota-amount` (observado: 1.500.000 → 1.000.000, devuelve `cuotaFija: 50000`). Caso 2 es pedir **hacia arriba**, que ese endpoint hoy no cubre.
- ❓ **Pregunta nueva:** el stepper hoy es de **4 pasos**. Gestión Documental agrega pantallas. ¿Pasa a 5, o la carga documental reemplaza pasos existentes? Ningún insumo lo define, y los mockups muestran "Paso 1 de 4".

---

## Hallazgo de la corrida

La pantalla `/fin` terminó en **"Application error: a client-side exception has occurred"**, en dos capturas separadas por 3 minutos. El resumen del reporte dice *"0 con status ≥ 400"* porque fue excepción de cliente, no HTTP: **el flujo no cerró bien aunque el reporte lo dé por limpio**. Relevante porque la Thank You Page de Zona Gris es una variante de esa misma pantalla.

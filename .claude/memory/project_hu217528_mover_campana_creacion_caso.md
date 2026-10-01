# HU 217528 — Mover consulta y enviar tipo de campaña en creación de caso

Backend puro (sin Frontend), tag `Gestión_Documental`. Parte de Feature 198568 "Back - Gestión Documental" → Epic 151684 "Ecosistema Digital fase 2". Ver [project_gestion_documental_zona_gris.md](project_gestion_documental_zona_gris.md) para el contexto de negocio completo (por qué existe el Feature, alcance de producto).

## Estado (fuente: Sprint Review 34, 22 sep 2026)

**Desarrollo 100% Finalizada.** Roadmap por sprint: Diseño SP30-32 · Desarrollo SP32-33 · Pruebas Internas SP33-34 · **Pruebas UAT SP35** (23 sep - 6 oct) · Despliegue a producción **TBD** (ver "Despliegue C" más abajo). El deck aclara que el cambio aplica **entre el sistema autogestionado Y asistido**, no solo autogestionado. Tiene un Video Demo embebido en el pptx de la review (no extraído como texto).

## HU 221404 — gemelo técnico del lado Bizagi/Gattaca (investigado 2026-09-22)

Parent **Feature 175846** "Aceptación de Preaprobado y Oferta en firme en flujo Autogestionado y Asistido" (Gattaca) — **no** el 198568 de Gestión Documental (Globant). Mismo contenido técnico que 217528 (mismos endpoints Bizagi `/start` Novedades+Activación y `/performSearch`), pero con **4 XPaths, uno más de los que traía 217528**:
- `sNombreProductoCampania` (ej. "CUPO") — **nuevo, no estaba en la lista de 217528**
- `sGestionDocumental`, `cMonto`, `dVigenciaOferta` — los 3 ya conocidos

Todo indica que 217528 (Globant, capa de servicio/orquestación) y 221404 (Gattaca, configuración OData de Bizagi) son **dos tickets del mismo cambio real**, repartidos por quién lo implementa. Mismo objetivo de despliegue (Sprint 35).

### Resuelve el punto gris original: "no hay campo explícito de tipo de campaña"

**No existe un campo separado.** El valor de `sGestionDocumental` ES la clasificación — regla exacta (viene de la HU hermana 192150, que reusa las mismas reglas del autogestionado):

| Condición (todas deben cumplirse) | Clasificación |
|---|---|
| Estado Campaña=1 (vigente) + **Gestión Documental=1** + Vigencia≥hoy + Tipo Campaña=2 (cupo) | **Preaprobado** |
| Estado Campaña=1 (vigente) + **Gestión Documental=2** + Vigencia≥hoy + Tipo Campaña=2 (cupo) | **Oferta en Firme** |
| Cumple ambas | Firme prevalece |
| Ninguna | Sin campaña, flujo normal (no se asocia dato de campaña) |

Coincide con la evidencia ya revisada: en `login-credito_2026-09-22_110412/reporte.html`, la campaña "Preaprobado cupo 2026 pruebas" traía `GESTION_DOCUMENTAL: 1` — cuadra exacto con la tabla.

**Mecanismo Bizagi exacto:** la regla se traslada del evento `EvRecibirInfoAdGC` (equivalente Bizagi de `/request-data`) al evento de inicio `GCE_Set_CampaniaAutoGestionado`. **Durante desarrollo/pruebas los atributos se mantienen opcionales en `EvRecibirInfoAdGC`** — el camino viejo convive con el nuevo temporalmente, se elimina después de estabilizar. No extrañarse si ambos caminos aceptan el dato por ahora.

**221404 trae acceptance criteria mucho más testeables** que los de 217528 (Given/When/Then concreto para Firme / Preaprobado / Sin oferta) — usar estos como base al diseñar test cases en vez de los originales de 217528.

**Reportes/consultas Bizagi afectados:** `GCR_Solicitudes - Promotor` y `GCR_Solicitudes - Analista Operativo` mostrarán la marcación desde el inicio del caso.

## HU 192150 — NO es lo mismo, es aparte (investigado 2026-09-22)

Parent también Feature 175846, pero es una funcionalidad **distinta**: solo canal **Asistido**, consulta el servicio de campañas justo al crear el caso y clasifica internamente (mismas reglas de la tabla de arriba) **únicamente para reportería/funnel** — explícito en la HU: "El proceso no mostrará al promotor el resultado... sin modificar el comportamiento funcional del flujo." Objetivo: poder identificar el origen-campaña de clientes que abandonan el flujo antes de las etapas donde hoy se registra. **No toca XPaths de Bizagi ni el endpoint de creación** — no confundir con 221404.

## Qué cambia (mecanismo exacto, confirmado por el plan de despliegue "Despliegue C")

**Antes:** los 3 XPaths de campaña (monto, vigencia de oferta, gestión documental) se enviaban en el endpoint que recibe la **información personal** del usuario (`/request-data`, junto con `contacto`/`estadoCivil`/`datosFinancieros`).

**Después:** se mueven al endpoint de **creación de caso** (`/validate-request`, donde nace `idCaso`), dentro de `informacionCampanas: {gestionDocumental, fechaVigencia, monto}`. Objetivo declarado: "mayor trazabilidad de los casos relacionados a campañas".

Mapeo XPath ↔ campo del request:
- `sGestionDocumental` → `informacionCampanas.gestionDocumental`
- `cMonto` → `informacionCampanas.monto`
- `dVigenciaOferta` → `informacionCampanas.fechaVigencia`

## Regla funcional

| Tipo de campaña | Qué conserva el sistema |
|---|---|
| Aprobado en Firme | Solo información de contacto |
| Preaprobado | Contacto + estado civil + datos financieros |

4 escenarios de aceptación: envío de XPaths en creación (Novedades y Activación), mapeo correcto en Bizagi, exposición en `performSearch`, conservación de datos según tipo de campaña.

## Evidencia ya revisada

`evidences/login-credito_2026-09-22_110412/reporte.html` (contra CERT, `platform-test-external`) ya muestra el comportamiento **nuevo**: paso 2 (`/validate-request`) envía `informacionCampanas` completo y crea el caso; paso 3 (`/request-data`) envía contacto+civil+financieros para una campaña Preaprobado (TIPO_CAMPANA 2). Cubre bien Escenario 3 y parcialmente Escenario 2, pero solo rama Preaprobado + proceso Activación (`noveltyType: "1"` = Originación). Sin cobertura de: Aprobado en Firme, proceso Novedades, ni `performSearch` (Escenario 4 — no aparece en absoluto en el reporte).

## Despliegue a producción — "Despliegue C - TBD"

Estado: **PENDING**, fecha TBD (aún no se ha desplegado a prod; CERT ya tiene el cambio).

- **Componentes:** Drupal, `app-cre-loans-request-manager-api` (backend — es el `req-mgr` del diagrama de arquitectura, ver [[reference_arquitectura_aws_gcp_plataforma_credito]] en la memoria global), `app-cre-solicitud` (Frontend).
- **Requiere ventana de mantenimiento:** se inhabilita el canal autogestionado en Drupal (`platform-prod-external.colsubsidio.com/loans-prod-admin-solicitud` → tipo de contenido "Configuraciones canal autogestionado" → checkbox "Activar ventana de mantenimiento") antes del despliegue, se reactiva después de pruebas.
- **Orden:** Paso 1 mantenimiento ON → Paso 2 Backend → Paso 3 Frontend → Paso 4 pruebas (quitando mantenimiento) → Paso 5 rollback si aplica (mantenimiento ON → rollback BE+FE → mantenimiento OFF → ratificación).
- **Punto a confirmar, no asumido:** la HU dice "Fuera del alcance: Frontend" (sin cambios de código/diseño), pero el plan SÍ incluye un paso de despliegue de `app-cre-solicitud`. Puede ser solo redeploy de versión sin cambio funcional — no verificado.

## Puntos grises — estado actualizado

- ~~El título menciona "enviar tipo de campaña" pero ningún campo explícito aparece~~ → **RESUELTO por HU 221404/192150**: `sGestionDocumental` (valor 1/2) es la clasificación, no existe campo separado. Ver tabla arriba.
- Escenarios 1 y 2 del acceptance criteria de 217528 son de bajo nivel de testabilidad → **usar los de 221404 en su lugar**, son concretos.
- Caso "ninguna condición cumple" (ni Firme ni Preaprobado) → **cubierto por 221404 Escenario 3**: no se asocia dato de campaña, flujo normal.
- Sigue sin resolver: la posible contradicción entre 217528 (dice conservar "estado civil" para Preaprobado) y HU 211912 (elimina la pantalla de Estado Civil) — ninguna de las HUs de campaña (221404/192150) menciona estado civil, así que no ayudan a resolver esa duda.

**Why:** esta HU se investigó a fondo cruzando HU + evidencia de flujo + diagrama de arquitectura + plan de despliegue; consolidarlo evita rehacer esa cadena de razonamiento en cada sesión nueva.
**How to apply:** antes de diseñar/ejecutar test cases para esta HU, partir de aquí en vez de releer la HU desde cero — ya está el mapeo XPath↔campo, la evidencia parcial existente y lo que falta cubrir (Firme, Novedades, performSearch).

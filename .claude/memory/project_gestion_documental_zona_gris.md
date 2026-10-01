# Gestión Documental · Zona Gris (contexto funcional)

**Zona Gris** = instancia de validación adicional (Mesa de Control) donde el afiliado carga soporte documental que certifique sus **ingresos adicionales**. Piloto: **Solicitud de cupo** (y sus variantes Aumentos y Reactivaciones), pero la solución debe ser **paramétrica** para los demás productos de crédito futuros.

## Jerarquía en Azure DevOps y alcance de producto

Epic 151684 "Ecosistema Digital fase 2" → Feature 198568 "Back - Gestión Documental" → de ahí cuelgan las HU (ej. PBI 217528 "Mover consulta y enviar tipo de campaña en creación de caso", 217172 "Formulario de ingresos", 217175 "Formulario de carga de archivos", etc.) y sus tareas [BE]/[FE]/[QC]/[DR]/[UI].

**Por qué existe el Feature** (contexto textual de 198568): hoy no hay proceso de gestión documental para solicitudes Aprobadas/Negadas/Zona Gris automáticas, ni forma de bifurcar cuando el motor manda a Zona Gris o el afiliado no acepta la oferta, ni carga de documentos (autogestionado/asistido), ni revisión (manual hoy, se busca semi-automatizar con IA), ni auditoría, custodia definitiva o reportes/taggeo.

**¿Conecta con Libre Inversión? Verificado en Azure DevOps (2026-09-22): NO, todavía no.** De 107 work items con tag `Gestión_Documental` (todos en rango reciente 214xxx-227xxx), ninguno menciona Libre Inversión — todos son de Cupo de Crédito (+ Aumentos/Reactivaciones/Novedades). Los 141 work items que sí mencionan "Libre Inversión" en el título son todos de rango antiguo (68xxx-90xxx) y no tienen el tag `Gestión_Documental`. Coincide con lo ya anotado arriba: el piloto es solo Cupo de Crédito, Libre Inversión queda como candidato a extensión **futura**, no trabajo actual. **Matiz (tablero draw.io, 2026-09-23):** sí hay un punto de contacto ya en el plan: el tablero de Libre Inversión incluye la HU 227148 (derivación de Zona Gris a asistido) y su HU 227147 lleva "Redirección a asistido por zona gris" + casuística DR y la tarea de PO "Definición de documentos de Consumo". Libre Inversión reutiliza la derivación temporal a asistido; lo que sigue sin compartir es la carga documental autogestionada. Detalle en la memoria global `project_consumo_libre_inversion_libranza`. Confirmado también en el deck de Sprint Review 34 (22 sep): Libre Inversión está en "plan de choque" de refinamiento aparte (iniciando por Libre Inversión y Compra Cartera), "pendiente socialización de flujo al equipo desarrollo para taskeo y estimación" — ni siquiera tiene backlog de desarrollo estimado todavía.

## Línea de tiempo oficial de los Casos (fuente: Sprint Review 34, slide "Arquitectura de Casos", 22 sep 2026)

**Corrige la impresión de que Caso 1 y Caso 2 son trabajo cercano en el tiempo — NO lo son.** Solo Caso 1 es 2026; todo el resto es 2027:

| Caso | Detonante (redacción oficial) | Formulario | Año |
|---|---|---|---|
| **Caso 1** — Motor a Zona Gris | El motor no otorga oferta automática **o la envía a validación interna** | Largo: Contacto, Canal preferido, Perfilamiento de ingresos, Carga Dinámica | **2026** — en desarrollo, Sprint 33-36 (HU 211912) |
| **Caso 2.1** — Mejora de Preaprobado | Afiliado no acepta oferta preaprobada o el motor la desestima tras evaluar ingresos | Largo + declaración explícita de ingresos adicionales | **2027** |
| **Caso 2.2** — Aprobado en Firme | Afiliado no acepta oferta en firme e indica tener soportes de ingresos adicionales | Corto → Formulario de Ingresos Detallado + Carga Documental | **2027** |
| **Caso 2.3** — Novedades *(caso nuevo, no documentado antes)* | Afiliado quiere gestionar aumento o reactivación del cupo | Corto → Formulario de Ingresos Detallado + Carga Documental (según tipo de novedad) | **2027** |

**Estrategia de entrega explícita:** Caso 1 se construye como "columna vertebral técnica" **reutilizable** para 2.1/2.2/2.3 — es decir, el diseño de Caso 1 (HU 211912) es intencionalmente la base de la que heredan los otros 3, no un caso aislado.

**Nota sobre el detonante de Caso 1:** es más amplio de lo que sugiere "el motor manda a Zona Gris" — también incluye el caso en que el motor **sí evalúa pero la envía a validación interna** aunque técnicamente haya generado algo. Matiz a tener en cuenta al diseñar los casos de "sin oferta" vs "con oferta enviada a revisión".

## HUs relacionadas con campañas — sin investigar todavía

Del mismo deck (slide 33, "Otros frentes Cupo"): dos HUs que suenan directamente relacionadas con [[project_hu217528_mover_campana_creacion_caso]] pero no se han revisado en detalle:
- **HU 192150** — "Aceptación preaprob. y en firme - Asistido | Marcación de casos de cupo con campaña" (despliegue 2026-35)
- **HU 221404** — "Aceptación preaprob. y en firme | Recibir datos de campaña **desde el Site en Bizagi** al inicio del caso" (despliegue 2026-35; aparece como próxima historia de Gattaca en Sprint 34 — "Capturar campañas al inicio, Casos de Auto")

Posible lado Asistido/Bizagi del mismo cambio que hace 217528 del lado autogestionado — confirmar antes de asumir que son equivalentes.

## Riesgo transversal declarado por el equipo (relevante para diseño de pruebas)

"Ambientes no homologados... al realizar las pruebas los resultados han sido diferentes a lo que sucede en Productivo, lo que significa reprocesos" — riesgo "Materializado" según el propio Sprint Review. Tener presente al comparar evidencia capturada en CERT contra el comportamiento esperado en PROD.

Documentos relacionados en esta misma carpeta:
- [project_carga_documental_reglas_tecnicas.md](project_carga_documental_reglas_tecnicas.md) — FE/BE, endpoint de documentos requeridos, uFlow, CASE_REVIEW y validaciones de archivos
- [project_hu213144_revision_documental_backoffice.md](project_hu213144_revision_documental_backoffice.md) — formulario del Analista en Bizagi
- [reference_figma_gestion_documental.md](reference_figma_gestion_documental.md) — mockups

---

## Dos caminos de entrada a carga documental

### Caso 1 — el motor de decisión (uFlow) define el envío a Zona Gris

*Fuente de los casos 1.1, 2.1 y 2.2 de esta sección: HU **202180** "Habilitación de flujos previo a la carga documental" (New, sin parent, última edición 23/7).*

**1.1 Afiliado sin oferta o con preaprobado que el motor manda a Zona Gris** (formulario largo):
1. Identificar si no tiene oferta o tiene preaprobado enviado a Zona Gris.
2. Datos adicionales:
   - **Valor solicitado** — misma estructura y validaciones de campos numéricos (signo $, separador de miles, número de decimales).
   - **Canal de comunicación preferido** — Correo electrónico / WhatsApp / SMS, lista **parametrizable**.
3. Mostrar mensaje + **listado de documentos** a cargar según la matriz de documentos por producto, para iniciar el flujo de Gestión Documental / Mesa de Control.
4. Informar si los documentos cargados presentan alguna **inconsistencia**.
5. Informar que la solicitud entra a **validación interna**; contemplar una **URL** para reingresar al flujo y revisar el estado del análisis.

### Caso 2 — el usuario tiene soportes para mejorar la oferta aprobada (ya está en personalización de la oferta)

**2.1 Preaprobado que no acepta la oferta** (formulario largo):
1. Identificar preaprobado.
2. Identificar **tipo de afiliado**: Dependiente / Independiente / Pensionado.
3. Habilitar la opción "no estoy de acuerdo con la oferta" → direcciona a Zona Gris.
4. Habilitar carga de soportes **según tipo de afiliado**. El usuario debe **declarar** que los soportes corresponden a ingresos adicionales (aparte del salario básico mensual): p. ej. certificado de ingresos de contador público, certificado de tradición y libertad de vivienda que genera ingresos.
5. Datos adicionales: Valor solicitado + Canal de comunicación (igual que 1.1).
6-8. Mismos mensajes del caso 1.1: listado de documentos, inconsistencias, validación interna + URL de estado.

**2.2 Aprobado en firme** (formulario corto): igual que 2.1, pero el formulario de datos adicionales pide **Valor solicitado, Salario mensual, Ingresos adicionales y Otras fuentes de ingreso**, más el canal de comunicación.

---

## Cambios transversales

- **Eliminar el campo Estado Civil** del formulario de cupo **y** del de novedades.
- Integración con el motor de decisión para identificar estado de la solicitud (Zona Gris vs. con oferta) y tipo de afiliado.
- Preliminarmente **6 archivos por producto + 1 campo adicional "Otros documentos"**.
- Pendiente **actualizar el flujograma** de gestión documental con 5 variaciones:
  1. Solicitud de cupo estándar/preaprobado directo a carga documental
  2. Solicitud de cupo aprobado en firme
  3. Reactivación simple (reactivación con aumento, descartada por regla de negocio)
  4. Aumento con oferta y pase directo a carga documental
  5. Flujo cuando **no** requiere carga documental

---

## Pantalla previa: ingresos (Paso 1 de 4 · Información personal)

"¿Cuáles son tus ingresos mensuales?" → **Salario básico mensual** · **Ingresos adicionales en tu trabajo** (opcional, "Ej: Comisiones, bonos, etc.") · **¿Tienes ingresos adicionales por otras actividades? Sí / No**.

Al marcar **Sí** se despliega el callout "Ten a la mano los documentos de soporte" y los campos **Ingresos mensuales adicionales** (valor mensual promedio por otras actividades), **Tipo de actividad** (ej. Pagos adicionales) y **Origen específico del ingreso** (ej. Horas extras). El origen específico alimenta el cruce de la matriz de documentos.

---

## Pantalla de confirmación (Thank You Page de Zona Gris)

Tras "Enviar documentos": toast **"La información se envió exitosamente"** + título **"[UserName], nuestro equipo revisará tus documentos"** y copy "Pronto recibirás el resultado de tu solicitud de crédito, a través del canal de notificación que seleccionaste."

- **Número de caso: [#000000000]** y card resumen con **Producto** (Cupo de crédito), **Valor solicitado** ($4.000.000), **Fecha de la solicitud** (ej. 11 de junio de 2026) y **Canal de notificación** (ej. WhatsApp) → confirma que el canal elegido en el formulario se persiste y se muestra.
- **"¿Qué sigue ahora?"** en 3 pasos con íconos: *Validaremos los documentos* (se confirma que la información adjunta cumpla los requisitos) → *Analizaremos tu solicitud* (evaluación de la información recibida) → *Te informaremos el resultado* (respuesta por el canal seleccionado).
- Callout informativo "Notificaremos el estado de tu solicitud": si surgen inquietudes durante la revisión, el usuario recibirá notificaciones con las indicaciones para continuar (redacción aproximada del mockup).
- CTAs de cierre: **Conoce todo sobre créditos**, *Conoce nuestro portafolio de seguros*, y **¿Tienes más preguntas? → Ir a centro de ayuda**. No hay botón de retorno al flujo: el caso queda en validación interna.
- Es una **variante nueva de Thank You Page**; el copy debería venir de Drupal como las demás. **Por confirmar con desarrollo:** si la variante se resuelve por `noveltyType` o por una bandera de Zona Gris.

---

## HU 211912 — Caso 1 completo (fuente formal, Azure DevOps)

`[HU] Habilitación de flujo Caso 1 - El Motor envía a Zona Gris - Backoffice Gestión documental Globant`, PBI 211912, estado **New**, parent 198568. Es la HU formal de todo el Caso 1 (políticas → modal condicional → contacto → ingresos/SAP → carga documental → pantalla final → reintentos). La mayoría de su contenido ya coincidía con lo documentado aquí y en [project_carga_documental_reglas_tecnicas.md](project_carga_documental_reglas_tecnicas.md); lo que agrega de nuevo:

- **3 tipos de Mesa de Control parametrizables**: Mesa tradicional, Agente IA, Agente Manual + IA — la pantalla de validación intermedia (entre enviar documentos y la pantalla final) cambia de diseño/información según cuál esté activa.
- **Infobip** es el proveedor de notificaciones (antes sin nombrar): dispara 2 plantillas — (1) URL de retoma cuando la Mesa de Control rechaza un documento por causal de la "Matriz de devoluciones", (2) aviso de "límite de intentos alcanzado".
- **Límite de intentos de subsanación es configurable**; al superarlo, bloquea la carga, muestra pantalla informativa y dispara la plantilla de Infobip de límite excedido, orientando a "otro canal de atención".
- Se elimina el campo **"Número de celular secundario"** del formulario de contacto.
- Checkbox de políticas cambia de texto: **"He leído y acepto las políticas de solicitud de crédito"** (se quita la palabra "Cupo").
- El modal de oferta se muestra o se omite según si el afiliado **tiene o no una oferta vigente** al momento de la consulta (no según el tipo firme/preaprobado) — si no tiene oferta, salta directo a "Datos de contacto".
- **Almacenamiento de los archivos cargados: pendiente de definir por arquitectura** — abierto explícitamente por la propia HU, no inferido.
- Figma con node-id distinto al ya documentado: `27567-39856` (ver [reference_figma_gestion_documental.md](reference_figma_gestion_documental.md) — sin confirmar si es el mismo archivo con alcance más amplio o una vista separada).

**⚠️ Contradicción con lo documentado más arriba:** esta HU dice que "Canal preferido para notificaciones" tiene **solo 2 opciones (SMS y Correo electrónico)**, no 3 (Correo/WhatsApp/SMS) como se anotó en la sección "Pantalla previa: ingresos" de este mismo archivo. **Confirmar cuál versión rige antes de diseñar el caso de prueba de ese campo.**

## Puntos abiertos (confirmar antes de diseñar/ejecutar pruebas)

- El requerimiento pide una **URL para revisar el estado del análisis**, pero el mockup de confirmación **no la incluye** (solo notificaciones por canal).
- No está definido el **criterio/umbral exacto** con el que uFlow decide Zona Gris; el requerimiento solo menciona "el campo que se usará".
- Canal preferido para notificaciones: **2 opciones (HU 211912) vs 3 opciones (documentado antes)** — ver contradicción arriba.
- Almacenamiento de archivos de carga documental: sin definir por arquitectura (HU 211912).

## Cómo aplicarlo

Al escribir casos de prueba: cubrir los 3 sub-escenarios (1.1, 2.1, 2.2) por tipo de afiliado, verificar la parametrización (canal de comunicación y listado de documentos), que **Estado Civil ya no aparezca** en cupo ni novedades, y que el canal elegido se refleje en la pantalla de confirmación.

# HU 217173 · Formulario de carga de archivos — Renderizado (+ evento CASE_REVIEW)

PBI **217173**, estado New, tags `2027; Gestión_Documental; Globant`, **sin sprint asignado**, parent Feature 198568. Primera de dos HUs del componente "Información adicional + Carga"; la segunda es **217175** ("Carga de archivos - Back"). Reglas de fondo en [project_carga_documental_reglas_tecnicas.md](project_carga_documental_reglas_tecnicas.md). Verificado en Azure DevOps el 2026-09-23 (el texto de la HU coincide con el que pegó el usuario).

## Regla clave de la HU

- **La matriz de Bizagi es la fuente de verdad** por documento: **título, texto de ayuda, cantidad máxima y estado**. Literal: *"Estos límites no residen en Drupal."*
- Alcance declarado: *"maquetado de etiquetas base e integración visual"*.
- ⚠️ Choca con la matriz de contenido de Drupal (ítem 24: título y descripción **por tipo de documento** parametrizados en Drupal) → pregunta abierta 3.6.
- Figma de la HU: nodo **base** `29652-55948`. Ver [reference_figma_gestion_documental.md](reference_figma_gestion_documental.md) (hay un tercer nodo más reciente, `30147-82759`).

## Escenarios de aceptación

1. Render dinámico por matriz: título, texto de ayuda y contador por contenedor.
2. Cambio de frecuencia (mensual ↔ quincenal) con archivos cargados → modal con `Cancelar` / `Cambiar frecuencia`.
3. `Cambiar frecuencia` → borra comprobantes, contador a 0, límite 3 (mensual) o 6 (quincenal).
4. `Cancelar` → cierra el modal, conserva selección y archivos.
5. Backend emite `CASE_REVIEW` (payload: ids de caso, producto, banderas Zona Gris) → el FE, suscrito al canal, despliega la carga documental.

## Delimitación con HUs vecinas (Feature 198568)

| HU | Qué cubre | Implicación para las pruebas |
|---|---|---|
| **217175** (2ª) | Subida uno a uno (`Adjuntar`), estado y conteo en **DynamoDB**, endpoints subir/actualizar/eliminar, **descarte de archivos en el microservicio al reiniciar una categoría (cambio de frecuencia)**, envío del consolidado a Bizagi. **Sin criterios sobre PDF/peso/contraseña** | El borrado persistente y `Adjuntar` no son de 217173: TC010-012 solo se ejecutan end-to-end con ambas HUs o con estado sembrado |
| **217858** (Sprint 032) | **Parámetro global** que habilita/deshabilita la carga documental. Inactivo → se omite "Información Adicional y Carga Documental" y se redirige a la pantalla final (sin pop-up de éxito ni mención a revisión de documentos) | Precondición de toda la suite = parámetro **Activo**. Falta el negativo: `CASE_REVIEW` con parámetro Inactivo |
| **223810** (tag 2027, sin descripción) | Render de estados **revisados (para corregir)** | `Por corregir` / `Validado` quedan fuera de 217173 |
| **217180** | Envío del consolidado a Bizagi al pulsar `Enviar documentos` | El CTA final no es de esta HU |
| 217172 / 217171 / 217174 | Formulario de ingresos / información personal / pantalla "gracias" | Pantallas previa y posterior |

## Tareas de 217173 (19)

- **FE (5):** maquetado UI, integración UI Drupal, redirección a cargue + render de contenido, **render de estados**, **render de errores**. Los dos últimos **no tienen criterio en los escenarios** pero sí tarea.
- **DR (2):** nuevo tipo de contenido con **campos 19-25** y vista que alimenta un endpoint con esos campos (el contenido de Drupal llega por endpoint).
- **BE (4):** matriz para renderizar **Parte 1** y **Parte 2** (esta con tag 2027), estado para enviar a la pantalla de cargue, estado de carga del formulario.
- **QC:** diseño de pruebas (*Done*, 219093), ejecución (To Do). **UI:** revisión QA de interfaz (222356).
- **Integración (Done, Sprint 033):** `[uFlow]` punto de integración y `[CROSS FE/BE/TL]` definición de integración con Bizagi. **Sin descripción ni adjuntos en DevOps**: solo link a Figma `30147-82759` y un comentario genérico. **El contrato de la matriz y del evento no está en la HU.**
- Estado al 2026-09-23: FE/DR/BE en *To Do* → no hay nada construido que ejecutar todavía.

## Alcance temporal y entrada a la pantalla

Solo el **Caso 1** es 2026 (Sprint Review 34); los Casos 2.1/2.2/2.3 son 2027. Por eso la **única entrada a esta pantalla en 2026 es el evento `CASE_REVIEW`** (motor → Zona Gris). El flujo voluntario "Aumentar monto" (Caso 2.x) todavía no aplica. Detonante del Caso 1: el motor **no otorga oferta o la envía a validación interna** (dos precondiciones distintas para TC016).

## Evento CASE_REVIEW y arquitectura

Transporte **WebSocket** (API Gateway WS; los eventos `step`/`stepStatus` se originan en Bizagi; DynamoDB guarda `userId`+`connectionId`) — ver `reference_arquitectura_aws_gcp_plataforma_credito` (memoria global; diagrama, no verificado en vivo). `observador_flujo.py` (raíz del repo) ya graba los frames del WebSocket (`websockets.json`, `websocket.jsonl`) y sirve para evidenciar TC016/TC017 en vez de F12 manual.

## Revisión de la suite TC001-TC018 — segunda pasada (2026-09-23)

Cobertura: Esc. 2-4 → TC009-011 · Esc. 5 → TC016-018 · **Esc. 1 → solo TC002/TC005, débiles**. Sin escenario en la HU: TC001, 003, 004, 012, 013, 015.

Defectos (siguen vigentes):
- **TC010**: "contador (0/3) intacto" con comprobantes cargados es contradictorio (debe ser n/3); mezcla Esc. 2 y 4; solo prueba mensual→quincenal.
- **TC014** contradice la HU: los contenedores los define la matriz de Bizagi (tareas BE Parte 1/2), no Drupal; la tarea `[DR]` crea un tipo de contenido de campos fijos. TC001/TC013 no separan texto Drupal (19-25) de texto por contenedor (Bizagi).
- **TC002** no verificable: 3 perfiles en uno, sin contenedores esperados, no valida título/ayuda/contador. Debe ser data-driven por **(tipo de trabajador, tipo de actividad, origen específico)** — ver catálogo en [project_hu217172_pantalla_ingresos.md](project_hu217172_pantalla_ingresos.md); los esperados salen de la respuesta de la matriz Bizagi, no de memoria. La Parte 2 (2027) puede dejar perfiles fuera del alcance 2026.
- **TC004** bloqueado (máximo de Valor solicitado por definir, 3.2). La regla de "Ajustar cupo" no lo resuelve.
- **TC013**: título "tiempo real" vs pasos "recarga"; el contenido pasa por una vista/endpoint de Drupal (posible caché).
- **TC015**: sin viewport, estados ni nodo de Figma vigente (¿`29654-55949` o `30147-82759`?); solapa con la tarea `[UI]` de revisión QA.
- **TC016-018**: sin contrato del payload; TC016 sin negativo (parámetro 217858 Inactivo; con oferta directa); TC018 solo cubre el evento emitido *después* de reconectar.
- TC006-TC009 sin perfil: por el mockup, el bloque de nómina aparece con Dependiente + Pagos adicionales (Horas extras) — **supuesto, confirmar contra la matriz**.

Huecos (re-acotados): render de **estados** (Por adjuntar solo; faltan Adjuntado / Carga en proceso) y de **errores** (formato, contraseña, peso, genérico) — ambos con tarea FE en 217173 · parámetro 217858 · lista vacía o falla del endpoint de la matriz · documento opcional · título/ayuda largos desde Bizagi · frecuencia: sentido inverso, misma opción, solo se borran los de nómina, límite alcanzado · modal por teclado · CASE_REVIEW: duplicado, otro idCaso, ya en pantalla, timeout, **mismo usuario en 2 pestañas** (DynamoDB guarda varias `connectionId` por `userId`) · escritorio vs móvil · límites [Restringido] de Drupal. **Fuera de alcance de 217173** (no cubrir aquí): `Por corregir`/`Validado` (223810, 2027) y `Enviar documentos` deshabilitado (217175/217180).

Preguntas abiertas nuevas: 1.6-1.7 y 3.6-3.13 en [project_gestion_documental_preguntas_abiertas.md](project_gestion_documental_preguntas_abiertas.md); 6.7 sobre Figma.

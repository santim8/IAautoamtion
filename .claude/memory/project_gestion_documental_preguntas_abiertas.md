# Gestión Documental · Preguntas abiertas

Consolidado de todo lo que quedó sin definir en los insumos del épico (requerimientos, mockups, matriz de Drupal y suite TC001-TC017). Actualizado **2026-08-20**.

🔴 = bloquea diseño o ejecución de pruebas · 🟡 = afecta cobertura o datos de prueba · ⚪ = aclaración

---

## 1 · Enrutamiento y motor de decisión

| # | Pregunta | Contexto |
|---|---|---|
| 🔴 1.1 | ¿Cuál es el **campo y el criterio exacto** con que uFlow marca Zona Gris? | El requerimiento solo dice "el campo que se usará para manejar si se envía o no a Zona gris". Sin esto no se pueden construir los casos del Caso 1 (envío directo). |
| 🔴 1.2 | ¿Un **Negado** puede reconsiderarse aportando documentos? | El motor responde Aprobado / Negado / Zona Gris. Los insumos solo contemplan "sin oferta", "preaprobado" y "aprobado en firme" como puntos de partida; el Negado no aparece en ningún flujo. |
| 🟡 1.3 | En el **aumento con envío directo**, ¿qué ve el usuario? | Está mapeada solo la rama voluntaria. Falta saber si se salta la pantalla de oferta o la muestra con otro mensaje. |
| 🟡 1.4 | ¿Cómo se elige entre las **dos variantes de la pantalla de cierre** (con y sin carga documental)? | ¿Bandera del caso, `noveltyType`, o dos nodos de contenido distintos en Drupal? |
| ⚪ 1.5 | ¿**Toda** reactivación evita la carga documental, o solo la simple? | La reactivación con aumento está descartada por regla de negocio, así que hoy en la práctica serían todas. |

## 2 · Pantalla de ingresos (PBI 217172)

| # | Pregunta | Contexto |
|---|---|---|
| 🔴 2.1 | ¿Cuál es la **regla para un tipo de trabajador no parametrizado o vacío** que retorne SAP? | TC013 y TC014 validan "de acuerdo con la regla definida"… y esa regla no existe. ¿Bloquea, aplica un default, o enruta a un flujo alterno? |
| ⚪ 2.2 | ¿Qué hace el sistema si el **desplegable queda sin opciones** tras el filtro? | Prácticamente descartado con la matriz del 2026-08-20: el filtro quita **un origen específico**, no un tipo, y el tipo con menos orígenes elegible como principal (`Rentas de capital`) tiene 3. Solo ocurriría con una parametrización de Drupal degenerada. |
| ⚪ 2.3b | ¿Tiene sentido que el **Pensionado** pueda declarar `Pensión → Mesada Pensional` como ingreso **adicional**, si ya lo capturó como monto principal? | Solapamiento semántico que sobrevive a la matriz del 2026-08-20. Ya no bloquea (el perfil tiene otros 3 tipos), pero permite declarar dos veces la misma mesada. |
| 🟡 2.8 | Responder **"No"** ¿lleva a carga documental en **todos** los flujos? | La HU lo afirma sin distinguir: en el envío directo tiene sentido, pero en los flujos voluntarios el usuario llegó tras pulsar "Aumentar monto", y decir "No" contradice su propia decisión. Ambigüedad de la HU, no de los casos. |
| 🟡 2.5 | ¿**De dónde sale cada dato de pensionado**? | Pendiente declarado por el propio diseño en la nota técnica. |
| 🟡 2.6 | Al alternar **Sí → No → Sí**, ¿los datos ya digitados se conservan o se limpian? | TC006/TC007 validan visibilidad de los campos, no qué pasa con el valor. |
| ⚪ 2.7 | ¿Qué es la **"Tabla Soportes"** que menciona la HU? | Ya se confirmó que **las actividades se parametrizan en Drupal**; queda aclarar si "Tabla Soportes" es otro nombre para lo mismo o una fuente distinta. |

## 3 · Carga documental

| # | Pregunta | Contexto |
|---|---|---|
| 🔴 3.1 | ¿Cuántos **errores de carga** rigen: solo el de tamaño, o los 3 particulares + 1 genérico? | La doc del módulo dice "se está contemplando solo un error relacionado con el tamaño"; el feedback de sesión y los items 31-35 de Drupal definen 4. Determina todos los casos negativos. |
| 🔴 3.2 | ¿Cuáles son los **valores máximos** del rango de Valor solicitado? | Declarado "por definir". El mínimo sí está: la oferta (si tiene) o el mínimo del producto (si no). |
| 🟡 3.3 | ¿Cuál es el **límite de archivos de "Soporte de otros ingresos"**? | Pendiente declarado por el diseño. |
| 🟡 3.4 | ¿El listado de documentos depende **solo del tipo de usuario** o del cruce completo Producto + Tipo de Trabajador + Origen? | La nota del módulo dice solo tipo de usuario; la matriz de Bizagi define un cruce de tres dimensiones. |
| 🟡 3.5 | ¿La matriz de documentos ya está **parametrizada para aumento y reactivación**, o solo para cupo nuevo? | El piloto es solicitud de cupo, pero el alcance declarado incluye novedades. |

## 4 · Retoma

| # | Pregunta | Contexto |
|---|---|---|
| 🔴 4.1 | Al retomar en carga documental, ¿se **recuperan los archivos ya cargados** o solo el estado de los bloques? | Los mockups marcan "De retoma" sobre la pantalla de carga, incluso en el estado con archivos adjuntos. |
| 🔴 4.2 | ¿Qué pasa si se retoma cuando el caso **ya está en revisión del analista**? | Debería ser solo consulta de estado, no edición — pero no está definido. |
| 🟡 4.3 | ¿Cómo interactúa con **`/request/check`** del MS Request Manager? | Hoy ese endpoint solo maneja Reactivación (HU 207400); Aumentos y otros van en HUs aparte. |

## 5 · Backoffice (RF-213144)

| # | Pregunta | Contexto |
|---|---|---|
| 🔴 5.1 | ¿**Qué revisa el analista cuando no hay documentos**? | El flujo de reactivación llega a validación interna sin archivos, pero los paneles B, C y D del formulario están construidos alrededor de una tabla de documentos. |
| 🟡 5.2 | ¿Cómo se refleja el rechazo del analista en la UI del usuario? | Se infiere que vía estado `Por corregir`, pero no está descrito el mensaje ni el punto de reingreso. |

## 6 · Contenido y experiencia

| # | Pregunta | Contexto |
|---|---|---|
| 🔴 6.1 | **¿WhatsApp entra en el MVP?** | Las notas del dropdown marcan SMS y Correo como MVP y WhatsApp como "evolución", pero el mockup de la pantalla de confirmación muestra "Canal de notificación: WhatsApp". Afecta los datos de prueba. |
| 🟡 6.2 | ¿Se incluirá la **URL para consultar el estado del análisis**? | El requerimiento la pide explícitamente; ninguna pantalla de cierre la muestra. |
| 🟡 6.3 | Los conteos de la matriz de Drupal deben ser **variables, no fijos**: item 29 dice 3 pasos pero el flujo sin documentos usa 2; item 27 pasa de 4 a 3 items del card. | ¿Se parametriza la cantidad o son dos nodos de contenido distintos? |
| ⚪ 6.4 | ¿Se usará la **parametrización existente para los items 33, 34 y 35** de alertas? | Pregunta que la propia matriz de contenido deja abierta. |
| ⚪ 6.5 | ¿La pantalla de oferta de **aprobado en firme y preaprobado es el mismo componente**? | Los mockups son visualmente idénticos; si se confirma, no hay que probar el ingreso a Zona Gris dos veces. |

---

## Resueltas

- ✅ **¿Las actividades se parametrizan en Drupal o en Bizagi?** → **Drupal** (2026-08-14).
- ✅ **¿La retoma aplica a la etapa de carga documental?** → Sí; los mockups marcan "De retoma" sobre la oferta y sobre la pantalla de carga.
- ✅ **¿`Origen específico del ingreso` depende de `Tipo de actividad`?** → Sí, es cascada, y ambos dependen del tipo de trabajador.
- ✅ **¿A quién aplica la regla de exclusión de la actividad principal, y sobre qué campo?** → Solo a **Independientes**, y **filtra por `Origen específico`, no por `Tipo de actividad`** (matriz 2026-08-20). El tipo ya usado como principal **sigue apareciendo** en el listado de adicionales; desaparece únicamente el origen concreto.
- ✅ **¿De dónde viene el tipo de trabajador?** → De **SAP**, no del motor de decisión.
- ✅ **La tabla de actividades, ¿son las principales o las adicionales?** → Son las **adicionales** (`Tipo de actividad`, item 13), y el catálogo completo (4 tipos) aplica **igual para los 3 perfiles**. En **Independiente** un subconjunto de 2 tipos (Rentas de capital, Servicios independientes) alimenta además `Actividad principal` (item 16), y por eso ahí —y solo ahí— aplica el filtro.
- ✅ **¿Cuál es el catálogo real de actividades de Independiente?** → `Rentas de capital` y `Servicios independientes` con sus orígenes (matriz 2026-08-20). Los textos del mockup ("Trabajo independiente o prestación de servicios" / "Servicio a un tercero") **están desactualizados**.
- ✅ **¿El Pensionado que responde "Sí" tiene opciones reales?** → **Sí** (2026-08-20): ve los 4 tipos, incluidos Rentas de capital, Servicios independientes y Pagos adicionales. Deja de ser hueco de parametrización; queda solo el solapamiento anotado en 2.3b.
- ✅ **¿Cada `Tipo de actividad` pertenece a un perfil?** → **No.** Los 4 tipos están disponibles como actividad adicional para los 3 perfiles. Lo único que varía por perfil es si se pide `Actividad principal`.
- ✅ **¿Un Dependiente se queda sin opciones por el filtro?** → **No.** Su actividad principal es el empleo, capturado como monto (salario), no como opción seleccionada; sin selección no hay nada que excluir. Ve "Pagos adicionales" normalmente.

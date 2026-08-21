# Carga documental · reglas técnicas (FE, BE, eventos)

HUs técnicas de la épica descrita en [project_gestion_documental_zona_gris.md](project_gestion_documental_zona_gris.md). Mockups en [reference_figma_gestion_documental.md](reference_figma_gestion_documental.md).

---

## Frontend — formulario "Información Adicional y Carga Documental"

- Campo **Valor solicitado**: formato numérico de moneda, **sin la palabra "Cupo"** en sus etiquetas. En el mockup: mínimo $700.000 / máximo el valor aprobado.
- Secciones contenedoras **por tipo de documento** con estados visuales. Cada sección muestra contador `Archivos adjuntos (n/N)`, lista de archivos con nombre + peso + acción Eliminar, barra de progreso durante la carga y toast "El documento se adjuntó correctamente".

### Estados de carga (definición del diseño)

Aplican **a nivel de tipo de documento** (ej. extracto bancario, declaración de renta), no a cada archivo individual:

| Estado | Definición |
|---|---|
| **Por adjuntar** | El documento no tiene ningún archivo adjunto aún |
| **Adjuntado** | El documento tiene al menos un archivo adjunto o reemplazado |
| **Por corregir** | El documento presenta **inconsistencias en al menos un adjunto** |
| **Validado** | El documento **no presenta novedades en ninguno** de sus adjuntos |

> `Por corregir` y `Validado` son estados **posteriores a la revisión del analista** (RF-213144): es el mecanismo por el que un rechazo con causal vuelve al usuario. `Por corregir` es el que materializa la ruta "Devolver".

### Estados por archivo (segundo nivel)

Además del estado por documento existe un estado **por archivo individual** (ej. `extracto_bancario_junio_2026`):

| Estado | Definición |
|---|---|
| **Validado** | El archivo no presenta inconsistencia |
| **Con inconsistencias** | El archivo tiene al menos una inconsistencia |

> Son **dos niveles**: el estado del documento se deriva del de sus archivos (un documento queda `Por corregir` si **al menos uno** de sus archivos tiene inconsistencias, y `Validado` si **ninguno** las tiene).

### Comportamiento del botón adjuntar (4 escenarios)

| Escenario | Botón |
|---|---|
| Aún no hay archivos adjuntos | **Adjuntar** |
| Ya hay n archivos adjuntos | **Adjuntar otro** |
| Carga en curso | **Carga en proceso** |
| Se alcanzó el límite de archivos del documento (pueden ser hasta 6) | **El botón se oculta** |

### Selector de frecuencia de pago (comprobantes de nómina)

- **Selección por defecto: ninguna** — ningún radio button viene marcado.
- **El contador de archivos solo se muestra cuando hay una selección** de frecuencia.
- Si el usuario **cambia la frecuencia teniendo archivos cargados**, se muestra un **warning de confirmación** y **se eliminan los comprobantes ya cargados**.
- Modal: **"¿En verdad quieres cambiar la frecuencia de pago?"** — "Al cambiar la frecuencia de pago se eliminarán los comprobantes ya cargados." · Botones **`Cancelar`** / **`Cambiar frecuencia`**.
- Patrón de warning transversal al flujo: **se muestra centrado y debe ser navegable con teclado**.

### Valor solicitado — rangos (PENDIENTE de definir)

| Situación | Mínimo | Máximo |
|---|---|---|
| **Con oferta** | El valor de la **oferta** | *Por definir* |
| **Sin oferta** | El **mínimo del producto** | *Por definir* |

> El "Mínimo $700.000 – Máximo aprobado" que aparece en los mockups es un valor de ejemplo, **no la regla final**. Con oferta, el mínimo es la oferta misma: no se puede pedir menos de lo ya aprobado.

### Listado de documentos

Nota del diseño: *"el listado de documentos requeridos estará ligado al tipo de usuario (Dependiente, Independiente o Pensionado)"*. Es una versión reducida del cruce completo de la matriz (Producto + Tipo de Trabajador + Origen de Ingreso Adicional) — confirmar si el listado depende solo del tipo de usuario o del cruce completo.

### Pendientes declarados por el diseño

- Validar el **límite de archivos** permitidos en "Soporte de otros ingresos".
- Definir los **valores máximos** del rango de Valor solicitado.
- **Selector condicional para comprobantes de nómina**: Pago quincenal → **6** archivos, Pago mensual → **3** archivos. El límite se ajusta dinámicamente y se trabajó la casuística de **cambiar de opción con documentos ya cargados**.
- Etiquetas, microtextos de ayuda e instrucciones se consumen **parametrizables desde Drupal (DR)**. La matriz completa de items, límites de caracteres y listas editables está en [reference_drupal_contenido_gestion_documental.md](reference_drupal_contenido_gestion_documental.md).
- Existe versión **escritorio y móvil**.
- Secciones del mockup: Extractos bancarios (3) · Declaración de renta (1) · Estados financieros (1) · Comprobantes de nómina (3 o 6) · **Soporte de otros ingresos (opcional)**. CTA "Enviar documentos" deshabilitado hasta completar los obligatorios.

## Validaciones de archivos (aplica a **todos los flujos**)

- Obligatorio subir los documentos **por separado**, no un consolidado.
- Solo **PDF**; debe existir un error específico de **formato** (no basta con bloquear el selector de archivos).
- Error si el archivo está **con contraseña o encriptado** (el usuario puede saltarse la restricción del selector).
- Error por **peso** (mockup: máx. **3.5 MB por archivo**).
- **Error genérico** cuando falla el servicio de carga y hay que reintentar después.
- Resultado del rediseño: **3 errores particulares + 1 genérico** consolidados.

> ⚠️ **Contradicción entre insumos.** La documentación del módulo de carga dice: *"se espera que el usuario solo pueda seleccionar documentos PDF en su equipo. Esto es relevante porque **se está contemplando solo un error relacionado con el tamaño**"* — es decir, el selector filtra a PDF y el único error sería el de peso. Eso choca con el feedback de sesión (que pedía error explícito de formato porque el usuario puede saltarse el filtro) y con los 4 errores del rediseño (items 31-35 de Drupal). **Confirmar cuál versión rige** antes de diseñar los casos negativos.

---

## Backend — endpoint de documentos requeridos

- Crear/exponer el endpoint de **detalle consolidado del caso** con la trama de datos de gestión documental.
- Hace el cruce **Producto + Tipo de Trabajador + Origen de Ingreso Adicional** contra la **matriz paramétrica de Bizagi**. Los valores concretos de actividad y origen (en cascada, por tipo de trabajador) están en [project_hu217172_pantalla_ingresos.md](project_hu217172_pantalla_ingresos.md).
- Retorna el listado de documentos exigidos con sus propiedades: **nombre del documento, tipo de archivo permitido, peso máximo, cantidad de archivos permitidos, carácter obligatorio u opcional**.
- Se consume **al cargar** la pantalla de Información Adicional.

## Origen del "Tipo de trabajador"

Lo retorna **SAP** (valores `Dependiente` / `Independiente` / `Pensionado`), **no** el motor de decisión — ver [project_hu217172_pantalla_ingresos.md](project_hu217172_pantalla_ingresos.md). Es una de las tres dimensiones del cruce de la matriz de documentos, así que una falla de SAP compromete toda la etapa de carga documental.

## Trama uFlow (motor de decisión)

- Mapear y analizar los campos del JSON de respuesta de uFlow al finalizar la evaluación del motor.
- Extraer el campo que determina **si el caso se envía o no a Zona Gris**, más los demás campos requeridos por la matriz de gestión documental.
- **Propagar** la trama al microservicio de Gestión Documental y a Bizagi para habilitar la etapa de cargue.

## Evento CASE_REVIEW (WebSocket / mensajería)

- Se **emite** cuando el motor determina que el caso entra a la ruta de validación adicional de gestión documental.
- **Payload:** identificadores del caso, producto y **banderas de estado de Zona Gris**.
- El Frontend se **suscribe** al canal y, al recibir la confirmación, ejecuta la **transición al módulo de Carga Documental**. Es el mismo canal de eventos (`/event-to-client`) por donde viaja `noveltyType`.

---

## Cómo aplicarlo

Para probar carga documental: primero verificar la respuesta del **endpoint de documentos requeridos** (cantidades y obligatoriedad por tipo de trabajador y origen de ingreso), y después la UI. Casos negativos obligatorios: archivo no-PDF, PDF con contraseña, exceso de peso, exceso de cantidad, y falla del servicio de carga.

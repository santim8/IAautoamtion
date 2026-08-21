# RF-213144 · Gestión Doc. Asistido: Revisión documental manual (Back)

Formulario de la actividad **"Realizar revisión documental"** en el proceso de **Backoffice** de Gestión de Crédito (Bizagi). Es la revisión humana posterior al cargue de documentos descrito en [project_gestion_documental_zona_gris.md](project_gestion_documental_zona_gris.md) y [project_carga_documental_reglas_tecnicas.md](project_carga_documental_reglas_tecnicas.md).

**Narrativa:** como *Analista de Crédito* quiero visualizar en una única pantalla interactiva la información de la solicitud, el perfil financiero del solicitante y los documentos adjuntos, para validar manualmente si cada documento cumple los requisitos, aprobándolo o rechazándolo con su causal, y continuar el flujo del crédito.

---

## Paneles

- **A · Encabezado de la solicitud (solo lectura, persistente):** Número de Solicitud, Creador de la Solicitud, Fecha Creación, Estado de la Solicitud.
- **B · Navegación y tabla de documentos:** pestañas *Validación de Documentos · Información Inicial y T&C · Seguimiento*. Tabla con columnas **Nombre Documento, Estado, Seleccionar**; al seleccionar un registro se muestran y actualizan los paneles C y D. **Al ingresar a la actividad solo son visibles los documentos en estado pendiente** (ni aprobados ni rechazados). El widget debe soportar los **N documentos** que se hayan cargado previamente.
- **C · Visor integrado de documentos (panel derecho):** soporta **PDF, JPG, PNG** con zoom (acercar/alejar), paginación y descarga. **No debe requerir descargas externas obligatorias** para visualizar el archivo.
- **D · Panel de validaciones del documento (interactivo):** muestra el nombre del documento seleccionado y un radio button **¿Documento Aprobado? [Yes / No]**, obligatorio. Si se selecciona **No** → se habilita la tabla de **Causales de rechazo** (parametrizadas) y es obligatorio marcar **al menos una** mediante checkbox.
- **E · Información del solicitante y perfil financiero (solo lectura):**
  - Bloque 1 — Nombre Completo, Tipo de Documento, Número de Documento, Tipo de Trabajador.
  - Bloque 2 — información financiera **dinámica según el tipo de trabajador** (Independiente, Pensionado, Dependiente).
- **F · Trazabilidad de casos rechazados:** **contador** del número de veces que se ha rechazado un documento.
- **G · Resultado de la validación:** al finalizar la revisión el flujo toma la ruta **Aprobado** (continúa el proceso) o **Devolver** (se vuelve a pedir el cargue de documentación).

---

## Reglas, dependencias y restricciones

- Los **campos obligatorios impiden el envío** del formulario si están vacíos; el sistema no debe permitir avanzar con obligatorios sin marcar o sin responder.
- Las **causales de rechazo están previamente parametrizadas**; los datos del encabezado vienen predefinidos.
- El panel de Información del Solicitante es de **solo lectura**.
- Depende de que la actividad previa (**Cargue de documentos**) haya finalizado correctamente para que el caso llegue a la bandeja del Analista, y de la disponibilidad del repositorio documental.
- Fuera de alcance: NA.

## Cómo aplicarlo

Casos de prueba obligatorios: documento sin responder el radio (no debe permitir envío), rechazo sin causal seleccionada, rechazo con ≥1 causal, verificación de que un documento ya gestionado desaparece de la tabla al reingresar, incremento del contador de rechazos, y ambas rutas de salida (Aprobado / Devolver).

# Gestión Documental · Zona Gris (contexto funcional)

**Zona Gris** = instancia de validación adicional (Mesa de Control) donde el afiliado carga soporte documental que certifique sus **ingresos adicionales**. Piloto: **Solicitud de cupo** (y sus variantes Aumentos y Reactivaciones), pero la solución debe ser **paramétrica** para los demás productos de crédito futuros.

Documentos relacionados en esta misma carpeta:
- [project_carga_documental_reglas_tecnicas.md](project_carga_documental_reglas_tecnicas.md) — FE/BE, endpoint de documentos requeridos, uFlow, CASE_REVIEW y validaciones de archivos
- [project_hu213144_revision_documental_backoffice.md](project_hu213144_revision_documental_backoffice.md) — formulario del Analista en Bizagi
- [reference_figma_gestion_documental.md](reference_figma_gestion_documental.md) — mockups

---

## Dos caminos de entrada a carga documental

### Caso 1 — el motor de decisión (uFlow) define el envío a Zona Gris

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

## Puntos abiertos (confirmar antes de diseñar/ejecutar pruebas)

- El requerimiento pide una **URL para revisar el estado del análisis**, pero el mockup de confirmación **no la incluye** (solo notificaciones por canal).
- No está definido el **criterio/umbral exacto** con el que uFlow decide Zona Gris; el requerimiento solo menciona "el campo que se usará".

## Cómo aplicarlo

Al escribir casos de prueba: cubrir los 3 sub-escenarios (1.1, 2.1, 2.2) por tipo de afiliado, verificar la parametrización (canal de comunicación y listado de documentos), que **Estado Civil ya no aparezca** en cupo ni novedades, y que el canal elegido se refleje en la pantalla de confirmación.

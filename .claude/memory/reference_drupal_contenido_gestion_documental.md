# Drupal · Matriz de contenido parametrizable — Gestión Documental

Todo el copy de las pantallas de Gestión Documental (GD) se administra desde **Drupal**, no está hardcodeado en el Frontend. Fuente: matriz "Gestión de contenido I-IV" (items 1-35).

Complementa [project_carga_documental_reglas_tecnicas.md](project_carga_documental_reglas_tecnicas.md) y [project_gestion_documental_zona_gris.md](project_gestion_documental_zona_gris.md).

## Convenciones de la matriz

- **[Restringido]** = el límite de caracteres se **valida/corta**. **[Sugerido]** = límite blando, orientativo para el editor.
- **"Drupal Helper: Sí, se muestra sugerencia"** = en el CMS se le muestra al editor la sugerencia de longitud del campo.
- **"Aplica para 3 flujos en GD"** = el mismo contenido se reutiliza en los 3 sub-escenarios (Caso 1.1, Caso 2.1 y Caso 2.2).
- **Origen `Dinámico/Drupal`** = plantilla en Drupal + dato inyectado en runtime (nombre de usuario, número de caso).

---

## Pantalla · Contacto (GC I, items 1-6)

| # | Campo / Copy | Origen | Límites | Notas |
|---|---|---|---|---|
| 1 | ¿Cómo podemos contactarte? | Drupal | Título 35 [Restringido] | Aplica para 3 flujos en GD |
| 2 | Número de celular | Drupal | Label 45 [Restringido] | |
| 3 | Confirma tu número de celular | Drupal | Label 45 [Restringido] | |
| 4 | Correo electrónico | Drupal | Label 45 [Restringido] | |
| 5 | Confirma tu correo electrónico | Drupal | Label 45 [Restringido] | |
| 6 | Canal preferido para notificaciones | Drupal | Label 45 [Restringido] · Input Helper 65 [Restringido] · Menu options 30 [sugerido] | **Agregar y quitar opciones** · Min-Máx opciones **1-10** [sugerido] |

> El item 6 confirma que la lista de canales (Correo / WhatsApp / SMS) es editable desde Drupal, con entre 1 y 10 opciones.

## Pantalla · Ingresos (GC I items 7-10, GC II items 11-17, GC III item 18)

| # | Campo / Copy | Origen | Límites | Notas |
|---|---|---|---|---|
| 7 | ¿Cuáles son tus ingresos mensuales? | Drupal | Título 35 [Restringido] | Aplica para 3 flujos en GD |
| 8 | Salario básico mensual | Drupal | Label 45 [Restringido] | |
| 9 | Ingresos adicionales en tu trabajo | Drupal | Label 45 [Restringido] | |
| 10 | ¿Tienes ingresos adicionales por otras actividades? | Drupal | Label 55 [Restringido] | |
| 11 | "Ten a la mano los documentos de soporte…" | Drupal | Título 40 [Sugerido] · Descripción 140 [Sugerido] | Callout que aparece al responder **Sí** en el item 10 |
| 12 | Ingresos mensuales adicionales | Drupal | Label 45 [Restringido] | |
| 13 | Tipo de actividad | Drupal | Label 45 [Restringido] · Menu options 30 [sugerido] | Agregar y quitar opciones · Min-Máx **1-10** |
| 14 | Origen específico del ingreso | Drupal | Label 45 [Restringido] · Menu options 30 [sugerido] | Agregar y quitar opciones · Min-Máx **1-10** |
| 15 | Ingreso mensual de tu actividad principal | Drupal | Label 45 [Restringido] · Helper 90 [Restringido] | Variante **Independiente** |
| 16 | Actividad principal | Drupal | Label 45 [Restringido] · Menu options 30 [sugerido] | Variante **Independiente** · Min-Máx **1-10** |
| 17 | Origen específico del ingreso | Drupal | Label 45 [Restringido] · Menu options 30 [sugerido] | Variante **Independiente** · Min-Máx **1-10** |
| 18 | Ingreso mensual por pensión | Drupal | Label 45 [Restringido] · Helper 90 [Restringido] | Variante **Pensionado** |

> Los items 12-14, 15-17 y 18 confirman que la pantalla de ingresos **cambia según tipo de afiliado**, con listas desplegables parametrizables. El `Origen específico del ingreso` es el campo que alimenta el cruce de la matriz de documentos.

> **Corrección (2026-08-20).** Los items **12-14 no son exclusivos de Dependiente**: son el bloque genérico de *actividad adicional* y lo usan **los tres perfiles**, porque la matriz definitiva habilita los 4 tipos de actividad para todos. Lo exclusivo de **Independiente** son los items **15-17** (`Ingreso mensual de tu actividad principal`, `Actividad principal` y su `Origen específico`), y el 18 lo es de **Pensionado**. Catálogo completo y reglas de filtro: [project_hu217172_pantalla_ingresos.md](project_hu217172_pantalla_ingresos.md).

> **Chequeo del límite de 30 caracteres [sugerido] en menu options:** el catálogo oficial cabe, pero apretado. La opción más larga es **"Actividad sin local comercial" (29)**, seguida de **"Negocio con local comercial" (27)** y **"Transporte por plataformas" (26)**. Cualquier reformulación de copy en esos tres orígenes puede romper el límite — vale un caso de prueba de contenido.

## Pantalla · Información adicional y carga documental (GC III, items 19-24)

| # | Campo / Copy | Origen | Límites | Notas |
|---|---|---|---|---|
| 19 | Información adicional | Drupal | Título 30 [Restringido] | Aplica para 3 flujos en GD |
| 20 | Datos de solicitud | Drupal | Título 30 [Restringido] | Aplica para 3 flujos en GD |
| 21 | Valor solicitado | Drupal | Label 45 [Restringido] · Helper 90 [Restringido] | |
| 22 | Adjuntar documentos | Drupal | Título 25 [Restringido] · Descripción 130 [Restringido] | |
| 23 | "Adjunta únicamente archivos en formato PDF, sin contraseña ni encriptación, con un peso máximo de 3.5 MB…" | Drupal | **Alerta 140 [Restringido]** | Instrucción de requisitos de archivo |
| 24 | Soporte de otros ingresos (opcional) — documentos en general | Drupal | Título 40 [Sugerido] · Descripción 90 [Sugerido] | **La cantidad de documentos a parametrizar depende de la configuración de la matriz** |

> El item 24 es clave: el bloque de cada tipo de documento (título + descripción) se parametriza **N veces según la matriz** de documentos por producto — no hay una lista fija en Drupal.

## Pantalla · Confirmación / Thank You Page (GC IV, items 25-30)

| # | Campo / Copy | Origen | Límites | Notas |
|---|---|---|---|---|
| 25 | "[UserName], nuestro equipo revisará tus documentos" | **Dinámico/Drupal** | Título 50 [Sugerido] | Nombre inyectado en runtime |
| 26 | "Pronto recibirás el resultado de tu solicitud de crédito, a través del canal de notificación que seleccionaste…" | Drupal | Descripción 120 [Sugerido] | |
| 27 | "Número de caso: [#000000000]" | **Dinámico/Drupal** | Título 20 [Sugerido] — **sin incluir el número después de ':'** · **Item de contenedor 25 [Restringido]** | Los items del card (ej. "canal de notificación", producto, valor, fecha) son parametrizables a 25 caracteres c/u. **La cantidad de items varía: 4 con carga documental, 3 sin ella** (no aparece Valor solicitado) |
| 28 | ¿Qué sigue ahora? | Drupal | Título 20 [Sugerido] | |
| 29 | Validaremos los documentos | Drupal | **Parametrización para cada uno de los 3 items:** Título 30 [Sugerido] · Descripción 90 [Restringido] · **Ícono en formato SVG** | Los pasos (validaremos / analizaremos / te informaremos) son configurables, ícono incluido. **⚠️ La matriz dice 3, pero el flujo sin carga documental usa solo 2** — el conteo debe ser variable |
| 30 | "Notificaremos el estado de tu solicitud…" | Drupal | Título 50 [Restringido] · Descripción 140 [Restringido] | Callout informativo |

## Alertas de error (GC IV, items 31-35)

| # | Campo / Copy | Origen | Límites | Notas |
|---|---|---|---|---|
| 31 | "Reemplaza el archivo por uno que cumpla con los requisitos." | Drupal | **Alerta 60 [Restringido]** | |
| 32-35 | Alertas restantes de error de carga | Drupal | **Alerta 60 [Restringido]** | **Pendiente: validar si se usará la parametrización existente para los items 32, 33, 34 y 35** |

> Cuadran con los **3 errores particulares + 1 genérico** definidos en el rediseño (formato, contraseña/encriptado, peso, y falla de servicio). El copy de cada uno cabe en **60 caracteres**.

---

## Verificación contra los mockups

Los mockups de Figma traen **globos amarillos numerados** sobre cada campo, que corresponden a estos mismos items. Contrastados:

- ✅ **Items 1-6** (datos de contacto) — confirmados uno a uno en el mockup "5.1. Datos de contacto".
- ✅ **Items 7-14** (ingresos, variante Dependiente) — confirmados en "6.1.1 Datos Ingresos Dependientes".
- ✅ **Items 19-24** (información adicional y carga documental) — confirmados en el mockup de "Información adicional".
- ⚠️ **Items 15-18** (variantes Independiente y Pensionado) y **25-35** (confirmación y alertas) aún **sin verificar** contra mockup numerado, pero el patrón de la matriz se sostiene.
- Los items **33, 34 y 35 no traen copy** en la matriz; solo se mencionan en la nota del item 32.

> La numeración de Figma es la forma directa de rastrear cualquier texto en pantalla hasta su campo parametrizable en Drupal.

## Cómo aplicarlo

- Los límites **[Restringido]** son casos de prueba directos: cargar en Drupal un texto que exceda el límite y verificar el comportamiento (corte/validación) en la UI; los **[Sugerido]** no deberían bloquear.
- Verificar que las listas parametrizables (items 6, 13, 14, 16, 17) permitan **agregar y quitar opciones** y respeten el rango **1-10**.
- Verificar que los contenidos marcados "Aplica para 3 flujos en GD" (items 1, 7, 19, 20) se reflejen igual en los 3 sub-escenarios: un cambio en Drupal debe verse en los tres.

# PBI 217172 · Pantalla de ingresos por tipo de trabajador

HU del flujo de [Gestión Documental](project_gestion_documental_zona_gris.md). Cubre la pantalla **"¿Cuáles son tus ingresos mensuales?"** mapeada en [project_gestion_documental_mapa_flujos.md](project_gestion_documental_mapa_flujos.md).

## Datos nuevos que aporta esta HU

- **El "Tipo trabajador" lo retorna SAP**, no el motor de decisión. El requerimiento original hablaba de "integración con el motor para identificar el tipo de afiliado"; la fuente real es **SAP**. Valores: `Dependiente`, `Independiente`, `Pensionado`.
- **Las actividades se parametrizan en Drupal** (confirmado por el equipo, 2026-08-14). Resuelve el pendiente del diseño de "alinearse con Gattaca: ¿Drupal o Bizagi?" → **Drupal**. Los desplegables `Tipo de actividad` y `Origen específico del ingreso` se administran con los items **13, 14, 16 y 17** de la matriz de contenido, con sus reglas de agregar/quitar opciones y rango 1-10.
- **Regla de negocio nueva:** la actividad principal del afiliado se excluye del listado de actividades adicionales — aplica **solo a Independientes** y, según la matriz del 2026-08-20, **filtra por `Origen específico`, no por `Tipo de actividad`**. Justificación literal del diseño: *"se espera que el usuario no pueda ingresar como actividad adicional la misma actividad primaria, **ya que de estas actividades se derivan los documentos que se van a solicitar**"*. Está redactada **explícitamente para independientes**.
- Los desplegables **Tipo de actividad → Origen específico del ingreso** funcionan **en cascada**: el origen depende de la actividad seleccionada.
- La bifurcación aplica a **todos los flujos de solicitud de cupo** ("cuando corresponda").

## Campos por perfil (según items de Drupal)

| Perfil | Campos propios | Items Drupal |
|---|---|---|
| **Dependiente** | Ingresos mensuales adicionales · Tipo de actividad · Origen específico del ingreso | 12, 13, 14 |
| **Independiente** | Ingreso mensual de tu actividad principal · **Actividad principal** · Origen específico del ingreso | 15, 16, 17 |
| **Pensionado** | Ingreso mensual por pensión | 18 |
| *Comunes* | Salario básico mensual · Ingresos adicionales en tu trabajo (opcional) · ¿Tienes ingresos adicionales por otras actividades? | 8, 9, 10 |

> **El campo "Actividad principal" (item 16) solo existe en el perfil Independiente.** Confirmado en los mockups: la regla de exclusión está redactada explícitamente como "regla de negocio para independientes".

## Matriz de parametrización de actividades (cascada)

> **Versión definitiva, confirmada en sesión del 2026-08-20** (Andrés Duarte, Santiago Correa, David Ávalos, Carlos Gómez). **Sustituye** la lectura anterior de los mockups, que asignaba cada `Tipo de actividad` a un único perfil: **esa lectura era incorrecta.**

**Regla estructural:** los **cuatro** tipos de actividad (Rentas de capital · Servicios independientes · Pagos adicionales · Pensión) están disponibles como **actividad ADICIONAL para los tres perfiles**. Lo único que cambia por perfil es si se pide **`Actividad principal`** — y solo el Independiente la pide.

### Actividad principal

| Perfil | ¿Se solicita? | Catálogo disponible |
|---|---|---|
| **Dependiente** | **No** | — (su ingreso principal es el salario, capturado como monto) |
| **Pensionado** | **No** | — (su ingreso principal es la mesada, capturada como monto) |
| **Independiente** | **Sí** | Solo **Rentas de capital** y **Servicios independientes**, con sus orígenes. **No** incluye Pagos adicionales ni Pensión |

### Actividad adicional — catálogo completo (idéntico para los 3 perfiles)

| Tipo de actividad | Origen específico del ingreso |
|---|---|
| **Rentas de capital** | Arriendo de inmuebles · Dividendos · Rendimientos financieros |
| **Servicios independientes** | Prestación de servicios · Negocio con local comercial · Actividad sin local comercial · Ventas por Internet · Transporte por plataformas |
| **Pagos adicionales** | Horas Extras · Comisiones · Bonificaciones |
| **Pensión** | Mesada Pensional |

> De estos valores **se derivan los documentos que se solicitan** (es el "Origen de Ingreso Adicional" del cruce de la matriz de documentos). Son, por tanto, los datos de prueba críticos de todo el flujo.

### 🔴 La exclusión filtra por ORIGEN ESPECÍFICO, no por tipo de actividad

Literal de la matriz, fila de Independiente / actividad adicional: *"Excepción de su elección anterior en **Origen Específico** (Nota: **Filtro por origen específico**)"*.

Es decir: si un Independiente elige como principal `Servicios independientes → Prestación de servicios`, en la actividad adicional **vuelve a ver `Servicios independientes`**; lo único que desaparece es el origen **Prestación de servicios**, quedando disponibles los otros cuatro orígenes de ese tipo.

Esto **corrige** la lectura literal de la HU (*"excluir automáticamente la opción seleccionada como Actividad principal, evitando duplicidades"*), que se venía interpretando como excluir el `Tipo de actividad` completo.

| Perfil | ¿Hay actividad principal seleccionada? | ¿Qué se excluye del listado adicional? |
|---|---|---|
| **Dependiente** | No — no existe el campo | **Nada.** Ve los 4 tipos completos |
| **Pensionado** | No — no existe el campo | **Nada.** Ve los 4 tipos completos |
| **Independiente** | Sí | **Solo el origen específico** ya usado como principal. El tipo de actividad sigue disponible |

> **El error de razonamiento frecuente** es asumir que Dependiente o Pensionado "tienen una actividad principal predeterminada" que se excluiría, dejándolos sin opciones. No es así: su ingreso principal se captura como **monto**, no como opción de catálogo. Sin selección no hay nada que filtrar.

### Solapamiento a vigilar (no bloqueante)

`Pensión → Mesada Pensional` figura como actividad **adicional** también para el **Pensionado**, cuyo ingreso principal ya se capturó como monto en `Ingreso mensual por pensión`. Ya **no** es un hueco de parametrización (tiene los otros tres tipos), pero sí un **solapamiento semántico**: podría declarar dos veces la misma mesada. Merece caso de prueba y pregunta al negocio.

Simétricamente, `Pensión → Mesada Pensional` está disponible para **Dependiente e Independiente** — coherente con un afiliado que trabaja y además recibe pensión.

## Campos obligatorios por perfil (notas del diseño)

| Perfil | Obligatorios para avanzar |
|---|---|
| **Dependiente** | 1. Salario · 2. ¿Tienes ingresos adicionales por otras actividades? |
| **Independiente** | 1. Ingreso · 2. **Actividad principal** · 3. **Origen específico del ingreso** |
| **Pensionado** | 1. Ingreso mensual por pensión |

En los tres perfiles la nota es la misma: *"'¿Tienes ingresos adicionales por otras actividades?' puede ser **'no'** y el usuario aún así podría avanzar"*. Y dentro de la sección de ingresos adicionales: *"todos los campos son necesarios para avanzar excepto el declarado como 'opcional'"*.

## Valores de ejemplo en los mockups

- **Pensionado:** Ingreso mensual por pensión $3.800.000 (helper "Valor de tu mesada pensional").
- **Independiente:** Ingreso mensual de tu actividad principal $3.000.000 (helper "Valor promedio que recibes como independiente") · Actividad principal = "Trabajo independiente o prestación de servicios" · Origen específico = "Servicio a un tercero".
- **Dependiente:** Salario básico $12.000.000 · Tipo de actividad = "Pagos adicionales" · Origen específico = "Horas extras".

## Inconsistencias detectadas en los insumos

1. ~~**Pensionado con ingresos adicionales no tiene opciones reales.**~~ → **Resuelto (2026-08-20).** La matriz definitiva le habilita Rentas de capital, Servicios independientes y Pagos adicionales. Queda únicamente el solapamiento de `Pensión → Mesada Pensional`, descrito arriba.
2. **Los valores del mockup de Independiente no están en el catálogo.** El mockup muestra "Trabajo independiente o prestación de servicios" y "Servicio a un tercero"; el catálogo oficial es `Servicios independientes` → `Prestación de servicios`. **Manda la matriz del 2026-08-20; los textos del mockup están desactualizados.**

## Pendientes declarados por el propio diseño (nota técnica)

1. **Confirmar de dónde sale cada dato de pensionado.** — abierto
2. ~~Alinearse con Gattaca sobre la parametrización de actividades: ¿Drupal o Bizagi?~~ → **Resuelto: Drupal** (2026-08-14).

Lista consolidada de preguntas abiertas del épico: [project_gestion_documental_preguntas_abiertas.md](project_gestion_documental_preguntas_abiertas.md).

## Reglas de formulario confirmadas en los mockups

- Obligatorios para avanzar: **Salario básico** y la **pregunta de otras actividades**. `Ingresos adicionales en tu trabajo` es **opcional**.
- Responder **"No"** permite avanzar sin desplegar campos adicionales.
- Responder **"Sí"** despliega 3 campos que, según los mockups, **deben diligenciarse para habilitar `Continuar`**.
- Accesibilidad: el formulario **y todos los de la bifurcación** deben ser navegables por teclado con foco visible, de izquierda a derecha.
- Opciones de los desplegables: **mín. 1 – máx. 10** (items 13, 14, 16, 17 de la matriz de Drupal).

## Revisión de la suite — versión 2 (2026-08-18)

La suite fue reescrita y **renumerada**. Cobertura v2: perfil (TC001-003), revelación Sí/No en Dependiente (TC004-007), exclusión de actividad principal (TC008-010), listados de actividades por perfil (TC011-013), **orígenes en cascada por perfil (TC014-016)** y SAP no disponible (TC017).

**Mejoras aplicadas respecto a la v1:** perfil declarado en precondiciones, valores reales del catálogo en lugar de "Actividad A/B/C", y la **cascada `Tipo de actividad` → `Origen específico` ya está cubierta** (TC014-016), que era el mayor hueco.

### 🔴 Contradicción interna: TC008 vs TC011 y TC010 vs TC013

- **TC008** (Dependiente) afirma que **no** se debe mostrar "Pagos adicionales", por ser su actividad principal.
- **TC011** (Dependiente) afirma que **sí** se debe mostrar "Pagos adicionales".
- **TC010** (Pensionado) afirma que **no** se debe mostrar "Pensión"; **TC013** afirma que **sí**.

Mismo perfil, mismo desplegable, resultados opuestos. **Los correctos son TC011 y TC013**, porque:
1. La regla de exclusión está redactada explícitamente como **"regla de negocio para independientes"**.
2. **"Actividad principal" es un campo que solo existe en el perfil Independiente** (item 16); Dependiente y Pensionado no lo tienen, así que no hay nada que excluir.
3. El **mockup del flujo Dependiente muestra el happy path** con `Tipo de actividad = "Pagos adicionales"` y `Origen = "Horas extras"`. Si TC008 fuera correcto, un Dependiente nunca podría declarar ingresos adicionales.

**Acción:** eliminar TC008 y TC010, o reconvertirlos explícitamente en el escenario abierto "qué se muestra cuando el listado queda sin opciones" (que hoy no tiene comportamiento definido). Tal como están, afirman una regla de negocio incorrecta.

**Gaps de cobertura detectados:**
1. ~~Cero casos sobre "Origen específico del ingreso"~~ → **cubierto en v2** (TC014-016). Falta todavía: (a) el **recambio** de la cascada — cambiar `Tipo de actividad` ya seleccionado y verificar que los orígenes se recarguen y se limpie el valor previo; (b) los orígenes de **"Servicios independientes"**, la segunda actividad de Independiente, que ningún caso cubre.
2. Campos obligatorios / habilitación del botón `Continuar`.
3. Persistencia o limpieza de los datos al alternar Sí → No → Sí (TC006/TC007 validan visibilidad, no el dato).
4. Validaciones del campo monetario (signo $, separador de miles, decimales, cero/negativos).
5. Accesibilidad por teclado, pese a estar documentada explícitamente.
6. Límites de parametrización: 1-10 opciones y longitudes (label 45, opciones 30 caracteres).
7. La pantalla aparece en **Paso 1 de 4** (formulario largo) y en **Paso 2 de 4** (flujos con oferta) — probar en ambos contextos.
8. Trazabilidad hacia el endpoint de documentos requeridos: que el origen seleccionado **cambie efectivamente** la lista de documentos exigidos.

### Impacto de la matriz definitiva (2026-08-20) sobre la suite

- **TC008 y TC010 quedan definitivamente inválidos.** Confirmado por la matriz: ni Dependiente ni Pensionado tienen `Actividad principal`, y ambos ven el catálogo completo de 4 tipos.
- **TC011-TC013 (listados por perfil) están cortos.** Cada uno debe aseverar **los 4 tipos de actividad**, no uno solo. Hoy TC011 asevera "Pagos adicionales" en Dependiente y TC013 "Pensión" en Pensionado: cierto, pero incompleto.
- **TC009 (exclusión en Independiente) hay que reescribirlo.** Debe verificar que tras elegir `Servicios independientes → Prestación de servicios` como principal, el tipo `Servicios independientes` **sigue apareciendo** y solo falta ese origen. Si el caso asevera que desaparece el tipo completo, está mal.
- **Falta un caso para el catálogo restringido de `Actividad principal`** en Independiente: exactamente 2 tipos (Rentas de capital, Servicios independientes), sin Pagos adicionales ni Pensión.
- **Nuevo caso de borde:** Independiente que elige `Rentas de capital` como principal — tras excluir el origen usado deben quedar los otros 2 orígenes de ese tipo.

### Casos negativos que se perdieron en la v2

La v1 tenía cuatro casos que desaparecieron: **tipo de trabajador no parametrizado**, **tipo de trabajador vacío/nulo**, **actividad duplicada** y **listado vacío**. Los dos primeros eran los de mayor valor de la suite.

> **Impacto del tipo de trabajador:** define (1) la variante de formulario, (2) qué actividades se parametrizan y (3) una de las tres dimensiones del cruce de la matriz de documentos. Un valor no mapeado rompe tres cosas aguas abajo.

**Recomendación:** no eliminarlos por estar bloqueados — dejarlos en estado *Blocked* referenciando la pregunta abierta. Un caso borrado desaparece del alcance; uno bloqueado presiona para que se defina la regla.

### Correcciones pendientes de aplicar (venían de la v1)

- **TC001-003 siguen diciendo "los campos correspondientes al perfil"** sin enumerarlos. El `Then` no es verificable. Usar las listas de la sección "Campos por perfil".
- **TC004 y TC006 siguen afirmando** que responder "No" *"permite avanzar directamente al flujo de carga documental"*. Depende del flujo: en el envío directo sí; en los voluntarios el usuario llegó tras pulsar "Aumentar monto" y responder "No" es contradictorio. Falta fijar el flujo en la precondición.

### Consistencia de datos (afecta aserciones de UI)

Los nombres del catálogo aparecen escritos de formas distintas entre casos: `Rentas de Capital` / `Rentas de capital`, `Servicios Independientes` / `Servicios independientes`, `Pension` / `Pensión`, `Rendimientos Financieros` / `Rendimientos financieros`. Deben coincidir **exactamente** con el catálogo de Drupal.

---

## Sesión 2026-08-20 — acuerdos y trazabilidad

Participantes: Andrés Duarte, Santiago Correa, David Ávalos, Carlos Humberto Gómez.

**Confirmado:**
- La **matriz completa de arriba** es la versión válida de parametrización (tipos, orígenes y reglas por perfil).
- Terminología de interfaz cerrada sobre **"Servicios independientes"**, **"actividad adicional"** y los orígenes con/sin **local comercial**.
- Se procede con **"Rentas de capital"** como selección vigente para la configuración en curso.
- Los insumos/archivos de la matriz quedan disponibles en **OneDrive**.
- Se revisó el control de **actividad principal de Independiente** y la etiqueta asociada a pensión.

**Del acta automática quedaron fragmentos sin decodificar** (la minuta viene traducida al inglés y con errores de transcripción): una mención a "10 points" de pérdida, la "IVM label" (posiblemente el rótulo de pensión — IVM = Invalidez, Vejez y Muerte) y una referencia a "museum". **No dar por buenos esos tres puntos sin confirmar con el equipo.**

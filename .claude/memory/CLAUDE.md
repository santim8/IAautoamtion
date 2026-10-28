# CLAUDE.md — IAautoamtion

Instrucciones de contexto para Claude Code. Este archivo es cargado automáticamente en cada sesión.

---

## Proyectos del workspace

Siempre se trabaja con dos proyectos en paralelo:
- **IAautoamtion** — este repositorio, automatización IA y scripts Python
- **colsubsidioFramework** — framework de automatización Java/TestNG (ruta local del usuario)

Aplica el mismo contexto, prompts y convenciones para ambos proyectos en cada sesión.

---

## Documentos de contexto (`.claude/memory/`)

Leerlos **antes** de diseñar o ejecutar pruebas del tema correspondiente:

**Gestión Documental / Zona Gris**
- [project_gestion_documental_zona_gris.md](project_gestion_documental_zona_gris.md) — épica de negocio: Caso 1 (el motor manda a Zona Gris) y Caso 2 (el usuario no acepta la oferta), campos nuevos, eliminación de Estado Civil, pantallas de ingresos y de confirmación, puntos abiertos
- [project_gestion_documental_preguntas_abiertas.md](project_gestion_documental_preguntas_abiertas.md) — **consolidado de preguntas sin resolver**, priorizadas por impacto en pruebas
- [project_gestion_documental_mapa_flujos.md](project_gestion_documental_mapa_flujos.md) — **mapa pantalla-por-pantalla de cada flujo que llega a carga documental** (se va completando flujo por flujo desde los mockups)
- [project_carga_documental_reglas_tecnicas.md](project_carga_documental_reglas_tecnicas.md) — FE/Drupal, endpoint de documentos requeridos (matriz Bizagi), trama uFlow, evento `CASE_REVIEW` y validaciones de archivos
- [project_hu_carga_documental_renderizado.md](project_hu_carga_documental_renderizado.md) — **HU 217173** (renderizado de "Información adicional + Carga"): matriz Bizagi como fuente de verdad, modal de frecuencia, `CASE_REVIEW`, delimitación con 217175/217858/223810/217180, tareas hijas y **revisión de la suite TC001-TC018**
- [project_hu217172_pantalla_ingresos.md](project_hu217172_pantalla_ingresos.md) — PBI 217172: pantalla de ingresos por tipo de trabajador (**fuente: SAP**), campos por perfil y revisión de la suite TC001-TC017
- [project_hu217171_formulario_info_personal_back.md](project_hu217171_formulario_info_personal_back.md) — **PBI 217171** (back del formulario contacto + ingresos): tipo de trabajador D/I/P/F desde `/request/check` (Bizagi `kpTipoTrabajador`), request-data por perfil y validaciones del BE, **500 en request-data de novedades** (buildBody null sin `datosFinancieros`) y riesgos (Facultativo, `codigoCampana`, tipo nulo)
- [project_hu213144_revision_documental_backoffice.md](project_hu213144_revision_documental_backoffice.md) — RF-213144: formulario del Analista en Bizagi (paneles A-G), causales de rechazo, rutas Aprobado/Devolver
- [project_hu217528_mover_campana_creacion_caso.md](project_hu217528_mover_campana_creacion_caso.md) — HU 217528: mueve XPaths de campaña de /request-data a /validate-request; evidencia parcial revisada; plan de despliegue a prod (PENDING)
- [reference_drupal_contenido_gestion_documental.md](reference_drupal_contenido_gestion_documental.md) — matriz de contenido parametrizable en Drupal (items 1-35): labels, límites de caracteres [Restringido/Sugerido] y listas editables
- [reference_flujo_actual_cupo_servicios.md](reference_flujo_actual_cupo_servicios.md) — **línea base**: mapa pantalla→servicio del flujo actual de cupo (aprobado en firme) con evidencia real, dónde se injerta Gestión Documental y qué campos ya existen en el contrato
- [reference_figma_gestion_documental.md](reference_figma_gestion_documental.md) — mockups (vigente: node-id `29654-55949`)
- [project_hu227148_derivacion_zona_gris_asistido.md](project_hu227148_derivacion_zona_gris_asistido.md) — **HU 227148** (solución temporal 2026 del Caso 1): Zona Gris → canal asistido; **estado temporal = `OFFER_RESULT` + `CASE_FOR_REVIEW`** (pantalla "Un asesor continuará…"), mockups finales, reingreso por `CASE_IN_PROGRESS_PROMOTER`, contraparte Gattaca (203293) y vacíos para QC
- [reference_contrato_notificaciones_bizagi.md](reference_contrato_notificaciones_bizagi.md) — enums `paso`/`estadoPaso` de Bizagi → plataforma, estados aceptados por paso, pantallas de error del front y valores de `canalOrigen` (código develop); **cómo probar `event-to-client` a mano** (dominio internal + x-api-key, socket `{idProducto}_{tipo}_{numero}`, DEV vs CERT)
- [reference_drawio_diagrama_hus_2026.md](reference_drawio_diagrama_hus_2026.md) — tablero draw.io por sprint (S32–S40) del Caso 1: HUs, tareas de QC del usuario, microservicio de carga + Azure AI y qué está desactualizado frente a Azure; incluye la pestaña Libre Inversión (flujo, libranza, capacidad y QC)

**Drupal (contenido parametrizable)**
- [reference_drupal_cert_mapa_contenido.md](reference_drupal_cert_mapa_contenido.md) — **cómo está armado Drupal CERT y cómo lo consume el front**: tipos de contenido → vistas REST → servicio → pantalla, qué tiene dimensión de producto (Casuísticas no), JSON armado como texto, pantallas en blanco por código faltante, flags por JSON:API y receta de QA. Acceso al admin en solo lectura con `python drupal_sesion.py login|estado|ver`

**Workflows**
- [workflow_consultar_pr.md](workflow_consultar_pr.md) — consultar Pull Requests en Azure DevOps
- [workflow_cancelar_caso.md](workflow_cancelar_caso.md) / [workflow_cancelar_caso_vigente.md](workflow_cancelar_caso_vigente.md) — cancelación de casos en Bizagi

---

## Azure DevOps

El token y la organización están en `token.txt` (en la raíz de este repo):
- `token_azure` — PAT para autenticación
- `project_azure` — `https://dev.azure.com/ColsubsidioDigital`

**Consultar una historia de usuario / PBI:**

Cuando el usuario diga `"consultar historia {ID}"` o `"consultar PBI {ID}"`:

```bash
TOKEN=$(grep token_azure token.txt | cut -d= -f2)
curl -s -u ":$TOKEN" \
  "https://dev.azure.com/ColsubsidioDigital/_apis/wit/workitems/{ID}?api-version=7.0&\$expand=all" \
  | python -m json.tool
```

Presentar la respuesta mostrando: título, estado, sprint, asignado, descripción (sin HTML), narrativa, criterios de aceptación y tareas hijas.

---

## Prompts recurrentes

### PROMPT 1 — Test de Biometría (colsubsidioFramework) — MODO RÁPIDO

Trigger: el usuario da un `id` (caso), un `{typeDocument} {identification}` y la palabra
`"biometria"`. Ejemplo de entrada:
```
id  274959

CE 212584

biometria
```

Objetivo: **ejecución lo más rápida posible, sin validar logs ni nada.**

1. Editar los `<parameter>` en `src/test/resources/suits/testng-biometry.xml`:
   - `idCaso` → número de caso (el `id`)
   - `typeDocument` → tipo de documento (CC por defecto, CE si se indica)
   - `identification` → número de documento
2. Ejecutar una sola vez, **desde la raíz del proyecto colsubsidioFramework**
   (`C:\Users\santiago.correa03\IdeaProjects\colsubsidioFramework`):
```powershell
cd C:\Users\santiago.correa03\IdeaProjects\colsubsidioFramework
mvn -o surefire:test "-Dsurefire.suiteXmlFiles=src/test/resources/suits/testng-biometry.xml"
```

**Reglas estrictas de este prompt:**
- Ejecutar SIEMPRE en `C:\Users\santiago.correa03\IdeaProjects\colsubsidioFramework`.
- NO usar `clean`, NO recompilar: solo `surefire:test` en offline (`-o`).
- NO leer, NO validar, NO resumir logs ni resultados. Lanzar y terminar.

---

### PROMPT 2 — Prueba de Cédulas API Test (colsubsidioFramework) — MODO RÁPIDO

Trigger: el usuario pega una lista de documentos `{typeDocument} {identification}` con el texto `"reemplazar en fill api y ejecuta"` o similar.

Objetivo: **ejecución lo más rápida posible, sin validar logs ni nada.**

1. Reemplazar el contenido del `DataProvider` `fillDataApi()` en
   `src/test/java/execution/data/DataProviderUtil.java` con los pares provistos
   (cada línea `TIPO\tNUMERO` → `{"TIPO", "NUMERO"},`).
2. Ejecutar una sola vez, **desde la raíz del proyecto colsubsidioFramework**
   (`C:\Users\santiago.correa03\IdeaProjects\colsubsidioFramework`):
```powershell
cd C:\Users\santiago.correa03\IdeaProjects\colsubsidioFramework
mvn -o surefire:test "-Dsurefire.suiteXmlFiles=src/test/resources/suits/testng.xml"
```

**Reglas estrictas de este prompt:**
- Ejecutar SIEMPRE en `C:\Users\santiago.correa03\IdeaProjects\colsubsidioFramework`.
- NO usar `clean`, NO recompilar: solo `surefire:test` en offline (`-o`).
- NO leer, NO validar, NO resumir logs ni resultados. Lanzar y terminar.
- No repetir entradas de datos.

**Ejemplo de entrada:**
```
CE	673434
CC	1004921429
CE	285632
```

**Resultado en `fillDataApi()`:**
```java
{"CE", "673434"},
{"CC", "1004921429"},
{"CE", "285632"},
```

---

### PROMPT 3 — Login Crédito Test (colsubsidioFramework) — SOLO REEMPLAZO

Trigger: `"login credito {typeDocument} {identification} [password]"`
(ej. `"login credito CC 1075662894 C0lsu_25#Bsid!"` o sin password
`"login credito CC 1002323232"`). También acepta el viejo `"credito login ..."` y una lista
`{typeDocument, identification, password}` con `"reemplazar en suit login test"`.

- **Password:** usar la que envíe el usuario. Si NO envía password, usar `C0lsu_25#Bsid!` por defecto.
- Soporta CC y CE.

**Acción: hacer el reemplazo y DAR el comando de consola. NO ejecutar.**

1. Reemplazar el contenido de `loginCreditoData()` en
   `src/test/java/execution/data/DataProviderUtil.java` con las filas provistas
   (`{"TIPO", "NUMERO", "PASSWORD"},`).
2. Entregar al usuario el comando para que lo corra él mismo en su consola:
```powershell
cd C:\Users\santiago.correa03\IdeaProjects\colsubsidioFramework
mvn -o surefire:test "-Dsurefire.suiteXmlFiles=src/test/resources/suits/testng-login-credito.xml"
```

**Reglas estrictas de este prompt:**
- NO ejecutar `mvn` desde el tool: los tests abren Chrome con Selenium y falla con
  `Unable to establish loopback connection` (el ChromeDriver no levanta en el sandbox).
- Solo editar el DataProvider y devolver el comando de consola. La ejecución la hace el usuario.

**Ejemplo de entrada:**
```
credito login CC 1002323232
```

**Resultado en `loginCreditoData()`:**
```java
{"CC", "1002323232", "C0lsu_25#Bsid!"},
```

**Ejemplo de entrada:**
```
credito login CC 1002323232
```

**Resultado en `loginCreditoData()`:**
```java
{"CC", "1002323232", "C0lsu_25#Bsid!"},
```

**Ejemplo de entrada:**
```
CC	1095915781	C0lsu_25#Bsid!
CC	52966724	C0lsu_25#Bsid!
CC	1097397286	C0lsu_25#Bsid!
```

**Resultado en `loginCreditoData()`:**
```java
{"CC", "1095915781", "C0lsu_25#Bsid!"},
{"CC", "52966724", "C0lsu_25#Bsid!"},
{"CC", "1097397286", "C0lsu_25#Bsid!"},
```

---

### PROMPT 4 — Generar Test Cases

Para crear casos de prueba a partir de una historia de usuario:

**Archivo fijo (se reemplaza por cada historia, NO se versiona por historia):**
- `test_cases.json` en la raíz del repo

**Flujo:**
1. Cuando el usuario diga `"crear test cases"` o similar para una historia, Claude:
   - Genera/sobreescribe `test_cases.json` con los casos en formato JSON estructurado
   - Cada caso tiene `title` y `steps[]` con `action` + `expected`
   - El primer paso siempre son las "Precondiciones"
2. Ya no hay exportación a Excel (se quitó `create_testcases_automation.py` el
   2026-10-20 para que el repo se pueda compartir sin pandas ni OpenAI). Si piden
   el Excel para Azure DevOps, avisar que esa lógica ya no está en el repo.

**Formato JSON esperado:**
```json
[
  {
    "title": "TC001 - Descripción corta",
    "steps": [
      {"action": "Precondiciones:\n- condición 1", "expected": ""},
      {"action": "Given ...", "expected": ""},
      {"action": "When ...", "expected": ""},
      {"action": "Then ...", "expected": "resultado esperado"}
    ]
  }
]
```

El propósito del archivo fijo es **no llenar el repositorio** con información de cada historia.

---

### PROMPT 5 — Consultar Bizagi

Cuando el usuario diga `"consultar bizagi {identification}"` o `"consultar bizagi CE {identification}"`:

```bash
# CC (por defecto)
python bizagi_automator.py {identification}

# CE
python bizagi_automator.py CE {identification}
```

Ejecutar desde la raíz de este repositorio (IAautoamtion).

**Ejemplos de triggers:**
- `"consultar bizagi 41336668"` → `python bizagi_automator.py 41336668`
- `"consultar bizagi CE 41336668"` → `python bizagi_automator.py CE 41336668`

---

### PROMPT 6 — Cancelar Caso (Bizagi headless + API cancel)

Cuando el usuario diga `"cancelar caso {identification} {token}"` o `"cancelar caso CE {identification} {token}"`:

```bash
# CC (por defecto)
python cancel_case_workflow.py {identification} {token}

# CE
python cancel_case_workflow.py CE {identification} {token}
```

El script hace dos pasos en secuencia:
1. Consulta Bizagi en modo headless para obtener el `idCaso` de la última solicitud del documento
2. Llama al endpoint `POST /loans/req-mgr/external/v1/product/2/request/cancel-request` con ese `idCaso`

**Nota:** El token de autorización se vence cada 2 horas; el usuario lo provee en cada invocación.

---

### PROMPT 7 — Cancelar Caso vía Bizagi UI (sin token)

Cuando el usuario diga `"cancelar caso bizagi {identification}"`, `"cancelar con bizagi {identification}"` o `"cancelar caso bizagi CE {identification}"`:

```bash
# CC (por defecto)
python bizagi_cancel_case.py {identification}

# CE
python bizagi_cancel_case.py CE {identification}

# Headless opcional
python bizagi_cancel_case.py --headless {identification}
```

A diferencia de PROMPT 6, este flujo cancela el caso desde la UI de Bizagi (Admin → Administración de procesos) y **no requiere token**.

**Ejemplos:**
- `"cancelar caso bizagi 41336668"` → `python bizagi_cancel_case.py 41336668`
- `"cancelar caso bizagi CE 41336668"` → `python bizagi_cancel_case.py CE 41336668`

---

### PROMPT 7B — Cancelar Caso Bizagi MODO RÁPIDO (headless)

Trigger: `"cancelar caso rapido {identification}"` o `"cancelar caso rapido CE {identification}"`.

Objetivo: **lanzar el comando y terminar, sin validar logs ni nada.** Corre headless.

```bash
# CC (por defecto)
python bizagi_cancel_case.py CC {identification} --headless

# CE
python bizagi_cancel_case.py CE {identification} --headless
```

**Reglas de este prompt:**
- Ejecutar desde la raíz de este repo (IAautoamtion).
- Siempre con `--headless`. Debe funcionar para CC y CE (CC por defecto si no se indica tipo).
- Rápido, pero SÍ se lee la salida para dar el **status de la cancelación** (este es el único
  reporte que se entrega; no resumir nada más).

**Status a reportar (leer la última solicitud / caso del log):**
- **NO encontrado** → si la salida contiene `ERROR: Error al cancelar el caso {N}` con
  `Page.wait_for_selector: Timeout ... waiting for locator("input[type="checkbox"]...value="{N}"")`:
  reportar que **no se encontró el caso {N}** y mostrar el número de caso que intentó buscar.
- **Cancelado OK** → si la salida contiene la secuencia
  `Checkbox del caso {N} marcado` → `Botón Cancelar presionado para caso {N}` →
  `Confirmación de cancelación aceptada para caso {N}`:
  reportar que **se encontró y canceló el caso {N}**.

**Ejemplos:**
- `"cancelar caso rapido CE 212584"` → `python bizagi_cancel_case.py CE 212584 --headless`
- `"cancelar caso rapido 41336668"` → `python bizagi_cancel_case.py CC 41336668 --headless`

---

### PROMPT 7C — Consultar Caso Bizagi (deja pantalla abierta)

Trigger: `"consultar caso {tipo}-{identification}"`, `"consultar caso {tipo} {identification}"`,
o `"consultar bizagi caso {tipo} {identification}"` (ej. `"consultar caso CE-212584"`).

**Siempre usar `bizagi_consultar_caso.py` (deja la pantalla abierta para interactuar), NUNCA
`bizagi_automator.py` para estos triggers** — ese cierra el navegador tras consultar.
Lanzar con el navegador visible en la sesión del usuario (background + sandbox desactivado).

Script: `bizagi_consultar_caso.py` (reusa la clase `BizagiAutomator` de `bizagi_cancel_case.py`).
Corre el flujo **solo hasta obtener la última solicitud** (`obtener_ultima_solicitud`) y **deja el
navegador abierto** (no headless) para que el usuario interactúe. NO navega a Admin ni cancela.

```bash
# CE
python bizagi_consultar_caso.py CE-212584
python bizagi_consultar_caso.py CE 212584

# CC (por defecto)
python bizagi_consultar_caso.py 1075662894
```

**Notas:**
- Acepta el documento con guion (`CE-212584`) o con espacio (`CE 212584`).
- Soporta CC y CE (CC por defecto si no se indica tipo).
- El script queda esperando un Enter en consola para cerrar el navegador.
- A partir de aquí el usuario va indicando qué hacer (ampliable luego).

---

### PROMPT 7D — Bizagi por API (sin navegador, sin formulario de login)

Trigger: cualquier consulta a Bizagi que no pida ver la pantalla: `"solicitudes bizagi {tipo} {identification}"`,
`"json del caso {N}"`, `"en qué va el caso {N}"`, `"¿se puede cancelar el caso {N}?"`. Claude lo corre solo.

`bizagi_api.py` le pega a los mismos servicios REST que llama el portal (lo que hacen los PROMPT 7/7B/7C
y `bizagi_consultar_json.py`, pero en 1–4 s y sin selectores):

```bash
python bizagi_api.py solicitudes [CE] {identification}   # GCR_Solicitudes - Promotor, la más reciente primero
python bizagi_api.py json {N}                            # GCR_Solicitudes - Analista operativo (fila completa)
python bizagi_api.py caso {N}                            # buscador superior: proceso, subprocesos, abortado o no
python bizagi_api.py admin {N}                           # Administración de procesos: ¿está en curso?
python bizagi_api.py cancelar {N}                        # en seco: dice qué cancelaría
python bizagi_api.py cancelar {N} --confirmar            # cancela (Rest/Cases/Abort) — pedir OK antes
python bizagi_api.py navegador                           # Chromium ya logueado con la sesión
```

**Sesión:** `POST /Api/Authentication/User` con `BIZAGI_USER`/`BIZAGI_PASSWORD` del entorno → cookie
`.BZAUTH` + token `X-BZXSRF-TOKEN` (sale de `/Rest/Users/CurrentUserGuid`), guardados en
`~/.panel_qa/bizagi_sesion.json`. Se vence a los 20 min sin uso y el script la renueva solo. Sin
credenciales en el entorno: `python bizagi_api.py login --cookie ".BZAUTH=..."` con la cookie
copiada de DevTools. Para Playwright: `from bizagi_api import abrir` da un contexto ya logueado.

**Cancelar (probado el 26/10 con 322388, 322390 y 322392):** responde `"deleted": true`, el caso queda
`isAborted` y sale de Administración de procesos, y `/request/check` del documento da 404 (la cédula
queda libre). El estado de negocio (`kpEstado` en Analista operativo) **se queda como estaba**
("Solicitud activa"): cancelar desde admin aborta el proceso sin pasar por la actividad "Cancelar
Solicitud". El botón del portal hace lo mismo (ver 298982: abortado y "Solicitud activa - En
validación biométrica").

**Ojo con "última solicitud":** el portal no ordena la tabla por fecha (la más nueva primero y el
resto ascendente), así que "última fila de la página 2" de `bizagi_cancel_case.py` puede no ser la
más reciente (CC 80057089 el 26/10: tomó 319407 y la más nueva era 320814). `solicitudes` ordena
por fecha de creación.

---

## Feature Flags CERT

> **Desde el 2026-10-02 las 4 URLs de abajo responden 404**: CloudFront las manda a S3, aunque la vista sigue existiendo en Drupal. Mientras se arregla, leer los flags por JSON:API (no requiere sesión):
> `curl -s "https://platform-test-external.colsubsidio.com/loans-cert-admin-solicitud/jsonapi/node/mantaince_window?fields%5Bnode--mantaince_window%5D=field_feature_flag,field_feature_flag_inc_reac,field_fflag_incr,field_maintenance_window,changed"`
> Campos: `field_feature_flag` = CIAM, `field_fflag_incr` = incremento, `field_feature_flag_inc_reac` = reactivación, `field_maintenance_window` = mantenimiento. Detalle en [reference_drupal_cert_mapa_contenido.md](reference_drupal_cert_mapa_contenido.md).

### CIAM
- **Trigger:** "está activo ciam" / "consultar ciam"
- **URL:** `https://platform-test-external.colsubsidio.com/loans-cert-admin-solicitud/api_creditos/parametros/drupal_auth_strategy_feature_flag`
- **Campo:** `drupalAuthStrategyFeatureFlag`

### Novedades (combinado)
- **Trigger:** "está activo novedades" / "consultar novedades"
- **URL:** `https://platform-test-external.colsubsidio.com/loans-cert-admin-solicitud/api_creditos/parametros/feature_flag_increment_and_reactivation`
- **Campo:** `featureFlagIncrementAndReactivation`

### Incremento (independiente)
- **Trigger:** "está activo incremento" / "consultar flag incremento"
- **URL:** `https://platform-test-external.colsubsidio.com/loans-cert-admin-solicitud/api_creditos/parametros/feature_flag_increment`
- **Campo:** `featureFlagIncrement`

### Reactivación (independiente)
- **Trigger:** "está activo reactivación" / "consultar flag reactivación"
- **URL:** `https://platform-test-external.colsubsidio.com/loans-cert-admin-solicitud/api_creditos/parametros/feature_flag_reactivation`
- **Campo:** `featureFlagReactivation`

No requieren autenticación. Responden `true` o `false`.

**Nota:** el servicio `card-validations` lee los flags desde Drupal, no desde Split. Si Split muestra ON pero Drupal retorna false, el servicio usa el valor de Drupal. Siempre verificar con estos endpoints ante comportamientos inesperados.

```bash
curl -s <URL>
```

---

### PROMPT 8 — Consultar Pull Request (Azure DevOps)

Cuando el usuario diga `"ver PR {repo} {número}"`, `"consultar PR {número}"` o muestre un PR de Azure DevOps:

**Paso 1 — Buscar el repo ID:**
```bash
TOKEN=$(grep token_azure token.txt | cut -d= -f2)
curl -s -u ":$TOKEN" \
  "https://dev.azure.com/ColsubsidioDigital/Ecosistema%20Digital%20Cr%C3%A9dito%20y%20Seguros/_apis/git/repositories?api-version=7.0" \
  | python -c "import sys,json; repos=json.load(sys.stdin)['value']; [print(r['id'], r['name']) for r in repos if '{repo}' in r['name'].lower()]"
```

**Paso 2 — Consultar el PR:**
```bash
TOKEN=$(grep token_azure token.txt | cut -d= -f2)
curl -s -u ":$TOKEN" \
  "https://dev.azure.com/ColsubsidioDigital/Ecosistema%20Digital%20Cr%C3%A9dito%20y%20Seguros/_apis/git/repositories/{repo_id}/pullrequests/{pr_number}?api-version=7.0" \
  | python -m json.tool
```

**Nota:** Si el número de PR en la pantalla tiene más dígitos (ej. 122464), el número real en Azure DevOps puede ser sin el primer dígito (ej. 22464). Listar los PRs del repo para confirmar:
```bash
TOKEN=$(grep token_azure token.txt | cut -d= -f2)
curl -s -u ":$TOKEN" \
  "https://dev.azure.com/ColsubsidioDigital/Ecosistema%20Digital%20Cr%C3%A9dito%20y%20Seguros/_apis/git/repositories/{repo_id}/pullrequests?searchCriteria.status=all&api-version=7.0" \
  | python -c "import sys,json; prs=json.load(sys.stdin)['value']; [print(p['pullRequestId'], p['title'][:80]) for p in prs]"
```

**Siempre consultar TODA la información del PR en este orden:**
1. Datos generales (título, estado, autor, fechas, ramas, ticket vinculado, reviewers)
2. Descripción completa (cambios realizados, tipo de cambio, checklist, cómo se probó)
3. Leer el diff/archivos modificados si es posible
4. Presentar resumen estructurado con todos los puntos anteriores

**Repo IDs conocidos:**
- `app-cre-product-eligibility-api` → `51a68bfb-dbe2-49ba-9bcf-1fb3ba285dbf`

---

### PROMPT 9 — Validador E2E (Claude recorre el flujo y entrega el reporte)

Trigger: `"valida e2e {tipo} {identification}"`, `"corre el e2e"`, `"valida el despliegue"`,
`"valida esta cédula de punta a punta"`. Claude lo corre solo (sin clave: sesión por token).

**Antes de correr, preguntar si se quiere ver en vivo o no** (si no lo dijo ya):
- **En vivo:** sin `--headless` y con `--lento 500` (pausa antes de cada clic y de lo que se escribe), lanzado
  en el panel de Terminal del QA para que vea la ventana y la consola.
- **Headless:** con `--headless`.
- En los dos casos se genera el reporte y se entrega su ruta absoluta.

```bash
# Consumo Libre Inversión en dev, hasta políticas (default: no pulsa Continuar, no crea caso)
python -m colsubsidio_flow e2e --documento CC:39712148 --headless

# En vivo
python -m colsubsidio_flow e2e --documento CC:39712148 --lento 500

# Otro subproducto o Cupo; qa = front de la rama qa con back de CERT
python -m colsubsidio_flow e2e --documento CC:n --slug mujeres --headless
python -m colsubsidio_flow e2e --documento CC:n --entrada cupo --base https://dev.colsubsidio.com/creditos/solicitud --headless

# Más allá de políticas: pulsa Continuar (CREA EL CASO en Bizagi) y sigue; pedir OK antes
python -m colsubsidio_flow e2e --documento CC:n --hasta fin --headless
```

- Opciones: `--hasta politicas|informacion-personal|personalizacion-oferta|datos-adicionales|biometria|fin`,
  `--rapido` (en políticas solo marca y sigue), `--lento 500` (en vivo), `--respuesta si`, `--sin-biometria`,
  `--dispositivo "Pixel 7"`. Sin `--documento` corre el data provider `e2e` de `cedulas.json`.
- **"Logueate y déjame la pantalla abierta en X":** `--hasta X --dejar-abierto` sin `--headless`. Claude
  entra, valida hasta X y deja la ventana ahí con el observador grabando; lo que el QA haga a mano entra al
  reporte (sección "a mano"), que se escribe al **cerrar la ventana** o con Enter en la consola. Con
  `--cdp 9333` además queda expuesta para que otro proceso se enganche (`politicas-225427 --conectar 9333`).
  ```bash
  python -m colsubsidio_flow e2e --documento CC:39712148 --hasta politicas --rapido --lento 500 --dejar-abierto
  ```
- Antes de entrar consulta `/request/check` (dev: d2b80 `product/{1|2}`; qa: CERT): con caso en curso el
  front hace **retoma** y no pasa por validaciones; el validador lo dice y sigue desde donde caiga.
- Valida: validaciones como `validaciones-225425`, políticas como `politicas-225427`, cada pantalla
  siguiente (servicio con su status y paso OK del socket de Bizagi) y, al cerrar, ningún 5xx/CORS/sin
  respuesta ni `stepStatus FAIL`. Los defectos ya reportados están en `CONOCIDOS` de
  `colsubsidio_flow/tests/e2e_test.py` y no tumban el veredicto (`PASA`, `PASA CON CONOCIDOS`, `FALLA`).
- **Reporte:** `evidences/e2e_<producto>_<numero>_<fecha>/reporte.html` = el del observador con el bloque
  del validador arriba (veredicto, checks por pantalla, pantallazos), más `validador.json` y `final.png`.
- **Qué entregar:** el veredicto, los FAIL nuevos con su pantalla y **siempre la ruta absoluta completa
  del reporte** (`C:\...\evidences\e2e_...\reporte.html`), en texto, además del archivo. Los CONOCIDO
  solo en una línea.
- Las pantallas después de políticas se armaron con la corrida de Cupo del 15/10 en qa y no se han
  podido correr. El 28/10 dev ya pasa de políticas (el socket manda `VALIDATION OK`), pero
  `informacion-personal` de Consumo muestra "Cód. error 500".
- Con `--hasta` más allá de políticas, o si el QA pulsa Continuar a mano, la cédula queda con caso y
  la siguiente corrida cae en retoma. Usar las libres del data provider `e2e` y revisar `/request/check`.

---

## Convenciones generales

- Ejecutar tests una sola vez, sin validación adicional posterior salvo que se pida explícitamente
- Al correr biometría o API test, reportar el resultado resumido (passed/failed + errores relevantes del servidor)
- Para consultas de Azure DevOps, leer el token siempre desde `token.txt` en este repo
- Nuevas memorias y prompts se guardan en este archivo (`CLAUDE.md`) para que el equipo los comparta

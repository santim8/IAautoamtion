# CLAUDE.md — IAautoamtion

Instrucciones de contexto para Claude Code. Este archivo es cargado automáticamente en cada sesión.

---

## Proyectos del workspace

Siempre se trabaja con dos proyectos en paralelo:
- **IAautoamtion** — este repositorio, automatización IA y scripts Python
- **colsubsidioFramework** — framework de automatización Java/TestNG (ruta local del usuario)

Aplica el mismo contexto, prompts y convenciones para ambos proyectos en cada sesión.

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

### PROMPT 4 — Generar Test Cases (Excel para Azure DevOps)

Para crear casos de prueba a partir de una historia de usuario y exportarlos a Excel listo para importar a Azure DevOps:

**Archivos fijos (se reemplazan por cada historia, NO se versionan por historia):**
- Entrada: `test_cases.json` en la raíz del repo
- Salida: `test_cases.xlsx` en la raíz del repo

**Flujo:**
1. Cuando el usuario diga `"crear test cases"` o similar para una historia, Claude:
   - Genera/sobreescribe `test_cases.json` con los casos en formato JSON estructurado
   - Cada caso tiene `title` y `steps[]` con `action` + `expected`
   - El primer paso siempre son las "Precondiciones"
2. Cuando el usuario diga `"transformar"` o `"exportar"`:
   ```bash
   python create_testcases_automation.py
   ```
   Genera `test_cases.xlsx` que sobreescribe el anterior.

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

El propósito de archivos fijos es **no llenar el repositorio** con información de cada historia.

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

## Feature Flags CERT

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

## Convenciones generales

- Ejecutar tests una sola vez, sin validación adicional posterior salvo que se pida explícitamente
- Al correr biometría o API test, reportar el resultado resumido (passed/failed + errores relevantes del servidor)
- Para consultas de Azure DevOps, leer el token siempre desde `token.txt` en este repo
- Nuevas memorias y prompts se guardan en este archivo (`CLAUDE.md`) para que el equipo los comparta

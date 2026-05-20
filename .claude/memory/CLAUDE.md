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

### PROMPT 1 — Test de Biometría (colsubsidioFramework)

Cuando el usuario diga `"biometria caso {idCaso} {identification}"` o similar:

1. Editar `src/test/resources/suits/testng-biometry.xml` con:
   - `idCaso` → número de caso
   - `identification` → número de documento
   - `typeDocument` → tipo de documento (CC por defecto, CE si se indica)
2. Ejecutar:
```bash
mvn clean test -Dsurefire.suiteXmlFiles=src/test/resources/suits/testng-biometry.xml
```

Ejecutar una sola vez, sin validación posterior.

---

### PROMPT 2 — Prueba de Cédulas API Test (colsubsidioFramework)

Cuando el usuario pase una lista de documentos `{typeDocument, identification}` para testng.xml:

1. Reemplazar el contenido de `fillDataApi()` en `src/test/java/execution/data/DataProviderUtil.java` con los pares provistos
2. Ejecutar:
```bash
mvn clean test "-Dsurefire.suiteXmlFiles=src/test/resources/suits/testng.xml"
```

Ejecutar una sola vez, no repetir entradas de datos.

---

### PROMPT 3 — Login Crédito Test (colsubsidioFramework)

Cuando el usuario pase una lista de documentos `{typeDocument, identification, password}` con el texto `"reemplazar en suit login test"` o similar:

1. Reemplazar el contenido de `loginCreditoData()` en `src/test/java/execution/data/DataProviderUtil.java` con las filas provistas
2. Archivo de suite: `C:\Users\santiago.correa03\IdeaProjects\colsubsidioFramework\src\test\resources\suits\testng-login-credito.xml`
3. Ejecutar:
```bash
mvn clean test "-Dsurefire.suiteXmlFiles=src/test/resources/suits/testng-login-credito.xml"
```

Ejecutar una sola vez, no repetir entradas de datos.

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

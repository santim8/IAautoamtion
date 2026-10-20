# Panel QA

Ventana local para lanzar los scripts de este repo sin pasar por la consola.
Doble clic en `panel.bat`.

## Pestañas

| pestaña | qué hace |
|---|---|
| Observador de flujos | navegas a mano en Chrome; captura pantallas, requests y websocket |
| Analitica dataLayer | navegas a mano en Chrome; anota cada push al `dataLayer` y lo valida contra `analitica/modelo_de_datos[*].json` |
| Suite biometría | autenticación biométrica + firma de documentos, pegando directo a los endpoints REST |
| Cancelar caso Bizagi | busca la última solicitud del documento y la cancela |
| Consultar caso Bizagi | muestra la última solicitud y deja el navegador abierto |
| Consultar JSON | busca por Id de caso en *GCR_Solicitudes - Analista operativo* y vuelca la fila como JSON |
| Validaciones API | corre los ~14 servicios de elegibilidad contra una lista de documentos, en paralelo |
| Usuarios | libreta de usuarios de prueba |
| Corridas | evidencia acumulada; abre reportes y los regenera |

## Instalación

Necesitas Python 3.10 o superior con `tkinter` (viene en el instalador oficial
de python.org).

```
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Después, para saber qué le falta a la máquina y qué pestaña deja de andar por
eso (no instala ni cambia nada):

```
python verificar_entorno.py
```

Para levantar el front de Consumo en local (`front-consumo-local` en
`.claude/launch.json`), el clon va en `~/qa-front-consumo` o donde diga la
variable `QA_FRONT_DIR`.

## Configuración

Qué pide cada pestaña, para no configurar de más:

| pestaña | qué necesita |
|---|---|
| Observador de flujos · Analítica dataLayer | nada; se engancha al Chrome de la máquina |
| Validaciones API · Suite biometría | `token.txt` con las 6 claves de elegibilidad |
| Cancelar caso · Consultar caso · Consultar JSON | `BIZAGI_USER` y `BIZAGI_PASSWORD` de entorno (y un Chromium que el panel baja solo la primera vez) |
| Usuarios · Corridas | nada |

Son dos mecanismos distintos y ninguno cubre al otro: `token.txt` no sirve para
Bizagi y las variables de entorno no sirven para elegibilidad.

### Credenciales de Bizagi

Los scripts de Bizagi las exigen por variable de entorno; no hay valor por
defecto. Una sola vez, en PowerShell, y luego abre una consola nueva:

```
setx BIZAGI_USER "tu.usuario"
setx BIZAGI_PASSWORD "tu.clave"
```

### Secretos de los servicios de elegibilidad

Las pestañas **Validaciones API** y **Suite biometría** pegan directo a los
endpoints REST. No dependen de `colsubsidioFramework` ni de Maven: son puertos
en Python (`validaciones_api.py` y `biometria_api.py`) que solo necesitan
`curl`, que en Windows 10/11 ya viene instalado.

Lo único que hay que poner son las claves, en un `token.txt` que no se versiona:

```
copy token.example.txt token.txt
```

`token.example.txt` lista cuál es cada una. Si falta alguna, el mensaje de
error dice exactamente qué línea agregar.

El archivo va en la raíz del repo (al lado de `panel.bat`); si usás el `.exe`,
al lado del `.exe`. Las claves no viajan ni en el repo ni dentro del ejecutable:
pedíselas a quien ya tenga el panel andando.

## Dónde queda todo

| ruta | contenido |
|---|---|
| `evidences/` | una carpeta por corrida del observador (no se versiona) |
| `observador/` | código del observador de flujos; `observador_flujo.py` es solo el punto de entrada. El mapa de módulos y dónde se agrega cada cosa (endpoint, complemento, salida) está en `observador/__init__.py` |
| `esquemas_servicios.json` | contrato observado de cada servicio; **sí se versiona** |
| `~/.panel_qa/usuarios_prueba.json` | usuarios de prueba, con sus claves en claro |
| `colsubsidio_flow/data/cedulas.json` | cédulas de los tests UI por data provider, sin claves; **sí se versiona** |
| `~/.panel_qa/backups/` | copia previa a cada guardado |
| `~/.panel_qa/logs/` | log completo de cada corrida |

Los usuarios viven fuera del repo a propósito: dentro, un `git clean -fdx` se
los llevaría por delante.

## Tests UI (`colsubsidio_flow`)

Puerto a Playwright de la capa UI de colsubsidioFramework: los page objects de
login, onboarding y solicitud, el data provider y los tests de login. La tabla
Java → Python está en `colsubsidio_flow/__init__.py`.

```
python -m colsubsidio_flow tests                       # qué tests hay
python -m colsubsidio_flow cedulas listar              # cédulas por data provider
python -m colsubsidio_flow cedulas agregar consumo_225423 CC:123 --nota "..."
python -m colsubsidio_flow consumo-225423              # corre todas las del data provider
python -m colsubsidio_flow login-credito-light --documento CC:123 --capturas evidences/light
```

La clave de cada cédula se toma de `~/.panel_qa/usuarios_prueba.json` (la
pestaña Usuarios del panel), o de `COLS_CLAVE`, o se pide por consola.
`--hasta-login` recorre hasta el formulario de login sin pedir clave.
Sin `--capturas` no se guarda ningún pantallazo.

## Colecciones de Bruno

Las colecciones del repo ya están en formato Bruno (una carpeta con un
`bruno.json` y un `.bru` por request), así que no se importan: se **abren**.
Bruno trabaja sobre esos mismos archivos, sin copiarlos a otro lado.

| carpeta | en Bruno se llama | qué tiene | environments |
|---|---|---|---|
| `bruno/validate-request/` | `request_colsubsidio` | validaciones de afiliación, tarjeta y SIIF; request check, request data y validate request; novedades, Bizagi, Gigya (crear usuario y lote) y biometría por pasos | `test`, `CERT`, `registro-dev` |
| `bruno/biometria/` | `biometria` | biometría completa (pasos 1 a 3) en un solo request | ninguno |
| `bruno/notification-service/` | `notification-service` | TC-01 a TC-30 y TC-CAP de correos y SMS | `CERT`, `colsubsidio-test` |
| `test_services/test_A02/bruno/` | `activation-file` | token de Apigee y archivo A02 (activación/aumento) | `test` |

### Abrir una colección

1. Instala Bruno de escritorio desde <https://www.usebruno.com/downloads>.
2. **Open Collection** (en la pantalla de inicio o en el menú `···` de la barra
   lateral) y elige la carpeta que tiene el `bruno.json`. Ni la raíz del repo
   ni `bruno/` son colecciones: Bruno no las abre.
3. La primera vez pregunta el modo de JavaScript: **Safe Mode**. Los scripts del
   repo están escritos para ese modo: `require("axios")` funciona, pero
   `URLSearchParams`, `URL`, `fetch` y `Buffer` no existen. Se cambia después
   desde la configuración de la colección.
4. Arriba a la derecha, cambia *No Environment* por el environment que toque.

Se repite el paso 2 por cada colección.

### Lo que no viene con el clon

- **Variables secretas.** Las que un environment declara en `vars:secret`
  Bruno las guarda cifradas en la máquina, no en el `.bru`, así que llegan
  vacías. Se cargan a mano en *Environment Settings*:

  | colección | environment | variables |
  |---|---|---|
  | `request_colsubsidio` | `CERT` | `token` |
  | `request_colsubsidio` | `test` | `gigyaLoginToken`, `gigyaGmid`, `gigyaUcid` |

  El resto (URLs, `x-api-key`, credenciales de Apigee) está en el archivo del
  environment y llega con el repo.
- **El CSV del lote de Gigya.** `bruno/validate-request/data/` no se versiona;
  `python usuarios.py exportar bruno` arma el CSV de *Crear Usuarios
  Lote[Gigya]* (ver `README_PANEL.md`).

Todo lo que cambies en Bruno (un body, un request nuevo, un valor del
environment) queda escrito en los `.bru` y aparece en `git status`. Los tokens
que se renuevan seguido (`token`, `tokenCIAM`, `tokenApegee`) viven en el
environment `test`: conviene mirar ese diff antes de commitear.

### Importar desde Postman o Insomnia

**Import Collection** es para archivos de otras herramientas (Postman,
Insomnia, OpenAPI): eliges el formato, el archivo y la carpeta donde Bruno crea
la colección nueva, ya convertida a `.bru`. En el repo hay dos:

| archivo | formato | equivalente en Bruno |
|---|---|---|
| `insomnia/Biometria_Completa.json` | Insomnia (export v4) | `bruno/biometria/` |
| `test_services/test_event_to_client/event-to-client.postman_collection.json` | Postman | `Event To Client[WEBSOCKET].bru` en `bruno/validate-request/` |

Como los dos ya tienen su versión en Bruno, importarlos crea una copia aparte.
Si importas algo nuevo para versionarlo, guárdalo en `bruno/<nombre>/`.

### Desde consola

```
npm install -g @usebruno/cli
cd bruno/notification-service
bru run --env CERT
bru run "TC-01 EMAIL CUPO_CREDITO_APROBADO.bru" --env CERT
bru run --env CERT --reporter-json results.json --reporter-html results.html
```

`bru run` se corre parado en la carpeta de la colección (la del `bruno.json`).
Si PowerShell no deja correr `bru` por la execution policy, usa `bru.cmd`: es
lo que hace `python usuarios.py crear-ciam` por dentro.

## Notas de uso

**Detener y generar reporte** no mata el proceso: le pide al observador que
cierre por el mismo camino que `Ctrl+C`, para que alcance a escribir el reporte,
el último pantallazo y la validación de esquemas. Si el navegador no responde,
a los 20 segundos el observador genera el reporte igual y sale.

Si una corrida quedara sin `reporte.html`, en **Corridas** la seleccionas y le
das **Revalidar**: se reconstruye desde los `.jsonl`, que se escriben mientras
navegas.

El checkbox **Tomar esta corrida como baseline de esquemas** viene desmarcado a
propósito. Marcarlo funde lo observado con el baseline y puede revertir
correcciones hechas a mano en `esquemas_servicios.json`.

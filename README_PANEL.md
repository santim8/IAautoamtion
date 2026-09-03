# Panel QA

Ventana local para lanzar los scripts de este repo sin pasar por la consola.
Doble clic en `panel.bat`, o usa el `.exe` (ver *Repartirlo como aplicación*).

## Pestañas

| pestaña | qué hace |
|---|---|
| Observador de flujos | navegas a mano en Chrome; captura pantallas, requests y websocket |
| Suite biometría | corre `testng-biometry.xml` del framework Java con los datos que pongas |
| Cancelar caso Bizagi | busca la última solicitud del documento y la cancela |
| Consultar caso Bizagi | muestra la última solicitud y deja el navegador abierto |
| Validaciones API | reemplaza la lista del `DataProvider` y corre `ApiTest` |
| Usuarios | libreta de usuarios de prueba |
| Corridas | evidencia acumulada; abre reportes y los regenera |

## Instalación

Necesitas Python 3.10 o superior con `tkinter` (viene en el instalador oficial
de python.org).

```
pip install -r requirements.txt
playwright install chromium
```

## Configuración

### Credenciales de Bizagi

Los scripts de Bizagi las exigen por variable de entorno; no hay valor por
defecto. Una sola vez, en PowerShell, y luego abre una consola nueva:

```
setx BIZAGI_USER "tu.usuario"
setx BIZAGI_PASSWORD "tu.clave"
```

### Framework Java (opcional)

Las pestañas **Suite biometría** y **Validaciones API** necesitan el repo
`colsubsidioFramework` y Maven en el PATH. Si no están, esas pestañas
simplemente no aparecen y el resto del panel funciona igual.

Por defecto se busca en `~/IdeaProjects/colsubsidioFramework`. Si lo tienes en
otro lado, copia `panel.config.example.json` a `panel.config.json` y ajusta la
ruta, o define la variable `COLSUBSIDIO_FRAMEWORK`.

## Repartirlo como aplicación

Para quien no tiene Python ni va a clonar el repo:

```
construir_exe.bat
```

Deja `dist\PanelQA.exe` (~54 MB). Se reparte la carpeta `dist\` completa y se
abre con doble clic; no necesita Python, ni Playwright, ni el repo.

**Dónde escribe.** Junto al `.exe`: `evidences\`, `esquemas_servicios.json`,
`panel.config.json`. Los usuarios de prueba siguen en `~/.panel_qa/`, igual que
desde el repo. Conviene dejarlo en una carpeta propia y no en Descargas.

**El navegador de Playwright no viaja dentro.** Solo lo usan las dos pestañas de
Bizagi, que abren su propio Chromium; el observador se engancha por CDP al
Chrome de verdad y no lo necesita. La primera vez que se usa una pestaña de
Bizagi, el panel lo baja solo a `~/.panel_qa/browsers` (~150 MB, unos minutos,
una sola vez). Si la máquina ya tiene uno de un `playwright install` previo, lo
reutiliza y no baja nada.

**Las pestañas de Java** (Suite biometría, Validaciones API) siguen necesitando
Maven y el repo `colsubsidioFramework` en la máquina. Si no están, no aparecen.

**Ojo al empaquetar:** `panel.spec` lista los datos uno por uno a propósito.
`token.txt` (el PAT de Azure DevOps) vive en esta carpeta, y meter `(".", ".")`
lo metería dentro del `.exe` que se reparte. No lo cambies por un comodín.

## Usuarios de prueba compartidos

`usuarios_compartidos.json` viaja en el repo. La primera vez que abres la
pestaña **Usuarios** después de clonar, ese catálogo siembra tu archivo local y
a partir de ahí cada quien maneja el suyo.

| botón | qué hace |
|---|---|
| Traer del repo | agrega los del catálogo que aún no tengas |
| Publicar al repo | reescribe el catálogo con tu lista actual |

**Las contraseñas no se publican por defecto.** El checkbox *Publicar también
las contraseñas* las incluye, pero entonces quedan en el historial de git de
forma permanente: borrar el archivo después no las quita. Con el checkbox
apagado se comparte todo lo demás y cada quien completa las claves en su
archivo local.

Después de publicar hay que commitear `usuarios_compartidos.json` a mano.

## Dónde queda todo

| ruta | contenido |
|---|---|
| `evidences/` | una carpeta por corrida del observador (no se versiona) |
| `esquemas_servicios.json` | contrato observado de cada servicio; **sí se versiona** |
| `usuarios_compartidos.json` | catálogo de usuarios del equipo; **sí se versiona** |
| `~/.panel_qa/usuarios_prueba.json` | tus usuarios, con sus claves en claro |
| `~/.panel_qa/backups/` | copia previa a cada guardado |
| `~/.panel_qa/logs/` | log completo de Maven y los Excel exportados |

Tu archivo de usuarios vive fuera del repo a propósito: dentro, un
`git clean -fdx` se lo llevaría por delante.

## Notas de uso

**Detener y generar reporte** no mata el proceso: le pide al observador que
cierre por el mismo camino que `Ctrl+C`, para que alcance a escribir el reporte,
el último pantallazo y la validación de esquemas. Si el navegador no responde,
a los 20 segundos el observador genera el reporte igual y sale.

**Detener sin reporte** corta la captura y deja la evidencia cruda; el reporte
se arma después con **Generar reporte**.

Si una corrida quedara sin `reporte.html`, en **Corridas** la seleccionas y le
das **Revalidar**: se reconstruye desde los `.jsonl`, que se escriben mientras
navegas.

El checkbox **Tomar esta corrida como baseline de esquemas** viene desmarcado a
propósito. Marcarlo funde lo observado con el baseline y puede revertir
correcciones hechas a mano en `esquemas_servicios.json`.

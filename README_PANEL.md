# Panel QA

Ventana local para lanzar los scripts de este repo sin pasar por la consola.
Doble clic en `panel.bat`.

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

## Dónde queda todo

| ruta | contenido |
|---|---|
| `evidences/` | una carpeta por corrida del observador (no se versiona) |
| `esquemas_servicios.json` | contrato observado de cada servicio; **sí se versiona** |
| `~/.panel_qa/usuarios_prueba.json` | usuarios de prueba, con sus claves en claro |
| `~/.panel_qa/backups/` | copia previa a cada guardado |
| `~/.panel_qa/logs/` | log completo de Maven y los Excel exportados |

Los usuarios viven fuera del repo a propósito: dentro, un `git clean -fdx` se
los llevaría por delante.

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

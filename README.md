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
| `esquemas_servicios.json` | contrato observado de cada servicio; **sí se versiona** |
| `~/.panel_qa/usuarios_prueba.json` | usuarios de prueba, con sus claves en claro |
| `colsubsidio_flow/data/cedulas.json` | cédulas de los tests UI por data provider, sin claves; **sí se versiona** |
| `~/.panel_qa/backups/` | copia previa a cada guardado |
| `~/.panel_qa/logs/` | log completo de cada corrida y los Excel exportados |

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

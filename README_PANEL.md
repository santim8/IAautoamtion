# Panel QA

Ventana local para lanzar los scripts de este repo sin pasar por la consola.
Doble clic en `panel.bat`, o usa el `.exe` (ver *Repartirlo como aplicación*).

## Pestañas

| pestaña | qué hace |
|---|---|
| Observador de flujos | navegas a mano en Chrome; captura pantallas, requests y websocket |
| Analitica dataLayer | navegas a mano en Chrome; anota cada push al `dataLayer` (sin el ruido de GTM) y lo valida contra `analitica/modelo_de_datos[*].json` |
| Suite biometría | autenticación biométrica + firma de documentos, pegando directo a los endpoints REST (sin Maven, sin navegador) |
| Cancelar caso Bizagi | busca la última solicitud del documento y la cancela |
| Consultar caso Bizagi | con Id de caso busca directo; sin él, pide tipo y documento y muestra la última solicitud. Deja el navegador abierto |
| Consultar JSON | busca por Id de caso en *GCR_Solicitudes - Analista operativo* y vuelca la fila como JSON en el log |
| Validaciones API | corre los ~14 servicios de elegibilidad de crédito contra una lista de documentos, en paralelo |
| Usuarios | banco de usuarios de prueba: ficha por cédula, estado real (*Refrescar*), filtros y reservas |
| Corridas | evidencia acumulada; abre reportes y los regenera |

## Instalación

Necesitas Python 3.10 o superior con `tkinter` (viene en el instalador oficial
de python.org).

```
pip install -r requirements.txt
playwright install chromium
```

## Configuración

Qué pide cada pestaña, para no configurar de más:

| pestaña | qué necesita |
|---|---|
| Observador de flujos · Analítica dataLayer | nada; se engancha al Chrome de la máquina. La consulta a `/request/check` del observador usa `token.txt` si lo hay; sin él, avisa y captura igual |
| Validaciones API · Suite biometría | `token.txt` con las 6 claves de elegibilidad |
| Cancelar caso · Consultar caso · Consultar JSON | `BIZAGI_USER` y `BIZAGI_PASSWORD` de entorno (y un Chromium que el panel baja solo la primera vez) |
| Usuarios | nada para la libreta; *Refrescar* usa el mismo `token.txt` de Validaciones API |
| Corridas | nada |

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

Las pestañas **Suite biometría** y **Validaciones API** pegan directo a los
endpoints REST (sin depender de `colsubsidioFramework` ni de Maven). Necesitan
estas claves en `token.txt` (no se versiona):

```
api_key_card_validations=<x-api-key de eligibility>
apigee_client_id=<client_id de Apigee>
apigee_client_secret=<client_secret de Apigee>
sso_password=<password de login SSO>
ciam_token_api_key=<x-api-key del endpoint de token CIAM>
ciam_gigya_api_key=<gigyaApiKey del token CIAM>
```

Si falta alguna, el mensaje de error dice exactamente cuál agregar.

**Dónde va el archivo.** Desde el repo, en la raíz (al lado de `panel.bat`).
Con el `.exe`, al lado del `.exe`. Hay una plantilla lista para copiar:

```
copy token.example.txt token.txt
```

Las claves no viajan ni en el repo ni dentro del `.exe`: cada quien pone su
`token.txt`. Pedíselas a quien ya tenga el panel andando.

## Repartirlo como aplicación

Para quien no tiene Python ni va a clonar el repo:

```
construir_exe.bat
```

Deja `dist\PanelQA.exe` (~54 MB). Se reparte la carpeta `dist\` completa y se
abre con doble clic; no necesita Python, ni Playwright, ni el repo.

**Dónde escribe.** Junto al `.exe`: `evidences\`, `esquemas_servicios.json`.
Los usuarios de prueba siguen en `~/.panel_qa/`, igual que desde el repo.
Conviene dejarlo en una carpeta propia y no en Descargas.

**El navegador de Playwright no viaja dentro.** Solo lo usan las dos pestañas de
Bizagi, que abren su propio Chromium; el observador se engancha por CDP al
Chrome de verdad y no lo necesita. La primera vez que se usa una pestaña de
Bizagi, el panel lo baja solo a `~/.panel_qa/browsers` (~150 MB, unos minutos,
una sola vez). Si la máquina ya tiene uno de un `playwright install` previo, lo
reutiliza y no baja nada.

**Ojo al empaquetar:** `panel.spec` lista los datos uno por uno a propósito.
`token.txt` (el PAT de Azure DevOps) vive en esta carpeta, y meter `(".", ".")`
lo metería dentro del `.exe` que se reparte. No lo cambies por un comodín.

## Usuarios de prueba compartidos

`usuarios_compartidos.json` viaja en el repo. La primera vez que abres la
pestaña **Usuarios** después de clonar, ese catálogo siembra tu archivo local y
a partir de ahí cada quien maneja el suyo.

| botón | qué hace |
|---|---|
| Traer del repo | agrega los del catálogo que aún no tengas; a los que ya tienes les suma etiquetas, les llena lo que esté vacío (clave, descripción, status, falla, reserva) y les pone el estado del catálogo si es de un refresco más nuevo que el tuyo. Lo que tú escribiste no se pisa |
| Publicar al repo | reescribe el catálogo con tu lista actual tal como la ves: etiquetas, reserva y el estado del último refresco (SAP, SIIF, ASCARD, preaprobado, caso, CIAM) |

Del estado no se publican el nombre, la edad ni la empresa del afiliado: el repo
es público y la tabla no los usa. La ficha los vuelve a mostrar después de
Refrescar.

**Las contraseñas no se publican por defecto.** El checkbox *Publicar también
las contraseñas* las incluye, pero entonces quedan en el historial de git de
forma permanente: borrar el archivo después no las quita. Con el checkbox
apagado se comparte todo lo demás y cada quien completa las claves en su
archivo local.

Después de publicar hay que commitear `usuarios_compartidos.json` a mano.

## Banco de usuarios: ficha y Refrescar

Cada usuario de la libreta conserva sus campos de siempre (tipo, usuario,
contraseña, descripción, status, falla) y suma tres:

| campo | qué guarda | quién lo escribe |
|---|---|---|
| `etiquetas` | lo que sabemos y no cambia solo: `novedades-autorizada`, `genero-cruzado-sap`, `ciam-lote-2026-10-08`, la HU donde sirvió... | tú (campo *Etiquetas*, separadas por coma) |
| `uso` | quién lo tiene reservado, para qué HU y desde cuándo | *Reservar...* / *Liberar* |
| `estado` | el estado real en cada sistema | *Refrescar*; no se edita a mano |

**Refrescar** pregunta, por cada cédula y contra platform-test (el back de dev):

| columna | servicio | qué muestra |
|---|---|---|
| Afiliación, Cat., Género | `affiliation-validations` v2 (SAP, la que llama el front) | tipo de trabajador (ZTRA/ZAIN/ZAPE/ZAFA), categoría, género (1 mujer, 2 hombre); en la ficha, el motivo si rechaza (`Ingresos insuficientes`, `Afiliado no vigente`...) |
| Validaciones | SAP, SIIF y ASCARD | `Pasa las 3`, `No pasa: SIIF, ASCARD` o `Sin dato: ...` |
| Preap. | campañas (`/campaigns`) | `Si` / `No` |
| Novedad | `card-validations` v2 (ASCARD) | Originación / Aumento / Reactivación según `tipoSolicitud`, o el rechazo con su regla; en la ficha, los bolsillos (`31:V ...`) y si está amparada |
| Caso | `/request/check` | `Sin caso` o el caso abierto con su `pasoPendiente` (lo que vería la retoma) |
| CIAM | lo guardado (Gigya `isAvailableLoginID` solo a pedido) | si la cédula tiene cuenta en el login de dev; en la ficha, si la creó Bruno |

**CIAM no se pregunta al refrescar** (desde el 20/10): una cuenta que existe no
deja de existir, y Gigya corta con 403048 si se le pregunta mucho. La columna
muestra lo guardado; para preguntarle a Gigya, por consola:
`python usuarios.py refrescar CC:123 --preguntar-ciam` (o `revisar ...
--preguntar-ciam`). `crear-ciam` marca la cuenta como existente al crearla.

**Contraseña de las cuentas creadas con Bruno**: Bruno registra cada cédula con
el correo `santiago.correa03+cc<numero>@globant.com`. Si ese correo está tomado
en Gigya, la cuenta la creó Bruno y nació con `regPassword` de `registro-dev`.
`--preguntar-ciam` se la pone en la columna *Contraseña* si estaba vacía (una
que ya tiene clave no se toca); Gigya se pregunta una sola vez por cuenta.
Sirve para *Crear Usuarios Lote[Gigya]*, `crear-ciam` y, desde el 20/10,
*Crear Usuario[Gigya]* (antes usaba una palabra aleatoria en el correo y esas
cuentas no se reconocen).

**Qué es "pasa"**: SAP = `affiliation-validations` v2 respondió OK; SIIF =
elegibilidad de productos OK; ASCARD = `card-validations` v2 OK (con cualquier
novedad). "Pasa las validaciones" y "pasa todas" son esas tres. SAP se pregunta
a la v2 porque la v1 interna aplica otras reglas (rechaza por ingresos a quien
la v2 deja pasar) y con algunos afiliados da 500. Listas restrictivas ya no
está vigente: no se consulta ni se muestra.

**Refrescar un usuario: basta con seleccionarlo.** Un clic en la fila (o
llegar a ella con las flechas o con Enter en *Documento(s)*) la refresca sola
cuando lleva medio segundo seleccionada; recorrer la tabla con las flechas
refresca solo la fila donde te detienes. La barra de abajo dice cómo quedó, en
la misma línea que `usuarios.py revisar`: `CC:123 refrescada: Pasa SAP, SIIF y
ASCARD | Originacion | Sin caso`. Si un servicio no respondió:
`CC:123 refrescada, menos caso, que no respondio y conserva el dato anterior`.

- Una fila refrescada hace menos de 30 s no se vuelve a pedir sola (la barra
  dice *esta al dia*); **F5** o clic derecho → *Refrescar este usuario* la
  refrescan igual. Una que quedó con errores sí se reintenta con otro clic.
- Si haces clic en otra fila mientras se refresca una, la nueva se refresca al
  terminar (*Al terminar sigue la fila seleccionada*).
- Con varias filas seleccionadas (Ctrl o Shift) no se refresca solo: usa F5 o
  *Refrescar seleccionados*.
- Al seleccionar nunca se prueba la contraseña, aunque esté marcado *Probar
  login CIAM* (eso solo con F5 o los botones, y pregunta antes).
- Lo que escribas en el formulario mientras se refresca no se pierde, y la ficha
  abierta con doble clic dice *(refrescando...)* y se pone al día sola.
- Al terminar, la tabla no salta arriba y las flechas siguen desde la misma fila.
- La casilla *Refrescar al seleccionar* lo apaga (por ejemplo, si el servidor
  anda bloqueando y solo quieres copiar usuarios y claves).

Los rechazos de tráfico (403 del WAF *Acceso Denegado*, 503 de CloudFront *The
request could not be satisfied*, 401 de Apigee, 429, 502, 504) se reintentan
hasta 3 veces, a los 2, 5 y 10 s. El servidor de platform-test corta a ráfagas:
medido el 20/10, ~2,4 consultas por segundo sostenidas fallaban desde la
consulta 31, y aun a 0,6 por segundo aparecía alguno; un usuario son 5
consultas, así que los reintentos lo absorben. Un 500 no se reintenta: es del
back (la CC 1023944601 da siempre `LRM0002` en `/request/check`). El panel no
puede quedarse en *Refrescando...*: si algo falla al aplicar el resultado, lo
dice y suelta los botones. Si el archivo cambia por fuera mientras hay una fila
seleccionada, la selección sigue en la misma cédula.

Si un servicio falla, esa parte conserva lo que traía y el error queda en la
ficha: la columna *Refrescado* lo cuenta (`14/10 16:29 (1 error)`) y **doble
clic** en la fila muestra la ficha completa. Al refrescar varias, el mensaje
final dice cuántas quedaron con errores y de qué servicio
(`3 con errores (caso 2, ascard 1)`).

Gigya (solo `--preguntar-ciam` y *Probar login CIAM*) va de a una consulta cada
2,5 s entre todos los hilos: en ráfaga corta con 403048 y el castigo dura varios
minutos. Si igual corta, no se le pregunta durante 5 minutos y CIAM conserva lo
que traía.

**Probar login CIAM** (apagado por defecto) prueba además la contraseña de la
libreta en Gigya y dice *Login OK*, *Sin verificar* (206002: falta abrir el
correo de verificación), *Clave errada* o *Bloqueada*. Cada clave errada cuenta
para el bloqueo de la cuenta, así que una clave que ya dio errada no se vuelve a
probar hasta que la cambies.

**Documento(s)** (Ctrl+F) es la forma rápida de encontrar cédulas: una o
varias, en cualquier formato (`123`, `CC 123`, `CC123`, `CE:456`, `CO1C 789`,
`52.335.676`), separadas por coma o espacio, o una columna pegada de Excel
(con la del tipo al lado o sin ella). Sin tipo busca en CC y CE. Con una sola
cédula busca mientras escribes (`5233` trae las que la contienen); con varias,
las muestra en el orden en que las pegaste y la barra de abajo dice cuáles no
están en la libreta. Mientras buscas por documento los filtros no aplican, para
que un combo olvidado no esconda la cédula. **Enter** selecciona lo encontrado
(listo para *Refrescar seleccionados*, *Reservar...* o *Liberar*) y otro
**Enter** abre la ficha; **Esc** limpia. **Agregar y validar** hace lo mismo
que `usuarios.py revisar`: suma al banco las que falten, con la etiqueta
`consulta-<fecha>`, y las refresca todas.

**Filtros**: afiliación, género, categoría, novedad, validaciones,
preaprobado, caso, CIAM, status, etiqueta y *Solo libres*; todos se combinan.
*Refrescar visibles* refresca lo que deja el filtro.

**Buscar entiende un perfil en palabras**, en cualquier combinación:
`mujer preaprobada que pase validaciones`, `2 pensionadas de reactivación sin
caso`, `hombre independiente aumento que pase todas`, `dependiente categoria B
originacion libre`, `facultativa sin preaprobado que falle alguna validación`.
La barra de abajo dice cómo lo entendió (`Buscar entendio: mujer | preaprobado |
pasa SAP, SIIF, ASCARD`); lo que no reconoce lo busca como texto (una cédula,
una etiqueta, un nombre). Si un combo y Buscar dicen algo del mismo campo,
manda el combo.

**Importar archivo...** suma las cédulas de un CSV, TXT o JSON (un Excel se
guarda antes como CSV): con
encabezado (columnas tipo y número/documento/cédula; nota u observación
opcional, aunque haya un título arriba) o una cédula por línea (`CC:123`,
`CE 456` o solo `123`, que es CC). Les pone la etiqueta `lote-<archivo>`, deja
la tabla filtrada por ella y ofrece validarlas en el acto. La carpeta `cargas/`
del repo no se versiona: sirve para dejar ahí esos archivos.

**Desde la consola** (mismo archivo; si el panel está abierto, la pestaña lo
relee sola):

```
python usuarios.py revisar CC 80273420 CC1015392154 52634111
python usuarios.py crear-ciam CC:80273420
python usuarios.py importar cargas/usuarios.csv --refrescar --hilos 8
python usuarios.py buscar --etiqueta lote-usuarios mujer preaprobada que pase validaciones
python usuarios.py buscar --genero F --preaprobado --pasa
python usuarios.py buscar --afiliacion pensionado --genero F --sin-caso --libres
python usuarios.py buscar --novedad reactivacion --sin-caso --reservar 225427 --cuantos 2
python usuarios.py refrescar --etiqueta novedades-autorizada
python usuarios.py refrescar CC:52335676 CC:41336668 --login
python usuarios.py liberar CC:41336668
python usuarios.py etiquetar CC:41336668 --agregar hu225427
python usuarios.py exportar cedulas consumo_225423 --novedad originacion --sin-caso
python usuarios.py exportar bruno --ciam no-existe
```

`revisar` responde de una "¿pasa todas, qué novedad es, tiene CIAM?": suma al
banco las cédulas que falten (etiqueta `consulta-<fecha>`), las refresca y
muestra la ficha de cada una, con el motivo de cada rechazo. El CIAM que
muestra es el guardado; con `--preguntar-ciam` le pregunta a Gigya. `crear-ciam` crea
la cuenta del login de dev con *Crear Usuarios Lote[Gigya]* (reescribe su CSV,
corre `bru.cmd`), dice por cédula si quedó creada o ya existía, y marca el banco
(CIAM existe, etiqueta `ciam-creado-<fecha>` y, en las que creó, la clave
`regPassword` de `registro-dev` en la columna *Clave*). A una cuenta que ya
existía no le toca la clave. La cuenta nueva queda pendiente de verificar el
correo `santiago.correa03+cc<numero>@globant.com`.

`exportar cedulas` llena un data provider de `colsubsidio_flow/data/cedulas.json`
(sin claves). `exportar bruno` reescribe
`bruno/validate-request/data/usuarios_registro.csv`, el CSV de *Crear Usuarios
Lote[Gigya]*: con `--ciam no-existe` deja solo los que todavía no tienen cuenta.
`python usuarios.py --help` lista todo.

## Dónde queda todo

| ruta | contenido |
|---|---|
| `evidences/` | una carpeta por corrida del observador (no se versiona) |
| `evidencias_analitica/` | una carpeta por corrida de la analítica (no se versiona) |
| `analitica/modelo_de_datos[*].json` | lo que se espera de cada evento de analítica; editable, **sí se versiona** |
| `esquemas_servicios.json` | contrato observado de cada servicio; **sí se versiona** |
| `usuarios_compartidos.json` | catálogo de usuarios del equipo; **sí se versiona** |
| `~/.panel_qa/usuarios_prueba.json` | tus usuarios, con sus claves en claro |
| `~/.panel_qa/backups/` | copia previa a cada guardado |
| `~/.panel_qa/logs/` | log completo de cada corrida de Validaciones API |
| `~/.panel_qa/validaciones_docs.json` | última lista de documentos corrida en Validaciones API |

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

El campo **Empezar en la URL que contenga** trae las dos rutas de login
(`creditos/solicitud/login` y `loans-dev-solicitud/login`): el observador no
captura nada hasta que una pestaña llega al login, y desde ahí sigue esa pestaña
en todo el flujo. Lo de antes (onboarding) no entra a la evidencia. Si el flujo
no pasa por el login (por ejemplo, con sesión ya iniciada y sin **Empezar sin
sesión previa**), la captura queda esperando; para observar desde el inicio,
pon `creditos/solicitud,loans-dev-solicitud`.

El checkbox **Tomar esta corrida como baseline de esquemas** viene desmarcado a
propósito. Marcarlo funde lo observado con el baseline y puede revertir
correcciones hechas a mano en `esquemas_servicios.json`.

El checkbox **Empezar sin sesión previa (como incógnito)** viene marcado: antes
de capturar borra cookies, caché y almacenamiento del Chrome de QA.

El checkbox **Consultar /request/check en el login, al detectar el documento y
en información personal** viene marcado. Ese endpoint (el que decide la retoma)
lo llama el servidor del front, no el navegador, así que el observador nunca lo
ve por su cuenta. Con el checkbox, el propio observador lo consulta en tres
momentos de la corrida: apenas responde el login de Gigya (`accounts.login`),
con el documento que trae su respuesta (`data.tpIdentificacion` y
`data.numeroDocumento`), para ver si hay una solicitud que retomar; al detectar
el documento en el tráfico de validaciones (o desde la primera pantalla si diste
el campo **Documento**, por ejemplo `CC:52961647`), cuando todavía no hay caso,
y al llegar a `informacion-personal`, cuando el caso ya se creó. Recargar esa
pantalla no repite la consulta, y al cerrar no se consulta de nuevo. El reporte
trae una tabla con `estado`, `pasoPendiente` e `idCaso` por consulta, y lo
mismo queda en `request_check.json`. Esas consultas van marcadas como `SONDA`
y no cuentan como fallos: un 404 significa que el documento no tiene caso
abierto.

**Reiniciar Chrome** (en el Observador y en la Analítica) cierra el Chrome de QA
y abre uno limpio; se pierden las pestañas y la sesión. Sirve cuando Chrome deja
de navegar aunque el panel diga que está arriba. Hay que detener la captura
antes.

Para que un evento de analítica nuevo se valide basta con agregar su entrada en
el `modelo_de_datos` que corresponda; no hay que tocar código.

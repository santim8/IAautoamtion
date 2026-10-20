---
name: usuarios
description: Banco de usuarios de prueba (cédulas) de crédito Colsubsidio sobre `python usuarios.py`. Úsala siempre que pidan usuarios, cédulas o documentos de prueba con un perfil o cualquier combinación de características ("dame una mujer preaprobada que pase SAP, SIIF y ASCARD", "2 pensionadas libres sin caso", "una cédula de reactivación", "un independiente sin cuenta CIAM", "¿qué cédula sirve para la HU X?"), cuando pregunten por una cédula puntual ("CC 123 ¿pasa todas?", "¿es de reactivación?", "¿tiene credenciales?", "y este 456?"), cuando pidan crearle la cuenta/usuario CIAM a una cédula, cuando suban o compartan un archivo (Excel, CSV, TXT) con cédulas para validar, cuando pidan reservar, liberar o etiquetar cédulas, refrescar o validar su estado (SAP, SIIF, ASCARD, preaprobado, Bizagi, Gigya), o llenar un data provider de colsubsidio_flow/data/cedulas.json o el CSV del lote de creación CIAM de Bruno. También antes de sacar cédulas de la memoria para una prueba.
allowed-tools: Bash(python usuarios.py:*)
---

# Banco de usuarios (`usuarios.py`)

La libreta es `~/.panel_qa/usuarios_prueba.json` (la misma de la pestaña
Usuarios del panel). Es la fuente de verdad de qué cédula sirve para qué: antes
de proponer una cédula de la memoria, búscala aquí. Todo corre desde la raíz del
repo: `python usuarios.py ...` (`--help` lista todo; README_PANEL.md, sección
"Banco de usuarios", explica las columnas).

## Reglas

- **No inventar cédulas.** Solo se proponen las que devuelve `buscar`. Si
  ninguna cumple, dilo y describe el perfil que hay que pedirle al equipo de
  datos (ej.: "pensionada ZAPE, mujer, sin caso en Bizagi, ASCARD originación").
  La cédula nueva entra por el panel o `importar`, nunca a mano en el JSON.
  Solo hay CC (CO1C) y CE (CO1E).
- **Nunca mostrar contraseñas.** No leas ni hagas `cat` de
  `usuarios_prueba.json` ni de `~/.panel_qa/backups/` (tienen las claves en
  claro). La tabla de `buscar` no trae claves; para la ficha completa usa
  `buscar ... --json`, que quita la clave y su huella.
- **`refrescar --login` solo si lo piden explícitamente**: prueba la clave en
  Gigya y cada clave errada cuenta para bloquear la cuenta. Avisa eso antes de
  correrlo.
- **Reservar solo si lo piden.** "Dame 2 pensionadas" es buscar y proponer;
  "...y resérvalas para la 225427" es reservar. Nunca `--forzar` sin pedido.
- `revisar`, `crear-ciam`, `refrescar`, `reservar`, `liberar`, `etiquetar`,
  `importar` y `exportar` escriben (la libreta, `cedulas.json` o el CSV de
  Bruno). `buscar` sin `--reservar` solo lee.
- **`crear-ciam` crea una cuenta real** en el Gigya de dev: solo cuando lo
  piden ("crear usuario", "créale credenciales").

## Una cédula puntual: `revisar` (un solo comando)

"CC 123 ¿pasa todas? ¿es de reactivación? ¿tiene credenciales?", "y este 456?":

    python usuarios.py revisar CC 123 [CE:456 789 ...]

La suma al banco si falta (etiqueta `consulta-<fecha>`), la refresca y muestra
la ficha: cada validación con su motivo de rechazo (SAP `Ingresos
insuficientes`, ASCARD `Tarjeta multiservicios no activa`...), novedad y
bolsillos, preaprobado, caso, CIAM y lo del banco (status, falla, etiquetas,
reserva). La última línea (`=> ...`) es la respuesta corta. Acepta `CC:123`,
`CC123`, `CC 123` o `123`. Tarda ~5 s una cédula. No hace falta `importar` +
`buscar --json` aparte.

Al responder, ojo con:
- Novedad por bolsillos (patrón visto en el banco): sin bolsillo 31 →
  originación; 31 normal → rechazo "Afiliado con cupo activo"; 31 inactivo →
  reactivación.
- CIAM `Existe` no dice si el correo está verificado (eso es `--login`).
- El CIAM de la ficha es el guardado. Si preguntan "¿tiene credenciales?" y
  no hay dato o dice `No existe`: `revisar CC 123 --preguntar-ciam`.

## Crear la cuenta CIAM: `crear-ciam`

    python usuarios.py crear-ciam CC:123 [CC:456 ...]

Reescribe `bruno/validate-request/data/usuarios_registro.csv` con esas cédulas,
corre *Crear Usuarios Lote[Gigya]* con `bru.cmd` y dice por cédula: `CREADA,
falta verificar el correo` (206002, lo normal en dev), `YA TENIA CUENTA` o `NO
CREADA: <motivo>`. Deja en el banco CIAM = existe, la etiqueta
`ciam-creado-<fecha>` y, en las que creó, la clave (`regPassword` de
`registro-dev`), que el panel muestra en la columna Clave; a las `YA TENIA
CUENTA` no les toca la clave. Login = tipo+número (`CC123`), clave del environment
`registro-dev` (no la muestres), correo `santiago.correa03+cc<numero>@globant.com`.
Avisa que hay que abrir el enlace de verificación antes de loguear.

## Del pedido a los filtros

Los filtros se combinan con Y, en cualquier combinación; uno que no se pide no
se pone.

**Atajo: el perfil en palabras.** `buscar` acepta el pedido tal cual y lo
traduce: `python usuarios.py buscar mujer preaprobada que pase validaciones`.
La primera línea de la salida (`Perfil: mujer | preaprobado | pasa SAP, SIIF,
ASCARD`) dice cómo lo entendió: **revísala y dísela al usuario**. Lo que no
reconoce lo busca como texto (una cédula, una etiqueta, un nombre); si en
`Perfil:` aparece `texto "..."` con palabras del pedido, no las entendió:
pásalas con la opción explícita de la tabla. Las opciones explícitas mandan
sobre el perfil. También sirve `--perfil "..."` en `refrescar` y `exportar`.

Qué es "pasa": SAP = `affiliation-validations` v2 OK (la del front; la v1
interna rechaza por ingresos y da 500 donde la v2 pasa); SIIF = elegibilidad de
productos OK; ASCARD = `card-validations` v2 OK (cualquier novedad). "Pasa
las validaciones" y "pasa todas" son esas tres. **Listas restrictivas ya no está
vigente**: no se consulta ni se menciona al responder.

| pedido | filtro |
|---|---|
| que pase las validaciones / todas (SAP, SIIF y ASCARD) | `--pasa` · solo algunas: `--pasa sap,siif` |
| que falle alguna validación | `--no-pasa` |
| preaprobado / con campaña | `--preaprobado` · sin preaprobado: `--sin-preaprobado` |
| categoría A, B o C | `--categoria B` |
| amparada / no amparada | en palabras: `buscar ... amparada` / `no amparada` |
| dependiente / independiente / pensionado / facultativo | `--afiliacion dependiente` (o `ZTRA`, `ZAIN`, `ZAPE`, `ZAFA`; `ZGRE` = grupo pensionado) |
| mujer / pensionada / "ella" | `--genero F` · hombre: `--genero M` |
| originación, aumento, reactivación (lo que diría ASCARD) | `--novedad originacion\|aumento\|reactivacion` |
| que ASCARD rechace (amparada, mora...) | `--novedad rechazo` |
| sin caso / caso nuevo / que no retome | `--sin-caso` · con caso abierto (retoma): `--con-caso` |
| con cuenta en el login de dev | `--ciam existe` · sin cuenta: `--ciam no-existe` |
| que ya entre al login / verificada | `--ciam login-ok` · le falta abrir el correo: `--ciam sin-verificar` |
| libres / que nadie esté usando | `--libres` (excluye En uso, Bloqueado, Quemado, Con falla y reservados) |
| las de novedades, las del lote CIAM, las de una HU | `--etiqueta novedades-autorizada` (`ciam-lote-2026-10-08`, `hu225423`, `candidato-mora`, `genero-cruzado-sap`...) |
| un nombre, una palabra de la descripción o la falla | `--texto X` |
| un status puntual | `--status "En uso"` |

Género, novedad, caso y CIAM salen del `estado` que escribe `refrescar`: una
cédula nunca refrescada no pasa esos filtros (ni `--afiliacion`). Que no
aparezca no significa que no exista. **CIAM solo se actualiza con
`--preguntar-ciam`** (en `refrescar` o `revisar`): el refresco normal no le
pregunta a Gigya, por pedido de Santiago (una cuenta que existe no deja de
existir y Gigya corta con 403048). Úsalo cuando pregunten "¿tiene
credenciales/cuenta?" de una cédula sin dato de CIAM o con `No existe` (pudo
crearse después).

## Cuando suben un archivo con cédulas

El usuario puede adjuntar o dejar en una carpeta (sugerido: `cargas/` en la
raíz del repo, que no se versiona) un CSV, TXT o JSON. Si es un Excel, pide que
lo guarde como CSV (`importar` rechaza .xlsx con ese mensaje). Sirve con
encabezado (columnas tipo y numero/documento/cédula; nota u observación
opcional), con un título arriba, o una cédula por línea (`CC:123`, `CE 456` o
solo `123`, que es CC).

1. `python usuarios.py importar RUTA --refrescar --hilos 8`: suma las que no
   estaban, les pone la etiqueta `lote-<nombre del archivo>` (o `--etiqueta X`)
   y las valida contra los servicios. La última línea dice cuántas pasan SAP,
   SIIF y ASCARD y cuántas además son preaprobadas. Con más de ~20 cédulas,
   córrelo en segundo plano (≈ 15 s por cada 5 cédulas).
2. Reporta las filas que no traían cédula válida (`! N fila(s) sin cedula
   valida`): no las corrijas a mano.
3. Responde el pedido sobre ese lote:
   `python usuarios.py buscar --etiqueta lote-x mujer preaprobada que pase validaciones`.
   Si ninguna cumple, di qué falló más (la columna *Validaciones* dice `No pasa:
   SIIF, ASCARD`), no relajes filtros sin preguntar.

## Flujo para "dame N ... [y resérvalas para la HU]"

1. **Ver qué hay** con el estado guardado:
   `python usuarios.py buscar <filtros> --libres`.
   La columna *Refrescado* dice de cuándo es cada dato.
2. **Refrescar antes de proponer.** ASCARD y Bizagi cambian solos (alguien abre
   un caso, se mueve un bolsillo). Refresca por lo que no cambia y filtra
   después por lo que sí:
   - las candidatas: `python usuarios.py refrescar CC:123 CC:456`
   - o la etiqueta pedida: `python usuarios.py refrescar --etiqueta X`
   - o, si en el paso 1 salieron pocas o ninguna porque hay cédulas sin
     refrescar: `python usuarios.py refrescar --libres` (más los filtros
     estables, `--afiliacion`/`--genero`, si ya hay estado).
     No refresques con `--sin-caso` o `--novedad`: dejarías fuera justo las que
     cambiaron hacia el perfil pedido.
   Tarda ~15 s por tanda de 5. Con más de
   ~40 cédulas, córrelo en segundo
   plano. Necesita `token.txt`; si falla por ahí, dilo y no sigas a ciegas.
   Las líneas `errores: ...` y la columna *Refrescado* `(N error)` dicen qué
   servicio no respondió: esa parte quedó con el dato anterior; dilo al
   proponer.
3. **Volver a buscar** con todos los filtros y proponer como máximo N, con lo
   que dice cada una (afiliación, categoría, género, novedad, caso, CIAM).
4. **Reservar solo si lo pidieron**, las mismas cédulas que mostraste:
   `python usuarios.py reservar CC:123 CC:456 --hu 225427`.
   (`buscar <filtros> --reservar 225427 --cuantos 2` reserva las primeras libres
   que cumplan; sirve cuando no importa cuáles.) Si alguna ya no está libre, el
   comando lo dice y no la toca: avísalo.
5. **Al terminar la HU** (o si piden soltarlas): ver las reservadas con
   `python usuarios.py buscar --status "En uso"` (la última columna dice quién y
   para qué HU) y `python usuarios.py liberar CC:123 CC:456`. Si sirvieron, se
   puede dejar rastro: `etiquetar CC:123 --agregar hu225427`.

## Exportar

- **Data provider de colsubsidio_flow**:
  `python usuarios.py exportar cedulas GRUPO <filtros>` agrega (sin claves) las
  que cumplen a `colsubsidio_flow/data/cedulas.json`, sin repetir. Exporta
  todas las que pasen el filtro: acota con filtros o `--etiqueta`.
  `--reemplazar` vacía el grupo antes; pregunta antes de usarlo. Grupos que hay
  hoy: `fill_data_api`, `login_credito`, `consumo_225423`. El archivo se
  versiona: avisa que quedó modificado.
- **Lote de creación CIAM (Bruno)**:
  `python usuarios.py exportar bruno --ciam no-existe` reescribe
  `bruno/validate-request/data/usuarios_registro.csv` con las que aún no tienen
  cuenta (antes `refrescar ... --preguntar-ciam`: `--ciam` sale del estado
  guardado). Luego se corre
  *Crear Usuarios Lote[Gigya]* con ese CSV.

## Si algo no cuadra

Si `buscar` sin filtros trae muchas menos cédulas o etiquetas de las esperadas,
puede que un panel abierto desde antes del banco (sin la pestaña nueva) haya
guardado su copia vieja encima. No refresques ni reserves sobre esa libreta:
avisa al usuario; la copia previa a cada guardado está en `~/.panel_qa/backups/`
(no la leas en crudo: tiene claves) y el panel viejo hay que cerrarlo antes de
restaurar.

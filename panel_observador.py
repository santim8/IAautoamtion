#!/usr/bin/env python3
"""Panel local para lanzar los scripts del repo sin tocar la consola.

Cada herramienta es una entrada de HERRAMIENTAS: se declara el script, los
campos que pide y como se para. El panel arma el formulario, el comando y el
log solo. Agregar una herramienta nueva es agregar un diccionario, no tocar la
UI.

Los tres modos de parada, que es lo que de verdad separa a un script de otro:

  "centinela"  el proceso escribe evidencia al cerrarse (observador_flujo).
               Se le pide parar con un archivo que el vigila, para que salga
               por el mismo camino que Ctrl+C. Matarlo dejaria la corrida sin
               reporte, sin el ultimo pantallazo y sin validacion de esquemas.
  "terminar"   el proceso queda vivo sosteniendo algo (el navegador de
               bizagi_consultar_caso, que espera un Enter que nunca llega
               cuando no hay consola). No hay nada que perder: se termina.
  None         de un tiro: corre, termina y se le lee un veredicto del log.

Se abre con doble clic en panel.bat, o con:
    python panel_observador.py
"""
import importlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.error
import urllib.request
import webbrowser
from tkinter import ttk, messagebox, simpledialog, filedialog

import usuarios as banco
from rutas import BASE, CONGELADO, DIR_DATOS, RECURSOS, chromium_instalado

EVIDENCIAS = os.path.join(BASE, "evidences")

# Los scripts hermanos que el panel lanza. Congelado no hay .py que pasarle a
# python: se importan como modulos desde el propio ejecutable (ver _correr_hijo),
# asi que la lista tambien le dice a PyInstaller que tiene que incluirlos.
HIJOS = ["observador_flujo", "observador_analitica", "bizagi_cancel_case",
         "bizagi_consultar_caso", "bizagi_consultar_json", "validaciones_api",
         "biometria_api"]

# Usuarios de prueba. Viven FUERA del repo a proposito: dentro, un git clean
# -fdx o volver a clonar se los lleva por delante (estan en .gitignore, que es
# justo lo que git clean borra). Aqui sobreviven a cualquier cosa que le pase
# al repo.
USUARIOS = banco.ARCHIVO
USUARIOS_LEGADO = os.path.join(BASE, "usuarios_prueba.json")
# Lista de documentos de la pestana Validaciones API. Mismo espiritu que los
# usuarios de prueba: fuera del repo para que sobreviva a un git clean, y es
# solo la lista de trabajo del panel (ya no un DataProvider de Java).
VALIDACIONES_DOCS = os.path.join(DIR_DATOS, "validaciones_docs.json")
# Catalogo compartido: este SI se versiona, para que quien clone el repo
# arranque con los usuarios de prueba del equipo. Siembra el archivo local la
# primera vez; despues cada quien maneja el suyo y sincroniza a mano.
USUARIOS_COMPARTIDOS = os.path.join(BASE, "usuarios_compartidos.json")
# Copia de fabrica del catalogo, dentro del .exe. Solo se lee, y solo cuando no
# hay una al lado del ejecutable: asi el equipo puede dejar un
# usuarios_compartidos.json actualizado junto al .exe sin reempaquetar nada.
USUARIOS_SEMILLA = os.path.join(RECURSOS, "usuarios_compartidos.json")


def catalogo_compartido():
    """El catalogo que se lee: el de al lado si existe, si no el de fabrica."""
    if os.path.exists(USUARIOS_COMPARTIDOS):
        return USUARIOS_COMPARTIDOS
    return USUARIOS_SEMILLA if os.path.exists(USUARIOS_SEMILLA) else USUARIOS_COMPARTIDOS
BACKUPS = banco.BACKUPS
LOGS = os.path.join(DIR_DATOS, "logs")

# [EXCEL_UPDATE] Thread:28 52526685 - Card Validation - PASS - HTTP 200 estado OK
# La marca es la del log del framework Java; validaciones_api.py la imita para
# que su salida se lea igual. Aqui no se exporta ningun Excel.
RE_RESULTADO = re.compile(r"\[EXCEL_UPDATE\] Thread:\d+\s+(\S+)\s+-\s+(.+?)\s+-\s+(.+)")
RE_HTTP_CODE = re.compile(r"HTTP\s+(\d+)")
# Servicios del catalogo del framework que no se revisan aqui: se descartan al
# entrar, asi no ocupan columna en la tabla. En minusculas porque el log no
# siempre respeta el casing del catalogo.
SERVICIOS_OCULTOS = {"sso credentials", "habeas data records", "validate request"}
# Orden canonico de las columnas, copiado de SERVICE_COLUMNS en
# ExcelReportManager.java, para que la tabla del panel se lea igual que el Excel
# del framework en vez de por orden de llegada al log.
SERVICIOS_CATALOGO = [
    "SSO Credentials", "Validation Bizagi", "Grupo Afiliacion",
    "Validator Rights", "Card Number",
    "Card Status", "Salary", "Card Validation", "Card Validation Error",
    "Novedad Estado", "Card Validation Error V2",
    "Siif Validation", "Validate Request", "Preapproved", "Habeas Data Records",
]
# Columnas que se muestran siempre, traigan o no linea en el log: Card
# Validation Error solo se reporta cuando falla, y que venga vacia tambien dice
# algo. Agrega aqui cualquier otra que quieras ver fija.
SERVICIOS_FIJOS = ["Grupo Afiliacion", "Card Validation Error"]


def _orden_servicio(nombre):
    """Coloca cada servicio donde lo pone el framework; lo desconocido, al final."""
    try:
        return (SERVICIOS_CATALOGO.index(nombre.strip()), "")
    except ValueError:
        return (len(SERVICIOS_CATALOGO), nombre)


def _decodificar_stdout(cruda):
    """El stdout del hijo casi siempre es UTF-8, pero alguna tilde suelta (una
    'O' con acento en cp1252) no es UTF-8 valido: decodificar todo como UTF-8
    con errors='replace' la cambiaba por el caracter de reemplazo (el rombo
    con interrogacion). Se intenta UTF-8 estricto primero y solo se cae a
    cp1252 cuando de verdad no es UTF-8, para no perder la tilde en 'Novedad
    Estado' (REACTIVACION, ORIGINACION)."""
    try:
        return cruda.decode("utf-8")
    except UnicodeDecodeError:
        return cruda.decode("cp1252", errors="replace")


MARCA_OK = "\U0001F7E2"    # verde
MARCA_MAL = "\U0001F534"   # rojo


def _formato_estado(estado):
    """Solo para la tabla: cada celda lleva su propio punto de color segun
    el PASS/FAIL crudo (el Treeview de Tk no permite pintar una celda suelta,
    solo la fila completa, asi que el punto es lo que distingue celda por
    celda). 'PASS - HTTP 200 estado OK' ademas se ve como '200 OK'; el codigo
    es el que trajo la respuesta real, no uno fijo. El crudo (con PASS/FAIL)
    se sigue guardando en self.resultados para el veredicto. Si el
    servicio no trae PASS ni FAIL (SKIP, o el detalle libre de Card
    Validation Error) se muestra tal cual llego, sin marca."""
    alto = estado.upper()
    if alto.startswith("PASS"):
        marca = MARCA_OK
    elif alto.startswith("FAIL"):
        marca = MARCA_MAL
    else:
        return estado
    m = RE_HTTP_CODE.search(estado)
    cuerpo = "%s %s" % (m.group(1), "OK" if marca == MARCA_OK else "FAIL") if m else estado
    return "%s %s" % (marca, cuerpo)
STOP_FILE = os.path.join(BASE, ".detener_observador")
# Centinela propio: la analitica y el observador de red pueden correr a la
# vez sobre la misma pestana, y cada uno tiene que poder pararse solo.
STOP_FILE_ANALITICA = os.path.join(BASE, ".detener_analitica")
# Lo que se escribe dentro del centinela para pedir parada sin reporte; el
# observador lo lee y deja la evidencia cruda para reportarla despues.
SIN_REPORTE = "sin-reporte"
# Rutas de la aplicacion: el front se sirve desde dos despliegues y el
# observador tiene que reconocer la pestana en cualquiera de los dos.
RUTAS_APP = "creditos/solicitud,loans-dev-solicitud"
# El observador fija la pestana recien cuando llega al login: lo de antes
# (onboarding) no entra a la evidencia, y desde ahi sigue esa pestana entera.
RUTAS_LOGIN = "creditos/solicitud/login,loans-dev-solicitud/login"
PUERTO = 9222

RE_MARCA = re.compile(r"_(\d{4})-(\d{2})-(\d{2})_(\d{2})(\d{2})(\d{2})$")
RE_CASO = re.compile(r"ltima solicitud:\s*(\d+)")
RE_CASO_JSON = re.compile(r"Consultando caso (\d+)")
# El caso que bizagi_cancel_case dice haber intentado cancelar. Lo imprime en
# su bloque de veredicto, que es mas fiable que deducirlo de otra linea.
RE_CASO_INTENTO = re.compile(r"Caso (?:cancelado|que se intento cancelar):\s*(\d+)")


# --- lanzar a los hermanos -------------------------------------------------
def comando_hijo(script, *args):
    """Como se corre uno de los scripts de al lado.

    Desde el repo: python script.py. Congelado NO, y este es el detalle que
    rompe todo si se pasa por alto: sys.executable ya no es python sino el
    propio panel, y el .py no existe en disco. Lanzarlo igual abriria otra
    ventana del panel en vez de correr nada.

    Congelado se relanza el mismo .exe con --child, que main() atiende y
    despacha al modulo antes de construir la UI.
    """
    modulo = script[:-3] if script.endswith(".py") else script
    if CONGELADO:
        return [sys.executable, "--child", modulo, *args]
    return [sys.executable, "-u", os.path.join(RECURSOS, modulo + ".py"), *args]


def hay_hijo(script):
    """Congelado los hijos son modulos importados, no archivos que mirar."""
    modulo = script[:-3] if script.endswith(".py") else script
    if CONGELADO:
        return modulo in HIJOS
    return os.path.exists(os.path.join(RECURSOS, modulo + ".py"))


def _correr_hijo(nombre, args):
    """El .exe haciendo de interprete de uno de sus modulos."""
    if nombre == "playwright-install":
        return _bajar_chromium()
    if nombre not in HIJOS:
        print("! hijo desconocido: %s" % nombre)
        return 2
    # el panel lee este stdout linea por linea para ir pintando el log; sin
    # esto sale a bloques y la ventana parece congelada hasta el final
    try:
        sys.stdout.reconfigure(line_buffering=True, encoding="utf-8",
                               errors="replace")
    except (AttributeError, ValueError):
        pass
    sys.argv = [nombre + ".py"] + list(args)
    return importlib.import_module(nombre).main() or 0


def _bajar_chromium():
    from playwright.__main__ import main as playwright_cli
    sys.argv = ["playwright", "install", "chromium"]
    try:
        playwright_cli()
    except SystemExit as e:
        return e.code or 0
    return 0


# --- pre-flight y veredictos ----------------------------------------------
def asegurar_chromium(emitir):
    """Los scripts de Bizagi abren su PROPIO navegador con Playwright, que no es
    el Chrome del sistema y hay que bajarlo una vez.

    Desde el repo lo resuelve el `playwright install chromium` del README. En el
    .exe no hay consola donde correrlo, y meter los 150 MB del navegador dentro
    del ejecutable lo dejaria inmanejable para repartirlo: se baja solo, una vez,
    a ~/.panel_qa/browsers.
    """
    if chromium_instalado():
        return True
    if not CONGELADO:
        emitir("! Falta el navegador de Playwright. Corre:  "
               "playwright install chromium", "mal")
        return False
    emitir("> Primera vez: bajando el navegador de Playwright (~150 MB). "
           "Esto tarda unos minutos y no se repite.", "panel")
    try:
        r = subprocess.run([sys.executable, "--child", "playwright-install"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=900)
    except (OSError, subprocess.SubprocessError) as e:
        emitir("! No pude bajar el navegador: %s" % e, "mal")
        return False
    if not chromium_instalado():
        emitir("! La descarga no dejo el navegador:\n%s"
               % (r.stdout or "")[-800:], "mal")
        return False
    emitir("> Navegador listo.", "panel")
    return True


def chrome_arriba(puerto=PUERTO, timeout=1.0):
    """Chrome ya expone el puerto CDP? Es lo que decide si hay que lanzarlo."""
    try:
        with urllib.request.urlopen("http://localhost:%d/json/version" % puerto,
                                    timeout=timeout):
            return True
    except (urllib.error.URLError, OSError):
        return False


PERFIL_QA = "chrome-qa-debug"


def matar_chrome_qa(emitir):
    """Cierra solo el Chrome del perfil de QA, no el personal del usuario.

    Se filtra por la linea de comandos, que es lo unico que distingue una
    instancia de otra: taskkill por nombre se llevaria los dos por delante.
    """
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
          "Where-Object { $_.CommandLine -like '*%s*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" % PERFIL_QA)
    try:
        subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        emitir("! no pude cerrar Chrome: %s" % e, "mal")
        return False
    for _ in range(20):                  # hasta 10 s a que suelte el puerto
        if not chrome_arriba(timeout=0.5):
            return True
        time.sleep(0.5)
    emitir("! Chrome sigue respondiendo en el puerto; ciérralo a mano.", "mal")
    return False


def reiniciar_chrome(emitir):
    """Un Chrome con muchas pestanas muertas deja de navegar aunque el puerto
    CDP siga contestando. Reiniciarlo es lo unico que lo arregla."""
    emitir("> Cerrando el Chrome de QA...", "panel")
    if not matar_chrome_qa(emitir):
        return False
    emitir("> Cerrado. Abriendo uno limpio...", "panel")
    return preparar_chrome(emitir)


def preparar_chrome(emitir):
    """El observador se engancha a un Chrome ya abierto; si no hay, lo abre."""
    if chrome_arriba():
        emitir("> Chrome ya estaba arriba, lo reuso.", "panel")
        return True
    emitir("> Chrome no responde en el puerto %d, lo abro..." % PUERTO, "panel")
    subprocess.run(comando_hijo("observador_flujo", "--lanzar-chrome"),
                   cwd=BASE, capture_output=True, text=True)
    for _ in range(40):          # hasta 20 s
        if chrome_arriba():
            emitir("> Chrome listo.", "panel")
            return True
        time.sleep(0.5)
    emitir("! Chrome no levanto el puerto de depuracion.", "mal")
    return False


# Los veredictos se buscan por subcadenas SIN tildes: el log del hijo puede
# llegar con la codificacion estropeada y "cancelación" no siempre casa.
def estado_cancelacion(texto):
    """Segun el modo corrido: veredicto de Bizagi o del servicio cancel-request."""
    if "CANCEL-REQUEST PLATAFORMA" not in texto:
        return _estado_cancelacion_bizagi(texto)
    m = re.search(r"idCaso: (\S+) -> HTTP ([^\r\n]+)", texto)
    caso, http = (m.group(1), m.group(2).strip()) if m else ("?", "?")
    if "REQUEST NO CANCELADO" in texto:
        return "mal", "cancel-request no cancelo el caso %s (HTTP %s)." % (caso, http)
    return "bien", "Caso %s cancelado por cancel-request." % caso


def _estado_cancelacion_bizagi(texto):
    """bizagi_cancel_case no devuelve exit code distinto: el veredicto se lee.

    El script ya imprime un bloque con el veredicto en texto claro
    ([CASO CANCELADO] / [CASO NO ENCONTRADO] / ...), asi que eso es lo primero
    que se busca. Las lineas sueltas del log quedan como respaldo, para que un
    ejecutable congelado con la version anterior del script siga dando un
    veredicto en vez de un "revisa el log".
    """
    m = RE_CASO_INTENTO.search(texto) or RE_CASO.search(texto)
    caso = m.group(1) if m else "?"
    if "CASO CANCELADO" in texto:
        return "bien", "Caso %s cancelado." % caso
    if "CASO NO ENCONTRADO" in texto:
        return "mal", ("No se encontro el caso %s para cancelar "
                       "(ya cancelado o en un estado que no lo permite)." % caso)
    if "CANCELACION FALLIDA" in texto:
        return "mal", ("Se encontro el caso %s pero la cancelacion no se "
                       "completo; revisa el log." % caso)
    if "SIN SOLICITUDES" in texto:
        return "mal", "No se encontro ninguna solicitud para ese documento."
    if "n aceptada para caso" in texto:
        return "bien", "Caso %s cancelado." % caso
    if "Error al cancelar el caso" in texto:
        return "mal", ("No se encontro el caso %s para cancelar "
                       "(ya cancelado o en un estado que no lo permite)." % caso)
    if "No se pudo obtener" in texto:
        return "mal", "No se encontro ninguna solicitud para ese documento."
    return "", "Termino sin un veredicto claro; revisa el log."


def estado_consulta(texto):
    """Cubre los dos modos de bizagi_consultar_caso: por documento (deja
    'ultima solicitud' en el log) y por Id de caso directo (deja 'buscado en
    el buscador superior', porque ahi no hay ninguna solicitud que leer)."""
    m = RE_CASO.search(texto)
    if m:
        return "bien", "Ultima solicitud: %s" % m.group(1)
    if "buscado en el buscador superior" in texto:
        return "bien", "Caso abierto en el buscador superior."
    if "el login" in texto:
        return "mal", "Fallo el login en Bizagi."
    if "No se pudo buscar el caso" in texto:
        return "mal", "No se pudo buscar el caso en el buscador superior."
    return "mal", "No se encontro ninguna solicitud para ese documento."


def args_cancelar(valores, emitir):
    """Un modo o el otro, nunca los dos: por Bizagi se busca la ultima
    solicitud del documento; por servicio se manda el Id caso directo."""
    if valores.get("Cancelar por", "bizagi") == "request":
        id_caso = valores.get("Id caso", "").strip()
        if not id_caso:
            emitir("! Escribe el Id de caso, o cambia 'Cancelar por' a Bizagi.", "mal")
            return None
        return ["--request", id_caso]
    documento = valores.get("Documento", "").strip()
    if not documento:
        emitir("! Escribe el documento, o cambia 'Cancelar por' a servicio.", "mal")
        return None
    return [valores.get("Tipo doc", "CC"), documento]


def confirmar_cancelar(valores):
    if valores.get("Cancelar por") == "request":
        return ("Se va a cancelar el caso %s con el servicio cancel-request."
                "\n\nSeguir?" % valores.get("Id caso", "").strip())
    return ("Se va a cancelar la ultima solicitud del documento %s %s en "
            "Bizagi.\n\nSeguir?" % (valores.get("Tipo doc", ""),
                                    valores.get("Documento", "").strip()))


def args_consultar(valores, emitir):
    """El radio "Buscar por" manda, y con el solo hay un campo que llenar: por
    Id de caso se busca directo (--caso); por cedula se usan Tipo doc +
    Documento. Lo que haya quedado escrito en el otro modo se ignora."""
    modo = valores.get("Buscar por", "caso")
    if modo == "caso":
        id_caso = valores.get("Id caso", "").strip()
        if not id_caso:
            emitir("! Escribe el Id de caso, o cambia 'Buscar por' a Cedula.", "mal")
            return None
        return ["--caso", id_caso]
    documento = valores.get("Documento", "").strip()
    if not documento:
        emitir("! Escribe la cedula, o cambia 'Buscar por' a Id de caso.", "mal")
        return None
    return [valores.get("Tipo doc", "CC"), documento]


def args_consultar_json(valores, emitir):
    """Este flujo busca directo por numero de solicitud; no hay documento."""
    id_caso = valores.get("Id caso", "").strip()
    if not id_caso:
        emitir("! Escribe el Id de caso (numero de solicitud).", "mal")
        return None
    return [id_caso]


def estado_consultar_json(texto):
    """bizagi_consultar_json.py no devuelve exit code distinto: el veredicto
    se lee del log, igual que los demas hijos de Bizagi."""
    m = RE_CASO_JSON.search(texto)
    caso = m.group(1) if m else "?"
    if "registro obtenido" in texto:
        return "bien", "Caso %s: registro obtenido en el JSON." % caso
    if "No se encontraron registros" in texto:
        return "mal", "Caso %s: la consulta no devolvio registros." % caso
    if "el login" in texto:
        return "mal", "Fallo el login en Bizagi."
    if "navegar a Analista operativo" in texto:
        return "mal", "No se pudo navegar a Analista operativo."
    if "buscar el caso" in texto:
        return "mal", "No se pudo buscar el caso %s en Analista operativo." % caso
    return "mal", "Termino sin un veredicto claro; revisa el log."


def args_biometria(valores, emitir):
    """Los mismos 3 campos que antes pedia la suite de TestNG (idCaso,
    typeDocument, identification), ahora como argumentos de linea de comandos
    directos para biometria_api.py -- ya no hace falta escribir una copia de
    testng-biometry.xml."""
    id_caso = valores.get("Id caso", "").strip()
    documento = valores.get("Documento", "").strip()
    if not id_caso or not documento:
        emitir("! Escribe el Id de caso y el Documento.", "mal")
        return None
    return ["--caso", id_caso, "--tipo", valores.get("Tipo doc", "CO1C"), "--doc", documento]


def estado_biometria(texto):
    """biometria_api.py imprime un veredicto final claro; se busca por
    subcadena, igual que los demas hijos."""
    if "BIOMETRIA OK" in texto:
        return "bien", "Biometria completada correctamente."
    m = re.search(r"BIOMETRIA FALLO en paso (\d): (.+)", texto)
    if m:
        return "mal", "Fallo en el paso %s (%s)." % (m.group(1), m.group(2).strip())
    return "mal", "Termino sin un veredicto claro; revisa el log."


# --- registro de herramientas ---------------------------------------------
# tipo: "texto" | "opcion" | "check".  arg=None => argumento posicional.
HERRAMIENTAS = [
    {
        "id": "observador",
        "nombre": "Observador de flujos",
        "script": "observador_flujo.py",
        "boton": "Iniciar captura",
        "parada": "centinela",
        "stop_file": STOP_FILE,
        "previo": preparar_chrome,
        "ayuda": "Navega a mano en Chrome; captura pantallas, requests y websocket.",
        "campos": [
            {"tipo": "texto", "arg": "--flujo", "etiqueta": "Flujo",
             "valor": "login-credito", "ancho": 26},
            {"tipo": "texto", "arg": "--solo-url", "etiqueta": "Empezar en la URL que contenga",
             "valor": RUTAS_LOGIN, "ancho": 42},
            {"tipo": "texto", "arg": "--documento", "etiqueta": "Documento (opcional)",
             "valor": "", "ancho": 16},
            {"tipo": "check", "arg": "--limpiar",
             "etiqueta": "Empezar sin sesion previa (como incognito)",
             "valor": True},
            # el front lo llama desde su servidor: sin esto no sale en la evidencia
            {"tipo": "check", "arg": "--request-check",
             "etiqueta": "Consultar /request/check en el login, al detectar el documento y en información personal (usa token.txt)",
             "valor": True},
            {"tipo": "check", "arg": "--generar-esquemas",
             "etiqueta": "Tomar esta corrida como baseline de esquemas",
             "valor": False},
        ],
    },
    {
        "id": "analitica",
        "nombre": "Analitica dataLayer",
        "script": "observador_analitica.py",
        "boton": "Iniciar captura",
        "parada": "centinela",
        "stop_file": STOP_FILE_ANALITICA,
        "previo": preparar_chrome,
        "ayuda": "Haces el flujo a mano; anota cada push al dataLayer y filtra el "
                 "ruido de GTM, igual que TermsAndConditionsAnalyticsSolid.",
        "campos": [
            {"tipo": "texto", "arg": "--flujo", "etiqueta": "Flujo",
             "valor": "terminos", "ancho": 26},
            {"tipo": "texto", "arg": "--solo-url", "etiqueta": "Solo URL que contenga",
             "valor": RUTAS_APP, "ancho": 42},
        ],
    },
    {
        "id": "biometria",
        "nombre": "Suite biometria",
        "script": "biometria_api.py",
        "boton": "Correr suite",
        "parada": None,
        "ayuda": "Autenticacion biometrica + firma de documentos, pegando "
                 "directo a los mismos endpoints que el framework Java "
                 "(sin Maven, sin navegador).",
        "argumentos": args_biometria,
        "estado": estado_biometria,
        "campos": [
            {"tipo": "texto", "solo_forma": True, "etiqueta": "Id caso",
             "valor": "", "ancho": 14, "requerido": True},
            {"tipo": "opcion", "solo_forma": True, "etiqueta": "Tipo doc",
             "opciones": ["CO1C", "CO1E"], "valor": "CO1C", "ancho": 8},
            {"tipo": "texto", "solo_forma": True, "etiqueta": "Documento",
             "valor": "", "ancho": 20, "requerido": True},
        ],
    },
    {
        "id": "bizagi_cancelar",
        "nombre": "Cancelar caso Bizagi",
        "script": "bizagi_cancel_case.py",
        "boton": "Cancelar caso",
        "parada": None,
        "previo": asegurar_chromium,
        "ayuda": "Una de las dos formas, no las dos: por Bizagi busca la ultima "
                 "solicitud del documento y la cancela en Administracion de "
                 "procesos; por servicio llama POST cancel-request con el Id caso.",
        "confirmar": confirmar_cancelar,
        "estado": estado_cancelacion,
        "argumentos": args_cancelar,
        "campos": [
            {"tipo": "radio", "solo_forma": True, "etiqueta": "Cancelar por",
             "opciones": [("Bizagi (por documento)", "bizagi"),
                          ("Servicio cancel-request (por Id caso)", "request")],
             "valor": "bizagi",
             "habilita": {"bizagi": ["Sin ventana del navegador", "Tipo doc",
                                     "Documento"],
                          "request": ["Id caso"]}},
            # el modo servicio la ignora: --request corre antes que el navegador
            {"tipo": "check", "arg": "--headless",
             "etiqueta": "Sin ventana del navegador", "valor": True},
            {"tipo": "opcion", "solo_forma": True, "etiqueta": "Tipo doc",
             "opciones": ["CC", "CE"], "valor": "CC", "ancho": 6},
            {"tipo": "texto", "solo_forma": True, "etiqueta": "Documento",
             "valor": "", "ancho": 20},
            {"tipo": "texto", "solo_forma": True, "etiqueta": "Id caso",
             "valor": "", "ancho": 14},
        ],
    },
    {
        "id": "bizagi_consultar",
        "nombre": "Consultar caso Bizagi",
        "script": "bizagi_consultar_caso.py",
        "boton": "Consultar",
        # deja el navegador abierto a proposito; se cierra con Detener
        "parada": "terminar",
        "previo": asegurar_chromium,
        "ayuda": "Se busca de UNA de las dos formas, no de las dos: por Id de "
                 "caso va directo al buscador superior; por cedula muestra la "
                 "ultima solicitud del documento. El navegador queda abierto.",
        "estado": estado_consulta,
        "argumentos": args_consultar,
        "campos": [
            {"tipo": "radio", "solo_forma": True, "etiqueta": "Buscar por",
             "opciones": [("Id de caso", "caso"), ("Cedula", "documento")],
             "valor": "caso",
             "habilita": {"caso": ["Id caso"],
                          "documento": ["Tipo doc", "Documento"]}},
            {"tipo": "texto", "solo_forma": True, "etiqueta": "Id caso",
             "valor": "", "ancho": 14},
            {"tipo": "opcion", "solo_forma": True, "etiqueta": "Tipo doc",
             "opciones": ["CC", "CE"], "valor": "CC", "ancho": 6},
            {"tipo": "texto", "solo_forma": True, "etiqueta": "Documento",
             "valor": "", "ancho": 20},
        ],
    },
    {
        "id": "bizagi_consultar_json",
        "nombre": "Consultar JSON",
        "script": "bizagi_consultar_json.py",
        "boton": "Consultar",
        # en headless (por defecto) el propio script cierra el navegador
        # apenas imprime el JSON; sin headless queda abierto y se cierra con
        # Detener, igual que "Consultar caso Bizagi"
        "parada": "terminar",
        "previo": asegurar_chromium,
        "ayuda": "Busca directo por Id de caso en GCR_Solicitudes - Analista "
                 "operativo (marca 'incluir todo' antes de buscar) y vuelca "
                 "la fila de resultados como JSON en el log.",
        "estado": estado_consultar_json,
        "argumentos": args_consultar_json,
        "campos": [
            {"tipo": "check", "arg": "--headless",
             "etiqueta": "Sin ventana del navegador", "valor": True},
            {"tipo": "texto", "solo_forma": True, "etiqueta": "Id caso",
             "valor": "", "ancho": 14, "requerido": True},
        ],
    },
]


# --- lectura de la evidencia ----------------------------------------------
def _json_o_nada(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def leer_corrida(d):
    """Una fila de la tabla, armada con lo que la corrida ya dejo en disco."""
    nombre = os.path.basename(d)
    fila = {"dir": d, "nombre": nombre, "flujo": "", "pasos": 0, "requests": 0,
            "ws": 0, "fallos": 0, "esquemas": "-", "orden": os.path.getmtime(d)}
    m = RE_MARCA.search(nombre)
    fila["fecha"] = ("%s-%s %s:%s" % (m.group(2), m.group(3), m.group(4), m.group(5))
                     if m else time.strftime("%m-%d %H:%M",
                                             time.localtime(fila["orden"])))
    resumen = _json_o_nada(os.path.join(d, "resumen.json"))
    if resumen:
        pasos = resumen.get("pasos") or []
        # --rehacer-reporte guarda el nombre de la carpeta como flujo, con
        # marca de tiempo incluida; para la tabla sobra
        fila["flujo"] = RE_MARCA.sub("", resumen.get("flujo", ""))
        fila["pasos"] = len(pasos)
        fila["requests"] = sum(p.get("requests", 0) for p in pasos)
        fila["ws"] = sum(p.get("websocket", 0) for p in pasos)
        fila["fallos"] = sum(p.get("fallos", 0) for p in pasos)
    if not fila["flujo"]:
        fila["flujo"] = RE_MARCA.sub("", nombre)
    val = _json_o_nada(os.path.join(d, "validacion_esquemas.json"))
    if val:
        n = (val.get("resumen") or {}).get("con_hallazgos", 0)
        fila["esquemas"] = "ok" if not n else "%d hallazgo%s" % (n, "" if n == 1 else "s")
    return fila


def listar_corridas():
    if not os.path.isdir(EVIDENCIAS):
        return []
    dirs = [os.path.join(EVIDENCIAS, d) for d in os.listdir(EVIDENCIAS)
            if os.path.isdir(os.path.join(EVIDENCIAS, d))]
    return sorted((leer_corrida(d) for d in dirs),
                  key=lambda x: x["orden"], reverse=True)


# --- una pestana por herramienta ------------------------------------------
class Herramienta(ttk.Frame):
    def __init__(self, padre, spec):
        super().__init__(padre)
        self.spec = spec
        self.proc = None
        self.cola = queue.Queue()
        self.salida = []          # todo el stdout, para el veredicto final
        self.dir_corrida = None   # carpeta de evidencia de la ultima corrida
        self.vars = {}
        self.campos_ui = {}       # etiqueta -> (label, control), para apagarlos
        self.radios = []          # campos "radio", que mandan sobre los demas
        self._construir()

    # -- UI
    def _construir(self):
        cfg = ttk.Frame(self, padding=(12, 12, 12, 4))
        cfg.pack(fill="x")
        if self.spec.get("ayuda"):
            ttk.Label(cfg, text=self.spec["ayuda"], foreground="#666").grid(
                row=0, column=0, columnspan=8, sticky="w", pady=(0, 10))

        col = 0
        fila = 1
        fila_check = 99     # los checks van abajo, uno por fila: en la misma celda se tapan
        for campo in self.spec["campos"]:
            etq = campo["etiqueta"]
            if campo["tipo"] == "check":
                var = tk.BooleanVar(value=campo["valor"])
                chk = ttk.Checkbutton(cfg, text=etq, variable=var)
                chk.grid(row=fila_check, column=0, columnspan=8, sticky="w",
                         pady=(8 if fila_check == 99 else 2, 0))
                self.campos_ui[etq] = (None, chk)   # para que un radio lo apague
                fila_check += 1
            elif campo["tipo"] == "radio":
                # Un radio parte el formulario en modos excluyentes y apaga los
                # campos del modo que no esta elegido. Es la unica forma de que
                # se vea que hay que llenar uno U otro: con los dos activos,
                # todo el mundo asume que los dos son obligatorios.
                var = tk.StringVar(value=campo["valor"])
                if col:
                    col, fila = 0, fila + 1
                ttk.Label(cfg, text=etq).grid(row=fila, column=col, sticky="w")
                caja = ttk.Frame(cfg)
                caja.grid(row=fila, column=col + 1, columnspan=7,
                          padx=(6, 0), sticky="w")
                for texto, valor in campo["opciones"]:
                    ttk.Radiobutton(caja, text=texto, value=valor, variable=var,
                                    command=self._sincronizar_modos).pack(
                                        side="left", padx=(0, 14))
                self.radios.append(campo)
                col, fila = 0, fila + 1
            else:
                var = tk.StringVar(value=campo["valor"])
                lbl = ttk.Label(cfg, text=etq)
                lbl.grid(row=fila, column=col, sticky="w")
                if campo["tipo"] == "opcion":
                    w = ttk.Combobox(cfg, textvariable=var, values=campo["opciones"],
                                     width=campo.get("ancho", 10), state="readonly")
                else:
                    w = ttk.Entry(cfg, textvariable=var, width=campo.get("ancho", 24))
                    w.bind("<Return>", lambda _e: self.ejecutar())
                w.grid(row=fila, column=col + 1, padx=(6, 18), sticky="w")
                self.campos_ui[etq] = (lbl, w)
                col += 2
                if col >= 6:
                    col, fila = 0, fila + 1
            self.vars[etq] = var

        self._sincronizar_modos()

        botones = ttk.Frame(self, padding=(12, 10, 12, 4))
        botones.pack(fill="x")
        self.b_ir = ttk.Button(botones, text=self.spec["boton"], command=self.ejecutar)
        self.b_ir.pack(side="left")
        self.b_parar = ttk.Button(botones, text=self._texto_parada(),
                                  command=self.detener, state="disabled")
        self.b_parar.pack(side="left", padx=8)
        self.b_reporte = None
        if self.spec["parada"] == "centinela":
            # separadas a proposito: a veces uno corta la captura para seguir
            # navegando y solo quiere el reporte mas tarde
            self.b_solo_parar = ttk.Button(botones, text="Detener sin reporte",
                                           command=self.detener_seco,
                                           state="disabled")
            self.b_solo_parar.pack(side="left")
            self.b_reporte = ttk.Button(botones, text="Generar reporte",
                                        command=self.generar_reporte)
            self.b_reporte.pack(side="left", padx=8)
        else:
            self.b_solo_parar = None
        ttk.Button(botones, text="Limpiar log", command=self.limpiar).pack(side="left")
        if self.spec.get("previo") is preparar_chrome:
            ttk.Button(botones, text="Reiniciar Chrome",
                       command=self.reiniciar_chrome).pack(side="right")

        self.estado = tk.StringVar(value="Listo.")
        self.lbl_estado = ttk.Label(self, textvariable=self.estado, padding=(14, 2))
        self.lbl_estado.pack(fill="x")

        marco = ttk.Frame(self, padding=(12, 4, 12, 12))
        marco.pack(fill="both", expand=True)
        self.log = tk.Text(marco, wrap="none", bg="#101010", fg="#d8d8d8",
                           insertbackground="#d8d8d8", font=("Consolas", 9),
                           relief="flat")
        barra = ttk.Scrollbar(marco, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=barra.set, state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        for tag, color in (("paso", "#7fb2ff"), ("ws", "#c9a0ff"), ("mal", "#ff8a80"),
                           ("bien", "#9be29b"), ("panel", "#ffd479")):
            self.log.tag_configure(tag, foreground=color)

    def _sincronizar_modos(self):
        """Deja activos solo los campos del modo elegido en cada radio.

        Los demas quedan en gris y no se pueden escribir, asi que el
        formulario dice por si solo cual es el dato que hace falta. El hook de
        argumentos ignora igual lo que haya quedado escrito en el otro modo.
        """
        for campo in self.radios:
            modo = self.vars[campo["etiqueta"]].get()
            for destino, etiquetas in campo["habilita"].items():
                activo = destino == modo
                for etq in etiquetas:
                    par = self.campos_ui.get(etq)
                    if not par:
                        continue
                    lbl, w = par
                    if isinstance(w, ttk.Combobox):
                        w.configure(state="readonly" if activo else "disabled")
                    else:
                        w.configure(state="normal" if activo else "disabled")
                    if lbl is not None:
                        lbl.configure(foreground="" if activo else "#999")

    def _texto_parada(self):
        return {"centinela": "Detener y generar reporte",
                "terminar": "Cerrar navegador"}.get(self.spec["parada"], "Detener")

    # -- log
    def emitir(self, linea, tag=None):
        self.cola.put((linea, tag))

    def escribir(self, linea, tag=None):
        if tag is None:
            t = linea.lstrip()
            # el fallo manda sobre el tipo de linea: un [ws ...] FAIL tiene
            # que verse rojo, no del morado de los websockets
            if "FAIL" in linea or "ERROR" in linea or t.startswith("!"):
                tag = "mal"
            elif t.startswith("[paso"):
                tag = "paso"
            elif t.startswith("[ws"):
                tag = "ws"
            elif t.startswith("ok ") or "Reporte:" in linea:
                tag = "bien"
        self.log.configure(state="normal")
        self.log.insert("end", linea.rstrip() + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def drenar(self):
        try:
            while True:
                self.escribir(*self.cola.get_nowait())
        except queue.Empty:
            pass

    def limpiar(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    def reiniciar_chrome(self):
        if self.ocupada():
            messagebox.showinfo("Captura en curso",
                                "Detén la captura antes de reiniciar Chrome.")
            return
        if not messagebox.askyesno(
                "Reiniciar Chrome",
                "Se cierra el Chrome de QA y se abre uno limpio.\n\n"
                "Se pierden las pestañas abiertas y la sesión.\n\n"
                "Seguir?"):
            return
        self.estado.set("Reiniciando Chrome...")
        threading.Thread(
            target=lambda: (reiniciar_chrome(self.emitir),
                            self.after(0, lambda: self.estado.set("Chrome listo."))),
            daemon=True).start()

    # -- ejecucion
    def ocupada(self):
        return self.proc is not None and self.proc.poll() is None

    def _base(self):
        """El comando sin argumentos: un script de este repo, o algo externo."""
        if self.spec.get("comando"):
            return [c() if callable(c) else c for c in self.spec["comando"]]
        return comando_hijo(self.spec["script"])

    def valores(self):
        return {c["etiqueta"]: str(self.vars[c["etiqueta"]].get()).strip()
                for c in self.spec["campos"] if c["tipo"] != "check"}

    def construir_cmd(self):
        """Del formulario al comando. Los posicionales van al final, en orden."""
        cmd = self._base()
        posicionales = []
        for campo in self.spec["campos"]:
            valor = self.vars[campo["etiqueta"]].get()
            if campo["tipo"] == "check":
                if valor:
                    cmd.append(campo["arg"])
                continue
            valor = str(valor).strip()
            if not valor:
                if campo.get("requerido"):
                    return None, campo["etiqueta"]
                continue
            if campo.get("solo_forma"):
                continue          # alimenta el hook de argumentos, no la linea
            if campo.get("arg"):
                cmd += [campo["arg"], valor]
            else:
                posicionales.append(valor)
        if self.spec["parada"] == "centinela":
            cmd += ["--stop-file", self.spec["stop_file"]]
        return cmd + posicionales, None

    def ejecutar(self):
        if self.ocupada():
            return
        cmd, falta = self.construir_cmd()
        if falta:
            messagebox.showinfo("Falta un dato", "Escribe %s." % falta)
            return
        aviso = self.spec.get("confirmar")
        if callable(aviso):
            if not messagebox.askyesno(self.spec["nombre"], aviso(self.valores())):
                return
        elif aviso:
            texto = aviso
            for etq, var in self.vars.items():
                texto = texto.replace("{%s}" % etq, str(var.get()))
            if not messagebox.askyesno(self.spec["nombre"], texto):
                return
        self.limpiar()
        self.salida = []
        self.b_ir.configure(state="disabled")
        self.lbl_estado.configure(foreground="")
        self.estado.set("Ejecutando...")
        threading.Thread(target=self._hilo, args=(cmd,), daemon=True).start()

    def _hilo(self, cmd, usar_previo=True):
        """Pre-flight, subproceso y bombeo del stdout. Fuera del hilo de la UI
        para que la ventana no se congele.

        usar_previo=False para comandos del mismo script que no necesitan el
        pre-flight (--rehacer-reporte trabaja sobre disco, no sobre Chrome).
        """
        previo = self.spec.get("previo") if usar_previo else None
        if previo and not previo(self.emitir):
            self.after(0, self._fin)
            return
        hook = self.spec.get("argumentos")
        if hook:
            extra = hook(self.valores(), self.emitir)
            if extra is None:
                self.after(0, self._fin)
                return
            cmd = cmd + extra
        stop = self.spec.get("stop_file")
        if stop and os.path.exists(stop):
            os.remove(stop)                    # sobra de una corrida anterior
        self.emitir("> " + " ".join(cmd[1:]), "panel")
        # el hijo imprime en utf-8 y no en la codificacion de la consola, para
        # que las tildes no lleguen rotas al log
        entorno = dict(os.environ, PYTHONIOENCODING="utf-8")
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=self.spec.get("cwd", BASE),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                errors="replace", bufsize=1, env=entorno)
        except OSError as e:
            self.emitir("! No pude lanzar el proceso: %s" % e, "mal")
            self.after(0, self._fin)
            return
        self.after(0, self._corriendo)
        for linea in self.proc.stdout:
            self.salida.append(linea)
            if linea.startswith("Evidencia:"):
                self.dir_corrida = linea.split(":", 1)[1].strip()
            self.cola.put((linea, None))
        self.proc.wait()
        self.after(0, self._fin)

    def _corriendo(self):
        if self.spec["parada"]:
            self.b_parar.configure(state="normal")
        if self.b_solo_parar:
            self.b_solo_parar.configure(state="normal")
        self.estado.set({"centinela": "Capturando. Navega en Chrome; al terminar, Detener.",
                         "terminar": "Corriendo. El navegador queda abierto."}
                        .get(self.spec["parada"], "Corriendo..."))

    def _fin(self):
        self.b_ir.configure(state="normal")
        self.b_parar.configure(state="disabled")
        if self.b_solo_parar:
            self.b_solo_parar.configure(state="disabled")
        self.proc = None
        veredicto = self.spec.get("estado")
        if veredicto:
            tag, msg = veredicto("".join(self.salida))
            self.estado.set(msg)
            self.lbl_estado.configure(
                foreground={"bien": "#1b7f2b", "mal": "#c62828"}.get(tag, ""))
        else:
            self.estado.set("Terminado.")
        for cb in getattr(self, "al_terminar", []):
            cb()

    def detener(self, con_reporte=True):
        if not self.ocupada():
            return
        self.b_parar.configure(state="disabled")
        if self.b_solo_parar:
            self.b_solo_parar.configure(state="disabled")
        if self.spec["parada"] == "centinela":
            self.estado.set("Cerrando y generando reporte..." if con_reporte
                            else "Cerrando sin generar el reporte...")
            with open(self.spec["stop_file"], "w", encoding="utf-8") as f:
                f.write("" if con_reporte else SIN_REPORTE)
        else:
            self.estado.set("Cerrando...")
            self.proc.terminate()

    def detener_seco(self):
        """Corta la captura y deja la evidencia cruda; el reporte, cuando quieras."""
        self.detener(con_reporte=False)

    def generar_reporte(self):
        """--rehacer-reporte sobre la ultima corrida (o la mas reciente en disco)."""
        if self.ocupada():
            messagebox.showinfo("Captura en curso",
                                "Detén la captura antes de generar el reporte.")
            return
        d = self.dir_corrida
        if not d or not os.path.isdir(d):
            corridas = listar_corridas()
            d = corridas[0]["dir"] if corridas else None
        if not d:
            messagebox.showinfo("Sin corridas", "Todavia no hay evidencia capturada.")
            return
        self.limpiar()
        self.salida = []
        self.dir_corrida = d
        self.estado.set("Generando reporte de %s..." % os.path.basename(d))
        cmd = comando_hijo(self.spec["script"], "--rehacer-reporte", d)
        threading.Thread(target=self._hilo, args=(cmd, False), daemon=True).start()


# --- pestana de corridas ---------------------------------------------------
class Corridas(ttk.Frame):
    def __init__(self, padre, panel):
        super().__init__(padre)
        self.panel = panel
        self.filas = {}
        self._construir()
        self.refrescar()

    def _construir(self):
        cols = ("fecha", "flujo", "pasos", "requests", "ws", "fallos", "esquemas")
        anchos = (110, 190, 55, 80, 50, 65, 110)
        titulos = ("Fecha", "Flujo", "Pasos", "Requests", "WS", "4xx/5xx", "Esquemas")
        marco = ttk.Frame(self, padding=12)
        marco.pack(fill="both", expand=True)
        self.tabla = ttk.Treeview(marco, columns=cols, show="headings", selectmode="browse")
        for c, a, t in zip(cols, anchos, titulos):
            self.tabla.heading(c, text=t)
            self.tabla.column(c, width=a,
                              anchor="w" if c in ("flujo", "fecha", "esquemas") else "center")
        barra = ttk.Scrollbar(marco, orient="vertical", command=self.tabla.yview)
        self.tabla.configure(yscrollcommand=barra.set)
        self.tabla.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        self.tabla.tag_configure("mal", foreground="#c62828")
        self.tabla.bind("<Double-1>", lambda _e: self.abrir_reporte())

        pie = ttk.Frame(self, padding=(12, 0, 12, 6))
        pie.pack(fill="x")
        ttk.Button(pie, text="Abrir reporte", command=self.abrir_reporte).pack(side="left")
        ttk.Button(pie, text="Abrir carpeta", command=self.abrir_carpeta).pack(side="left", padx=8)
        ttk.Button(pie, text="Revalidar", command=self.revalidar).pack(side="left")
        ttk.Button(pie, text="Refrescar", command=self.refrescar).pack(side="left", padx=8)
        ttk.Button(pie, text="Borrar", command=self.borrar).pack(side="right")

        self.estado = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.estado, padding=(14, 0, 14, 8)).pack(fill="x")

    def refrescar(self):
        self.tabla.delete(*self.tabla.get_children())
        self.filas.clear()
        corridas = listar_corridas()
        for c in corridas:
            tag = "mal" if (c["fallos"] or "hallazgo" in c["esquemas"]) else ""
            iid = self.tabla.insert(
                "", "end", tags=(tag,),
                values=(c["fecha"], c["flujo"], c["pasos"], c["requests"],
                        c["ws"] or "", c["fallos"] or "", c["esquemas"]))
            self.filas[iid] = c
        self.estado.set("%d corrida(s) en evidences/" % len(corridas))

    def _seleccionada(self):
        sel = self.tabla.selection()
        if not sel:
            messagebox.showinfo("Sin seleccion", "Escoge una corrida de la lista.")
            return None
        return self.filas.get(sel[0])

    def abrir_reporte(self):
        c = self._seleccionada()
        if not c:
            return
        ruta = os.path.join(c["dir"], "reporte.html")
        if not os.path.exists(ruta):
            messagebox.showinfo("Sin reporte", "Esa corrida no tiene reporte.html.")
            return
        webbrowser.open("file:///" + os.path.abspath(ruta).replace("\\", "/"))

    def abrir_carpeta(self):
        c = self._seleccionada()
        if not c:
            return
        if hasattr(os, "startfile"):
            os.startfile(c["dir"])          # Windows
        else:
            webbrowser.open("file:///" + c["dir"].replace("\\", "/"))

    def revalidar(self):
        """--rehacer-reporte sobre la corrida: es lo que hay que correr cada vez
        que se corrige el baseline de esquemas."""
        c = self._seleccionada()
        if not c:
            return
        herr = self.panel.herramientas["observador"]
        if herr.ocupada():
            messagebox.showinfo("Ocupado", "Hay una captura en curso.")
            return
        self.panel.tabs.select(herr)
        herr.limpiar()
        herr.salida = []
        herr.estado.set("Revalidando %s..." % c["nombre"])
        cmd = comando_hijo("observador_flujo", "--rehacer-reporte", c["dir"])
        threading.Thread(target=herr._hilo, args=(cmd, False), daemon=True).start()

    def borrar(self):
        c = self._seleccionada()
        if not c:
            return
        if not messagebox.askyesno(
                "Borrar evidencia",
                "Se va a borrar de forma permanente:\n\n%s\n\n"
                "Con sus pantallazos, requests y reporte. No hay papelera.\n\n"
                "Seguro?" % c["dir"]):
            return
        try:
            shutil.rmtree(c["dir"])
        except OSError as e:
            messagebox.showerror("No se pudo borrar", str(e))
            return
        self.refrescar()


# --- validaciones API por lote --------------------------------------------
TIPOS_DOC = ["CC", "CE"]


def solo_unicos(docs):
    """El DataProvider deduplica por numero con un LinkedHashSet; se hace lo
    mismo aqui para poder avisar cuantos van a correr de verdad."""
    vistos, unicos = set(), []
    for tipo, numero in docs:
        if numero not in vistos:
            vistos.add(numero)
            unicos.append((tipo, numero))
    return unicos


class Validaciones(ttk.Frame):
    """Corre los servicios de elegibilidad sobre una lista de documentos.

    Pega la lista y lanza validaciones_api.py, el puerto en Python de
    ApiTest.testValidationServices: mismos endpoints, sin Java ni Maven de por
    medio. El hijo escupe muchas lineas; aqui solo se muestran las que sirven y
    el resto queda en un archivo aparte.
    """

    def __init__(self, padre):
        super().__init__(padre)
        self.proc = None
        self.cola = queue.Queue()
        self.servicios = list(SERVICIOS_FIJOS)   # columnas, en orden del framework
        self.resultados = {}         # documento -> {servicio: estado}
        self.ruta_log = None
        self.ok = False              # True cuando la ultima corrida cerro sin FAIL
        self._construir()

    def _construir(self):
        arriba = ttk.Frame(self, padding=(12, 12, 12, 4))
        arriba.pack(fill="x")
        ttk.Label(arriba, text="Tipo").grid(row=0, column=0, sticky="w")
        ttk.Label(arriba, text="Identificacion").grid(row=0, column=1, sticky="w",
                                                      padx=(6, 0))
        self.v_tipo = tk.StringVar(value=TIPOS_DOC[0])
        ttk.Combobox(arriba, textvariable=self.v_tipo, values=TIPOS_DOC, width=5,
                     state="readonly").grid(row=1, column=0, sticky="w")
        self.v_doc = tk.StringVar()
        e = ttk.Entry(arriba, textvariable=self.v_doc, width=20)
        e.grid(row=1, column=1, sticky="w", padx=(6, 12))
        e.bind("<Return>", lambda _ev: self.agregar())     # numero, Enter, numero...
        self.foco = e
        ttk.Button(arriba, text="Agregar", command=self.agregar).grid(row=1, column=2)
        ttk.Button(arriba, text="Quitar", command=self.quitar).grid(row=1, column=3,
                                                                    padx=8)
        ttk.Button(arriba, text="Cargar lista actual",
                   command=self.cargar_actual).grid(row=1, column=4)
        ttk.Button(arriba, text="Vaciar", command=self.vaciar).grid(row=1, column=5,
                                                                    padx=8)

        md = ttk.Frame(self, padding=(12, 8, 12, 0))
        md.pack(fill="x")
        self.docs = []
        self.tabla_docs = ttk.Treeview(md, columns=("tipo", "doc"), show="headings",
                                       selectmode="extended", height=6)
        self.tabla_docs.heading("tipo", text="Tipo")
        self.tabla_docs.heading("doc", text="Identificacion")
        self.tabla_docs.column("tipo", width=60, anchor="center")
        self.tabla_docs.column("doc", width=180, anchor="w")
        sb = ttk.Scrollbar(md, orient="vertical", command=self.tabla_docs.yview)
        self.tabla_docs.configure(yscrollcommand=sb.set)
        self.tabla_docs.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")
        self.tabla_docs.tag_configure("repetido", foreground="#999")
        self.tabla_docs.bind("<Delete>", lambda _ev: self.quitar())

        botones = ttk.Frame(self, padding=(12, 8, 12, 4))
        botones.pack(fill="x")
        self.b_ir = ttk.Button(botones, text="Reemplazar y ejecutar", command=self.ejecutar)
        self.b_ir.pack(side="left")
        self.b_parar = ttk.Button(botones, text="Detener", command=self.detener,
                                  state="disabled")
        self.b_parar.pack(side="left", padx=8)
        ttk.Button(botones, text="Cargar lista actual",
                   command=self.cargar_actual).pack(side="left")
        ttk.Button(botones, text="Abrir log completo",
                   command=self.abrir_log).pack(side="left", padx=8)

        self.estado = tk.StringVar(value="Pega la lista de documentos.")
        self.lbl = ttk.Label(self, textvariable=self.estado, padding=(14, 2))
        self.lbl.pack(fill="x")

        panes = ttk.PanedWindow(self, orient="vertical")
        panes.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        mt = ttk.Frame(panes)
        self.tabla = ttk.Treeview(mt, columns=("documento",), show="headings",
                                  selectmode="browse", height=8)
        self.tabla.heading("documento", text="Documento")
        self.tabla.column("documento", width=130, anchor="w")
        sb2 = ttk.Scrollbar(mt, orient="vertical", command=self.tabla.yview)
        sbh = ttk.Scrollbar(mt, orient="horizontal", command=self.tabla.xview)
        self.tabla.configure(yscrollcommand=sb2.set, xscrollcommand=sbh.set)
        sb2.pack(side="right", fill="y")
        sbh.pack(side="bottom", fill="x")
        self.tabla.pack(side="left", fill="both", expand=True)
        panes.add(mt, weight=3)

        ml = ttk.Frame(panes)
        self.log = tk.Text(ml, wrap="none", bg="#101010", fg="#d8d8d8", height=8,
                           font=("Consolas", 9), relief="flat")
        sb3 = ttk.Scrollbar(ml, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb3.set, state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        sb3.pack(side="right", fill="y")
        for tag, color in (("mal", "#ff8a80"), ("bien", "#9be29b"), ("panel", "#ffd479")):
            self.log.tag_configure(tag, foreground=color)
        panes.add(ml, weight=2)

        self._columnas()      # las columnas fijas se ven desde el arranque

    # -- log
    def emitir(self, linea, tag=None):
        self.cola.put((linea, tag))

    def drenar(self):
        try:
            while True:
                linea, tag = self.cola.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", linea.rstrip() + "\n", tag or ())
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass

    # -- lista de documentos
    def agregar(self):
        numero = re.sub(r"\D", "", self.v_doc.get())
        if not numero:
            return
        self.docs.append((self.v_tipo.get(), numero))
        self.v_doc.set("")
        self.foco.focus_set()
        self.refrescar_docs()

    def quitar(self):
        for iid in sorted(self.tabla_docs.selection(), key=int, reverse=True):
            self.docs.pop(int(iid))
        self.refrescar_docs()

    def vaciar(self):
        self.docs = []
        self.refrescar_docs()

    def refrescar_docs(self):
        self.tabla_docs.delete(*self.tabla_docs.get_children())
        vistos = set()
        for i, (tipo, numero) in enumerate(self.docs):
            repe = numero in vistos
            vistos.add(numero)
            self.tabla_docs.insert("", "end", iid=str(i),
                                   tags=("repetido",) if repe else (),
                                   values=(tipo, numero))
        unicos = solo_unicos(self.docs)
        rep = len(self.docs) - len(unicos)
        if not self.docs:
            self.estado.set("Agrega documentos a la lista.")
        else:
            self.estado.set("%d documento(s), %d se van a correr%s"
                            % (len(self.docs), len(unicos),
                               "  (%d repetido(s), en gris)" % rep if rep else ""))
        self.tabla_docs.see(str(len(self.docs) - 1)) if self.docs else None

    def cargar_actual(self):
        """Trae al cuadro la ultima lista que se corrio desde este panel."""
        datos = _json_o_nada(VALIDACIONES_DOCS)
        if not isinstance(datos, list):
            messagebox.showinfo("Sin lista", "Todavia no hay una lista guardada.")
            return
        self.docs = [(d.get("tipo", ""), d.get("numero", "")) for d in datos
                    if isinstance(d, dict)]
        self.refrescar_docs()

    def guardar_docs_actuales(self, unicos):
        """Persiste la lista que se va a correr, para que 'Cargar lista
        actual' la recuerde la proxima vez (reemplaza al DataProvider de
        Java, que cumplia el mismo papel de 'lista de trabajo')."""
        try:
            os.makedirs(DIR_DATOS, exist_ok=True)
            with open(VALIDACIONES_DOCS, "w", encoding="utf-8") as f:
                json.dump([{"tipo": t, "numero": n} for t, n in unicos], f,
                          ensure_ascii=False, indent=2)
        except OSError as e:
            self.emitir("! No pude guardar la lista de documentos: %s" % e, "mal")

    # -- ejecucion
    def ocupada(self):
        return self.proc is not None and self.proc.poll() is None

    def ejecutar(self):
        if self.ocupada():
            return
        unicos = solo_unicos(self.docs)
        if not unicos:
            messagebox.showinfo("Falta la lista",
                                "Agrega al menos un documento a la lista.")
            return
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.tabla.delete(*self.tabla.get_children())
        self.servicios = list(SERVICIOS_FIJOS)
        self.resultados = {}
        self._columnas()
        self.b_ir.configure(state="disabled")
        self.lbl.configure(foreground="")
        self.estado.set("Ejecutando...")
        threading.Thread(target=self._hilo, args=(unicos,), daemon=True).start()

    def _hilo(self, unicos):
        self.guardar_docs_actuales(unicos)

        os.makedirs(LOGS, exist_ok=True)
        self.ruta_log = os.path.join(
            LOGS, "validaciones_%s.log" % time.strftime("%Y%m%d_%H%M%S"))
        cmd = comando_hijo("validaciones_api", "--hilos", "5",
                           *["%s:%s" % (t, n) for t, n in unicos])
        self.emitir("> " + " ".join(cmd[1:]), "panel")
        self.emitir("> log completo: %s" % self.ruta_log, "panel")
        entorno = dict(os.environ, PYTHONIOENCODING="utf-8")
        try:
            self.proc = subprocess.Popen(
                cmd, cwd=BASE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, bufsize=1, env=entorno)
        except OSError as e:
            self.emitir("! No pude lanzar la validacion: %s" % e, "mal")
            self.after(0, self._fin)
            return
        self.after(0, lambda: self.b_parar.configure(state="normal"))
        with open(self.ruta_log, "w", encoding="utf-8") as archivo:
            for cruda in self.proc.stdout:
                linea = _decodificar_stdout(cruda)
                archivo.write(linea)
                self._linea(linea)
        self.proc.wait()
        self.after(0, self._fin)

    def _linea(self, linea):
        """Del torrente del hijo solo sube al panel lo que se mira."""
        m = RE_RESULTADO.search(linea)
        if m:
            doc, servicio, estado = m.group(1), m.group(2).strip(), m.group(3).strip()
            if servicio.lower() in SERVICIOS_OCULTOS:
                return                    # sigue en el log completo del disco
            self.after(0, self._resultado, doc, servicio, estado)
            malo = estado.upper().startswith("FAIL")
            self.emitir("  %-12s %-26s %s" % (doc, servicio, estado),
                        "mal" if malo else "bien")
            return
        t = linea.strip()
        if t.startswith("Tests run:"):
            self.emitir(t, "panel")

    def _columnas(self):
        cols = ["documento"] + self.servicios
        self.tabla.configure(columns=cols)
        self.tabla.heading("documento", text="Documento")
        self.tabla.column("documento", width=130, anchor="w")
        for s in self.servicios:
            self.tabla.heading(s, text=s)
            self.tabla.column(s, width=190, anchor="w")

    def _resultado(self, doc, servicio, estado):
        if servicio not in self.servicios:
            self.servicios.append(servicio)
            self.servicios.sort(key=_orden_servicio)
            self._columnas()
        self.resultados.setdefault(doc, {})[servicio] = estado
        self._pintar()

    def _pintar(self):
        """Cada celda ya trae su propio punto verde/rojo desde _formato_estado;
        pintar tambien la fila completa (como antes) tapaba esos puntos con un
        solo color parejo, y una fila con un FAIL se veia toda roja aunque el
        resto de celdas estuviera en PASS."""
        self.tabla.delete(*self.tabla.get_children())
        for doc, servs in self.resultados.items():
            valores = [doc] + [_formato_estado(servs.get(s, "")) for s in self.servicios]
            self.tabla.insert("", "end", values=valores)

    def _fin(self):
        self.b_ir.configure(state="normal")
        self.b_parar.configure(state="disabled")
        self.proc = None
        docs = len(self.resultados)
        malos = sum(1 for s in self.resultados.values()
                    if "FAIL" in " ".join(s.values()).upper())
        if docs:
            self.estado.set("%d documento(s) con resultado, %d con algun FAIL."
                            % (docs, malos))
            self.lbl.configure(foreground="#c62828" if malos else "#1b7f2b")
        else:
            self.estado.set("No hubo lineas de resultado. Revisa el log completo.")
            self.lbl.configure(foreground="#c62828")
        self.ok = docs > 0 and malos == 0
        for cb in getattr(self, "al_terminar", []):
            cb()

    def detener(self):
        if self.ocupada():
            self.b_parar.configure(state="disabled")
            self.proc.terminate()

    def abrir_log(self):
        if not self.ruta_log or not os.path.exists(self.ruta_log):
            messagebox.showinfo("Sin log", "Todavia no hay log de una corrida.")
            return
        if hasattr(os, "startfile"):
            os.startfile(self.ruta_log)
        else:
            webbrowser.open("file:///" + self.ruta_log.replace("\\", "/"))


# --- usuarios de prueba ----------------------------------------------------
class Usuarios(ttk.Frame):
    """Libreta de usuarios de prueba: quien es, para que sirve y como quedo.

    Se guarda en usuarios_prueba.json apenas se toca algo, para que cerrar el
    panel de golpe no pierda nada. La ficha (etiquetas, reserva y el estado que
    trae Refrescar) la maneja usuarios.py, que tambien se usa desde la consola:
    si el archivo cambia por fuera, la pestana lo relee sola.
    """

    COLS = ("tipo", "usuario", "clave", "descripcion", "status", "falla")
    TITULOS = ("Tipo", "Usuario", "Contrasena", "Descripcion", "Status", "Falla")
    # la tabla muestra la libreta y, en medio, lo que trajo el ultimo refresco
    TABLA = ("tipo", "usuario", "clave", "descripcion", "status", "afiliacion",
             "categoria", "genero", "validaciones", "preaprobado", "novedad", "caso",
             "ciam", "refrescado", "falla")
    TABLA_TITULOS = ("Tipo", "Usuario", "Contrasena", "Descripcion", "Status",
                     "Afiliacion", "Cat.", "Genero", "Validaciones", "Preap.", "Novedad",
                     "Caso", "CIAM", "Refrescado", "Falla")
    TABLA_ANCHOS = (45, 95, 90, 170, 85, 150, 40, 65, 150, 50, 140, 190, 95, 125, 170)
    ESTADOS = banco.ESTADOS
    # CC/CE es como los piden los scripts de Bizagi; los servicios usan
    # CO1C/CO1E, que es otra codificacion del mismo tipo de documento
    TIPOS = ["CC", "CE"]
    TODOS = "(todos)"
    # filtro -> (titulo, opciones que se ven, lo que entiende banco.coincide)
    # de a tres por fila, en este orden; todos se combinan con Y
    FILTROS = (
        ("afiliacion", "Afiliacion", ["Dependiente", "Independiente", "Pensionado",
                                      "Facultativo"]),
        ("genero", "Genero", ["Mujer", "Hombre"]),
        ("categoria", "Categoria", ["A", "B", "C"]),
        ("novedad", "Novedad", ["Originacion", "Aumento", "Reactivacion", "Rechazo"]),
        ("validaciones", "Validaciones", ["Pasa SAP, SIIF, ASCARD", "Falla alguna"]),
        ("preaprobado", "Preaprobado", ["Si", "No"]),
        ("caso", "Caso", ["Sin caso", "Con caso"]),
        ("ciam", "CIAM", ["Existe", "No existe", "Login OK", "Sin verificar"]),
        ("status", "Status", banco.ESTADOS),
    )
    VALOR_FILTRO = {"Sin caso": "sin", "Con caso": "con", "Existe": "existe",
                    "No existe": "no-existe", "Login OK": "login-ok",
                    "Sin verificar": "sin-verificar"}
    # Refrescar al seleccionar: solo lo disparan el clic y estas teclas, no
    # cualquier cambio de seleccion (la tabla se vuelve a seleccionar sola al
    # repintarse tras cada refresco, y eso seria un bucle)
    NAVEGACION = {"Up", "Down", "Prior", "Next", "Home", "End"}
    AUTO_DEMORA = 500     # ms quieto en la fila: recorrer con flechas no consulta cada una
    AUTO_RECIENTE = 30    # s: una recien refrescada no se vuelve a pedir sola (F5 si)

    def __init__(self, padre):
        super().__init__(padre)
        self.datos = []
        self.editando = None      # indice que se esta editando, o None
        self.vars = {}
        self.filtros = {}
        self.refrescando = False
        self._entendido = []
        self._docs = []           # lo que entendio Documento(s)
        self._faltan = []         # de esos, los que no estan en la libreta
        self._mtime = None
        self._cola = queue.Queue()
        self._auto_id = None          # refresco al seleccionar, esperando AUTO_DEMORA
        self._auto_pendiente = False  # se selecciono otra mientras se refrescaba
        self._recien = {}             # (tipo, numero) -> cuando se refresco aqui
        self._en_refresco = set()     # las que estan refrescandose ahora
        self._fichas = {}             # (tipo, numero) -> ventana de su ficha abierta
        self._form_original = {}      # el formulario tal como se cargo
        self._construir()
        self.cargar()
        for tecla in ("<Control-f>", "<Control-F>"):
            self.winfo_toplevel().bind(tecla, self._ir_a_documentos, add="+")
        self.after(2000, self._vigilar)

    def _construir(self):
        form = ttk.Frame(self, padding=(12, 12, 12, 4))
        form.pack(fill="x")
        anchos = {"usuario": 18, "clave": 16, "descripcion": 34, "falla": 34}
        col = 0
        for clave, titulo in zip(self.COLS, self.TITULOS):
            ttk.Label(form, text=titulo).grid(row=0, column=col, sticky="w", padx=(0, 6))
            var = tk.StringVar()
            if clave == "tipo":
                var.set(self.TIPOS[0])
                w = ttk.Combobox(form, textvariable=var, values=self.TIPOS,
                                 width=5, state="readonly")
            elif clave == "status":
                w = ttk.Combobox(form, textvariable=var, values=self.ESTADOS, width=14)
            else:
                w = ttk.Entry(form, textvariable=var, width=anchos.get(clave, 18))
                w.bind("<Return>", lambda _e: self.guardar())
            w.grid(row=1, column=col, sticky="w", padx=(0, 14))
            self.vars[clave] = var
            col += 1
        ttk.Label(form, text="Etiquetas (separadas por coma)").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.vars["etiquetas"] = tk.StringVar()
        e = ttk.Entry(form, textvariable=self.vars["etiquetas"], width=60)
        e.grid(row=2, column=2, columnspan=3, sticky="w", pady=(8, 0))
        e.bind("<Return>", lambda _e: self.guardar())
        self.ver_claves = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="Mostrar contrasenas en la tabla",
                        variable=self.ver_claves,
                        command=self.refrescar).grid(row=3, column=0, columnspan=3,
                                                     sticky="w", pady=(8, 0))
        # apagado por defecto: publicar deja las claves en el historial de git
        # para siempre, y eso no se deshace borrando el archivo despues
        self.publicar_claves = tk.BooleanVar(value=False)
        ttk.Checkbutton(form, text="Publicar tambien las contrasenas",
                        variable=self.publicar_claves).grid(
                            row=3, column=3, columnspan=3, sticky="w", pady=(8, 0))

        botones = ttk.Frame(self, padding=(12, 6))
        botones.pack(fill="x")
        self.b_guardar = ttk.Button(botones, text="Agregar", command=self.guardar)
        self.b_guardar.pack(side="left")
        ttk.Button(botones, text="Limpiar campos",
                   command=self.limpiar).pack(side="left", padx=8)
        ttk.Button(botones, text="Copiar usuario",
                   command=lambda: self.copiar("usuario")).pack(side="left")
        ttk.Button(botones, text="Copiar contrasena",
                   command=lambda: self.copiar("clave")).pack(side="left", padx=8)
        ttk.Button(botones, text="Traer del repo",
                   command=self.traer).pack(side="left", padx=(16, 0))
        ttk.Button(botones, text="Publicar al repo",
                   command=self.publicar).pack(side="left", padx=8)
        ttk.Button(botones, text="Abrir carpeta de datos",
                   command=self.abrir_datos).pack(side="left")
        ttk.Button(botones, text="Importar archivo...",
                   command=self.importar_archivo).pack(side="left", padx=8)
        ttk.Button(botones, text="Eliminar", command=self.eliminar).pack(side="right")

        # Refrescar pregunta a los servicios (SAP, ASCARD, /request/check,
        # Gigya...) por cada cedula; tarda segundos por cedula, va en un hilo
        acciones = ttk.Frame(self, padding=(12, 2))
        acciones.pack(fill="x")
        self.b_ref_sel = ttk.Button(acciones, text="Refrescar seleccionados",
                                    command=lambda: self.refrescar_estado(False))
        self.b_ref_sel.pack(side="left")
        self.b_ref_vis = ttk.Button(acciones, text="Refrescar visibles",
                                    command=lambda: self.refrescar_estado(True))
        self.b_ref_vis.pack(side="left", padx=8)
        # apagado por defecto: cada clave errada cuenta para el bloqueo de la
        # cuenta en Gigya
        self.probar_login = tk.BooleanVar(value=False)
        ttk.Checkbutton(acciones, text="Probar login CIAM (usa la contrasena)",
                        variable=self.probar_login).pack(side="left", padx=(4, 16))
        self.auto_refrescar = tk.BooleanVar(value=True)
        ttk.Checkbutton(acciones, text="Refrescar al seleccionar",
                        variable=self.auto_refrescar).pack(side="left", padx=(0, 16))
        ttk.Button(acciones, text="Reservar...", command=self.reservar).pack(side="left")
        ttk.Button(acciones, text="Liberar", command=self.liberar).pack(side="left", padx=8)
        ttk.Button(acciones, text="Ver ficha", command=self.ver_ficha).pack(side="left")

        # Documento(s): la forma rapida de encontrar cedulas, una o varias
        # pegadas de un Excel o de un chat. Mientras se busca por documento los
        # filtros de abajo no aplican: un combo olvidado no esconde la cedula
        barra_d = ttk.Frame(self, padding=(12, 8, 12, 2))
        barra_d.pack(fill="x")
        ttk.Label(barra_d, text="Documento(s)").pack(side="left")
        self.documentos = tk.StringVar()
        self.e_documentos = ttk.Entry(barra_d, textvariable=self.documentos, width=48)
        self.e_documentos.pack(side="left", padx=(6, 8))
        self.documentos.trace_add("write", lambda *_a: self.refrescar())
        self.e_documentos.bind("<<Paste>>", self._pegar_documentos)
        self.e_documentos.bind("<Return>", lambda _e: self.seleccionar_encontrados())
        self.e_documentos.bind("<Escape>", lambda _e: self.documentos.set(""))
        self.b_revisar = ttk.Button(barra_d, text="Agregar y validar", state="disabled",
                                    command=self.revisar)
        self.b_revisar.pack(side="left")
        ttk.Label(barra_d, text="Ctrl+F  ·  varias: pegalas de Excel  ·  Enter las selecciona",
                  foreground="#6b6b6b").pack(side="left", padx=(10, 0))

        barra_f = ttk.Frame(self, padding=(12, 4))
        barra_f.pack(fill="x")
        ttk.Label(barra_f, text="Filtrar:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        # tres filtros por fila: los seis en una sola no caben en 960 px
        for n, (nombre, titulo, opciones) in enumerate(self.FILTROS):
            fila, col = divmod(n, 3)
            ttk.Label(barra_f, text=titulo).grid(row=fila, column=1 + col * 2, sticky="w",
                                                 pady=(0, 4))
            var = tk.StringVar(value=self.TODOS)
            cb = ttk.Combobox(barra_f, textvariable=var, values=[self.TODOS] + list(opciones),
                              width=14, state="readonly")
            cb.grid(row=fila, column=2 + col * 2, sticky="w", padx=(4, 12), pady=(0, 4))
            cb.bind("<<ComboboxSelected>>", lambda _e: self.refrescar())
            self.filtros[nombre] = var
        self.solo_libres = tk.BooleanVar(value=False)
        ttk.Checkbutton(barra_f, text="Solo libres", variable=self.solo_libres,
                        command=self.refrescar).grid(row=0, column=7, sticky="w", pady=(0, 4))
        # Buscar entiende un perfil en palabras ("mujer pensionada preaprobada
        # que pase validaciones"); lo que no reconoce lo busca como texto
        ttk.Label(barra_f, text="Buscar").grid(row=1, column=7, sticky="w", pady=(0, 4))
        self.buscar = tk.StringVar()
        e = ttk.Entry(barra_f, textvariable=self.buscar, width=22)
        e.grid(row=1, column=8, sticky="w", padx=(4, 10), pady=(0, 4))
        self.buscar.trace_add("write", lambda *_a: self.refrescar())
        ttk.Label(barra_f, text="Etiqueta").grid(row=2, column=7, sticky="w", pady=(0, 4))
        self.filtro_etiqueta = tk.StringVar(value=self.TODOS)
        self.cb_etiqueta = ttk.Combobox(barra_f, textvariable=self.filtro_etiqueta,
                                        values=[self.TODOS], width=20, state="readonly")
        self.cb_etiqueta.grid(row=2, column=8, sticky="w", padx=(4, 10), pady=(0, 4))
        self.cb_etiqueta.bind("<<ComboboxSelected>>", lambda _e: self.refrescar())
        ttk.Button(barra_f, text="Quitar filtros",
                   command=self.quitar_filtros).grid(row=0, column=8, sticky="w",
                                                     padx=(4, 0), pady=(0, 4))

        marco = ttk.Frame(self, padding=(12, 4, 12, 6))
        marco.pack(fill="both", expand=True)
        self.tabla = ttk.Treeview(marco, columns=self.TABLA, show="headings",
                                  selectmode="extended")
        for c, a, t in zip(self.TABLA, self.TABLA_ANCHOS, self.TABLA_TITULOS):
            self.tabla.heading(c, text=t)
            self.tabla.column(c, width=a, stretch=False,
                              anchor="center" if c in ("tipo", "status", "categoria",
                                                       "genero") else "w")
        barra = ttk.Scrollbar(marco, orient="vertical", command=self.tabla.yview)
        barra_x = ttk.Scrollbar(marco, orient="horizontal", command=self.tabla.xview)
        self.tabla.configure(yscrollcommand=barra.set, xscrollcommand=barra_x.set)
        self.tabla.grid(row=0, column=0, sticky="nsew")
        barra.grid(row=0, column=1, sticky="ns")
        barra_x.grid(row=1, column=0, sticky="ew")
        marco.rowconfigure(0, weight=1)
        marco.columnconfigure(0, weight=1)
        self.tabla.tag_configure("mal", foreground="#c62828")
        self.tabla.tag_configure("libre", foreground="#1b7f2b")
        self.tabla.tag_configure("uso", foreground="#1f5fbf")
        self.tabla.bind("<<TreeviewSelect>>", lambda _e: self.cargar_en_form())
        self.tabla.bind("<Double-1>", lambda _e: self.ver_ficha())
        self.tabla.bind("<Return>", lambda _e: self.ver_ficha())
        # refrescar la fila seleccionada sin ir a los botones: F5 o clic derecho
        self.winfo_toplevel().bind("<F5>", self._f5, add="+")
        self.menu_fila = tk.Menu(self, tearoff=False)
        self.menu_fila.add_command(label="Refrescar este usuario  (F5)",
                                   command=lambda: self.refrescar_estado(False))
        self.menu_fila.add_command(label="Ver ficha", command=self.ver_ficha)
        self.menu_fila.add_separator()
        self.menu_fila.add_command(label="Copiar usuario", command=lambda: self.copiar("usuario"))
        self.menu_fila.add_command(label="Copiar contrasena",
                                   command=lambda: self.copiar("clave"))
        self.tabla.bind("<Button-3>", self._menu_fila)
        self.tabla.bind("<ButtonRelease-1>", self._clic_fila, add="+")
        self.tabla.bind("<KeyRelease>", self._tecla_fila, add="+")

        self.estado = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.estado,
                  padding=(14, 0, 14, 8)).pack(fill="x")

    # -- persistencia
    @staticmethod
    def _clave(u):
        return banco.clave(u)

    @staticmethod
    def _mtime_archivo():
        try:
            return os.path.getmtime(USUARIOS)
        except OSError:
            return None

    def cargar(self):
        os.makedirs(DIR_DATOS, exist_ok=True)
        # el archivo vivia dentro del repo; si sigue ahi, se trae una sola vez
        if not os.path.exists(USUARIOS) and os.path.exists(USUARIOS_LEGADO):
            shutil.copy2(USUARIOS_LEGADO, USUARIOS)
        # primer arranque tras clonar: el catalogo del repo siembra el local
        semilla = catalogo_compartido()
        if not os.path.exists(USUARIOS) and os.path.exists(semilla):
            shutil.copy2(semilla, USUARIOS)
        self.datos = banco.leer(USUARIOS)
        self._mtime = self._mtime_archivo()
        self.refrescar()

    def volcar(self, respaldo=True):
        try:
            banco.guardar(self.datos, USUARIOS, respaldo=respaldo)
        except OSError as e:
            messagebox.showerror("No se pudo guardar", str(e))
        self._mtime = self._mtime_archivo()

    def _vigilar(self):
        """Relee el archivo si otro lo cambio (usuarios.py desde la consola).
        Durante un refresco no: los resultados se aplican sobre self.datos y
        se guardan al llegar, el archivo se pondria al dia ahi mismo."""
        try:
            m = self._mtime_archivo()
            if m != self._mtime and not self.refrescando:
                editando = (self._clave(self.datos[self.editando])
                            if self.editando is not None and self.editando < len(self.datos)
                            else None)
                seleccionadas = {self._clave(self.datos[int(i)]) for i in self.tabla.selection()
                                 if int(i) < len(self.datos)}
                self.datos = banco.leer(USUARIOS)
                self._mtime = m
                if editando is not None:
                    self.editando = next((i for i, u in enumerate(self.datos)
                                          if self._clave(u) == editando), None)
                    if self.editando is None:
                        self.limpiar()
                self.refrescar()
                # la seleccion se rehace por cedula: si el archivo cambio de
                # orden, por posicion quedaria marcada (y se refrescaria) otra
                filas = [i for i in self.tabla.get_children()
                         if self._clave(self.datos[int(i)]) in seleccionadas]
                if filas:
                    self.tabla.selection_set(filas)
                else:
                    self.tabla.selection_remove(*self.tabla.selection())
                self.estado.set("Releido: el archivo cambio por fuera (%s)."
                                % time.strftime("%H:%M:%S"))
        finally:
            self.after(2000, self._vigilar)

    # -- tabla
    def filtros_actuales(self):
        """Los combos y, debajo, lo que entendio Buscar: si los dos dicen algo
        del mismo campo, manda el combo."""
        f = {}
        for nombre, var in self.filtros.items():
            valor = var.get()
            if not valor or valor == self.TODOS:
                continue
            if nombre == "validaciones":
                if valor == "Falla alguna":
                    f["no_pasa"] = True
                else:
                    f["pasa_todas"] = banco.VALIDACIONES
            elif nombre == "preaprobado":
                f["preaprobado"] = valor == "Si"
            else:
                f[nombre] = self.VALOR_FILTRO.get(valor, valor)
        if self.solo_libres.get():
            f["libres"] = True
        if self.filtro_etiqueta.get() not in ("", self.TODOS):
            f["etiqueta"] = self.filtro_etiqueta.get()
        self._entendido = []
        texto = self.buscar.get().strip()
        if texto:
            perfil, self._entendido, _cantidad = banco.interpretar(texto)
            for k, v in perfil.items():
                f.setdefault(k, v)
        return f

    def quitar_filtros(self):
        for var in self.filtros.values():
            var.set(self.TODOS)
        self.solo_libres.set(False)
        self.filtro_etiqueta.set(self.TODOS)
        self.buscar.set("")
        self.documentos.set("")
        self.refrescar()

    def _hay_filtros(self):
        return bool(any(v.get() not in ("", self.TODOS) for v in self.filtros.values())
                    or self.solo_libres.get() or self.buscar.get().strip()
                    or self.filtro_etiqueta.get() not in ("", self.TODOS))

    def refrescar(self):
        seleccion = set(self.tabla.selection())
        # repintar no mueve la vista ni la fila activa del teclado: sin esto,
        # tras cada refresco la tabla saltaba arriba y la flecha seguia desde
        # la primera fila
        foco = self.tabla.focus()
        arriba, izquierda = self.tabla.yview()[0], self.tabla.xview()[0]
        filas_antes = self.tabla.get_children()
        self.tabla.delete(*filas_antes)
        por_documento = bool(self.documentos.get().strip())
        sobra = []
        if por_documento:
            self._docs, sobra = banco.documentos_en_texto(self.documentos.get())
            # con un solo documento se busca mientras se escribe
            filas, self._faltan = banco.buscar_documentos(self.datos, self._docs,
                                                          parcial=len(self._docs) == 1)
        else:
            self._docs, self._faltan = [], []
            filas = banco.filtrar(self.datos, **self.filtros_actuales())
        self.b_revisar.configure(state="normal" if self._docs and not self.refrescando
                                 else "disabled")
        for i, u in filas:
            clave = u.get("clave", "")
            if clave and not self.ver_claves.get():
                clave = "*" * len(clave)
            est = (u.get("status") or "").lower()
            if u.get("falla") or est in ("bloqueado", "quemado", "con falla"):
                tag = "mal"
            elif u.get("uso") or est == "en uso":
                tag = "uso"
            elif est == "disponible":
                tag = "libre"
            else:
                tag = ""
            r = banco.resumen(u)
            self.tabla.insert("", "end", iid=str(i), tags=(tag,),
                              values=(u.get("tipo", ""), u.get("usuario", ""), clave,
                                      u.get("descripcion", ""), u.get("status", ""),
                                      r["afiliacion"], r["categoria"], r["genero"],
                                      r["validaciones"], r["preaprobado"], r["novedad"],
                                      r["caso"], r["ciam"], r["refrescado"],
                                      u.get("falla", "")))
        quedan = [i for i in seleccion if self.tabla.exists(i)]
        if quedan:
            self.tabla.selection_set(quedan)
        if foco and self.tabla.exists(foco):
            self.tabla.focus(foco)
        # mismas filas (un refresco): la vista queda donde estaba. Otro filtro:
        # arranca arriba, como siempre
        if self.tabla.get_children() == filas_antes:
            self.tabla.yview_moveto(arriba)
        self.tabla.xview_moveto(izquierda)
        etiquetas = sorted({t for u in self.datos for t in u.get("etiquetas") or []})
        self.cb_etiqueta.configure(values=[self.TODOS] + etiquetas)
        repetidos = len(self.datos) - len(banco.por_clave(self.datos))
        if por_documento:
            self.estado.set(self._texto_documentos(filas, sobra))
            return
        if self._entendido:
            self.estado.set("%d de %d usuario(s)  |  Buscar entendio: %s"
                            % (len(filas), len(self.datos), " | ".join(self._entendido)))
            return
        self.estado.set("%d de %d usuario(s)%s  |  %s  |  copias en backups/"
                        % (len(filas), len(self.datos),
                           "  (%d cedula(s) repetida(s))" % repetidos if repetidos else "",
                           USUARIOS))

    def _texto_documentos(self, filas, sobra):
        """La barra de abajo cuando se busca por documento."""
        docs, faltan = self._docs, self._faltan

        def lista(ks):
            return ", ".join("%s:%s" % k for k in ks[:6]) + (
                " y %d mas" % (len(ks) - 6) if len(ks) > 6 else "")

        if not docs:
            partes = ["No veo un documento en lo que escribiste"]
        elif len(docs) == 1:
            tipo, numero = docs[0]
            exactos = sum(1 for _i, u in filas if banco.clave(u)[1] == numero)
            if not faltan:
                partes = ["%s esta en la libreta%s" % ("%s:%s" % docs[0] if tipo else numero,
                                                       " (%d veces)" % exactos if exactos > 1 else "")]
                if len(filas) > exactos:
                    partes.append("%d mas lo contienen" % (len(filas) - exactos))
                partes.append("Enter la selecciona, otro Enter abre la ficha")
            elif filas:
                partes = ["%d documento(s) contienen %s" % (len(filas), numero)]
            else:
                partes = ["%s no esta en la libreta: Agregar y validar la suma y la consulta"
                          % lista(faltan)]
        else:
            partes = ["%d de %d documento(s) en la libreta" % (len(docs) - len(faltan), len(docs))]
            if faltan:
                partes.append("faltan %s (Agregar y validar las suma)" % lista(faltan))
        if sobra:
            partes.append("no son documento: %s" % ", ".join(sobra[:4]))
        if self._hay_filtros():
            partes.append("los filtros no aplican al buscar por documento")
        return "  |  ".join(partes)

    def _clic_fila(self, e):
        if self.tabla.identify_region(e.x, e.y) in ("cell", "tree"):
            self._programar_auto()

    def _tecla_fila(self, e):
        if e.keysym in self.NAVEGACION:
            self._programar_auto()

    def _programar_auto(self):
        """Refrescar al seleccionar, cuando la seleccion lleva AUTO_DEMORA quieta."""
        if self._auto_id:
            self.after_cancel(self._auto_id)
        self._auto_id = self.after(self.AUTO_DEMORA, self._auto_refrescar)

    def _auto_refrescar(self, avisar=True):
        """Refresca la fila seleccionada si es una sola. Sin login (no abre
        dialogos ni toca Gigya). Si hay un refresco andando, la deja para
        cuando termine; si se refresco hace menos de AUTO_RECIENTE, no."""
        self._auto_id = None
        sel = self.tabla.selection()
        if not self.auto_refrescar.get() or len(sel) != 1 or int(sel[0]) >= len(self.datos):
            return
        if self.refrescando:
            self._auto_pendiente = True
            return
        k = self._clave(self.datos[int(sel[0])])
        hace = time.time() - self._recien.get(k, 0)
        if hace < self.AUTO_RECIENTE:
            if avisar:
                self.estado.set("%s:%s esta al dia: se refresco hace %d s (F5 la refresca "
                                "otra vez)." % (k[0], k[1], hace))
            return
        self.refrescar_estado(False, login=False)

    def _f5(self, _e=None):
        """F5, solo con esta pestana a la vista: refresca lo seleccionado."""
        if not self.winfo_ismapped():
            return None
        if self.tabla.selection():
            self.refrescar_estado(False)
        return "break"

    def _menu_fila(self, e):
        """Clic derecho: la fila bajo el raton queda seleccionada (si no lo
        estaba ya) y sale su menu."""
        fila = self.tabla.identify_row(e.y)
        if not fila:
            return
        if fila not in self.tabla.selection():
            self.tabla.selection_set(fila)
        self.tabla.focus(fila)
        cuantos = len(self.tabla.selection())
        self.menu_fila.entryconfigure(
            0, label=("Refrescar los %d seleccionados  (F5)" % cuantos if cuantos > 1
                      else "Refrescar este usuario  (F5)"),
            state="disabled" if self.refrescando else "normal")
        try:
            self.menu_fila.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu_fila.grab_release()

    def _sel(self):
        sel = self.tabla.selection()
        return int(sel[0]) if sel else None

    def _seleccion(self):
        return [int(i) for i in self.tabla.selection()]

    def cargar_en_form(self):
        i = self._sel()
        if i is None:
            return
        # la misma fila que se vuelve a seleccionar sola (la tabla se repinta al
        # terminar cada refresco) no pisa lo que se este escribiendo
        if i == self.editando and self._form_modificado():
            return
        self.editando = i
        for c in self.COLS:
            self.vars[c].set(self.datos[i].get(c, ""))
        self.vars["etiquetas"].set(", ".join(self.datos[i].get("etiquetas") or []))
        self._form_original = {c: v.get() for c, v in self.vars.items()}
        self.b_guardar.configure(text="Actualizar")

    def _form_modificado(self):
        return any(self.vars[c].get() != valor for c, valor in self._form_original.items())

    def limpiar(self):
        self.editando = None
        self._form_original = {}
        for v in self.vars.values():
            v.set("")
        self.vars["tipo"].set(self.TIPOS[0])
        self.tabla.selection_remove(*self.tabla.selection())
        self.b_guardar.configure(text="Agregar")

    # -- acciones
    def guardar(self):
        # al editar se parte del registro completo: la ficha (estado, uso) no
        # esta en el formulario y no se puede perder por actualizar la clave
        fila = dict(self.datos[self.editando]) if self.editando is not None else {}
        fila.update({c: self.vars[c].get().strip() for c in self.COLS})
        if not fila["usuario"]:
            messagebox.showinfo("Falta un dato", "Escribe el usuario.")
            return
        fila.pop("etiquetas", None)
        banco.etiquetar(fila, self.vars["etiquetas"].get().split(","))
        if (fila.get("status") or "").lower() != "en uso":
            fila.pop("uso", None)
        if self.editando is None:
            self.datos.append(fila)
        else:
            self.datos[self.editando] = fila
        self.volcar()
        self.limpiar()
        self.refrescar()

    def eliminar(self):
        i = self._sel()
        if i is None:
            messagebox.showinfo("Sin seleccion", "Escoge un usuario de la lista.")
            return
        if not messagebox.askyesno("Eliminar",
                                   "Quitar a %s de la lista?" % self.datos[i].get("usuario", "")):
            return
        self.datos.pop(i)
        self.volcar()
        self.limpiar()
        self.refrescar()

    def reservar(self):
        indices = self._seleccion()
        if not indices:
            messagebox.showinfo("Sin seleccion", "Escoge uno o varios usuarios.")
            return
        ocupados = [self.datos[i].get("usuario", "") for i in indices
                    if not banco.libre(self.datos[i])]
        if ocupados and not messagebox.askyesno(
                "Reservar", "No estan libres: %s.\n\nReservarlos igual?" % ", ".join(ocupados)):
            return
        hu = simpledialog.askstring("Reservar", "Para que HU (o tarea)?", parent=self)
        if not hu:
            return
        for i in indices:
            banco.reservar(self.datos[i], hu)
        self.volcar()
        self.limpiar()
        self.refrescar()

    def liberar(self):
        indices = self._seleccion()
        if not indices:
            messagebox.showinfo("Sin seleccion", "Escoge uno o varios usuarios.")
            return
        for i in indices:
            banco.liberar(self.datos[i])
        self.volcar()
        self.limpiar()
        self.refrescar()

    def importar_archivo(self):
        """Suma las cedulas de un CSV/TXT/JSON con la etiqueta lote-<archivo>,
        deja la tabla filtrada por ella y ofrece validarlas."""
        ruta = filedialog.askopenfilename(
            parent=self, title="Cedulas a importar",
            filetypes=[("CSV o texto", "*.csv *.txt"),
                       ("JSON", "*.json"), ("Todos", "*.*")])
        if not ruta:
            return
        try:
            entrantes, malas = banco.leer_archivo(ruta)
            etiqueta = banco.etiqueta_de_archivo(ruta)
            for ent in entrantes:
                ent["etiquetas"] = list(ent.get("etiquetas") or []) + [etiqueta]
            hay = banco.por_clave(self.datos)
            ya = sum(1 for ent in entrantes
                     if banco.parse_doc("%s:%s" % (ent.get("tipo") or "CC",
                                                   ent.get("usuario") or ent.get("numero")))
                     in hay)
            agregados, _actualizados = banco.importar(self.datos, entrantes)
        except (OSError, ValueError) as e:
            messagebox.showerror("No se pudo importar", str(e))
            return
        if not entrantes:
            messagebox.showinfo("Sin cedulas", "No encontre cedulas en %s.\n\nSirve una "
                                "columna numero/documento/cedula (y tipo, opcional) o una "
                                "cedula por linea." % os.path.basename(ruta))
            return
        self.volcar()
        self.quitar_filtros()
        self.filtro_etiqueta.set(etiqueta)
        self.refrescar()
        aviso = ("%d cedula(s) en %s: %d nuevas, %d ya estaban.\nQuedaron con la etiqueta "
                 "%s y la tabla filtrada por ella." % (len(entrantes), os.path.basename(ruta),
                                                      agregados, ya, etiqueta))
        if malas:
            aviso += "\n\n%d fila(s) no traian una cedula valida." % len(malas)
        if messagebox.askyesno("Importar", aviso + "\n\nValidarlas ahora (Refrescar visibles)?"):
            self.refrescar_estado(True)

    # -- busqueda por documento
    def _ir_a_documentos(self, _e=None):
        """Ctrl+F, solo con esta pestana a la vista."""
        if not self.winfo_ismapped():
            return None
        self.e_documentos.focus_set()
        self.e_documentos.select_range(0, "end")
        self.e_documentos.icursor("end")
        return "break"

    def _pegar_documentos(self, _e):
        """Una columna de Excel llega con saltos de linea y tabs, que el Entry
        muestra como basura: se pega separada por comas."""
        try:
            texto = self.clipboard_get()
        except tk.TclError:
            return "break"
        texto = ", ".join(linea.replace("\t", " ").strip()
                          for linea in texto.splitlines() if linea.strip())
        e = self.e_documentos
        if e.selection_present():
            e.delete("sel.first", "sel.last")
        # pegar al lado de otro numero no los puede fundir en uno solo
        if re.search(r"\d\s*$", e.get()[:e.index("insert")]):
            texto = ", " + texto
        e.insert("insert", texto)
        return "break"

    def seleccionar_encontrados(self):
        """Enter en Documento(s): selecciona lo encontrado y pasa a la tabla,
        donde otro Enter abre la ficha."""
        hijos = self.tabla.get_children()
        if not self._docs or not hijos:
            return
        self.tabla.selection_set(hijos)
        self.tabla.focus(hijos[0])
        self.tabla.see(hijos[0])
        self.tabla.focus_set()
        self.estado.set("%d seleccionada(s). Enter abre la ficha; Refrescar seleccionados, "
                        "Reservar... y Liberar van sobre ellas." % len(hijos))
        # elegir la cedula escribiendola tambien es seleccionarla (si es una sola)
        self._programar_auto()

    def revisar(self):
        """Lo de 'usuarios.py revisar' sobre lo que hay en Documento(s): suma
        al banco los que falten, con la etiqueta consulta-<fecha>, y valida los
        pedidos (no lo demas que traiga la busqueda parcial)."""
        if not self._docs or self.refrescando:
            return
        if self._faltan:
            etiqueta = "consulta-%s" % time.strftime("%Y-%m-%d")
            banco.importar(self.datos, [{"tipo": t, "usuario": n, "etiquetas": [etiqueta]}
                                        for t, n in self._faltan])
            self.volcar()
            self.refrescar()
        pedidos, _faltan = banco.buscar_documentos(self.datos, self._docs)
        self.tabla.selection_set([str(i) for i, _u in pedidos])
        self.refrescar_estado(False)

    def ver_ficha(self):
        i = self._sel()
        if i is None:
            messagebox.showinfo("Sin seleccion", "Escoge un usuario de la lista.")
            return
        k = self._clave(self.datos[i])
        v = self._fichas.get(k)
        if v is None or not v.winfo_exists():
            v = tk.Toplevel(self)
            v.geometry("640x560")
            v.texto = tk.Text(v, wrap="word", font=("Consolas", 10))
            v.texto.pack(fill="both", expand=True)
            self._fichas[k] = v
        self._pintar_ficha(k)
        v.lift()

    def _pintar_ficha(self, k):
        """La ficha abierta de esa cedula, con lo ultimo. Abierta mientras se
        refresca (doble clic justo al seleccionar), se pone al dia sola."""
        v = self._fichas.get(k)
        if v is None or not v.winfo_exists():
            self._fichas.pop(k, None)
            return
        u = next((u for u in self.datos if self._clave(u) == k), None)
        if u is None:
            return
        v.title("Ficha %s:%s%s" % (k[0], k[1], "  (refrescando...)" if k in self._en_refresco
                                    else ""))
        v.texto.configure(state="normal")
        v.texto.delete("1.0", "end")
        v.texto.insert("1.0", json.dumps(banco._publico(u), ensure_ascii=False, indent=2))
        v.texto.configure(state="disabled")

    def refrescar_estado(self, visibles, login=None):
        """login None: lo que diga 'Probar login CIAM'. El refresco al
        seleccionar pasa False: nunca abre el dialogo ni prueba claves."""
        if self.refrescando:
            return
        # un pedido explicito (F5, boton) cubre el de seleccionar que esperaba
        if self._auto_id:
            self.after_cancel(self._auto_id)
            self._auto_id = None
        indices = ([int(i) for i in self.tabla.get_children()] if visibles
                   else self._seleccion())
        if not indices:
            messagebox.showinfo("Sin seleccion", "Escoge uno o varios usuarios, o usa "
                                "Refrescar visibles.")
            return
        # copias: el hilo no toca los dicts que la UI esta mostrando
        registros = [dict(self.datos[i]) for i in indices]
        malos = sorted({"%s:%s" % self._clave(u) for u in registros if not banco.refrescable(u)})
        registros = [u for u in registros if banco.refrescable(u)]
        if not registros:
            self.estado.set("%s no se puede refrescar: los servicios solo entienden CC o CE "
                            "con numero." % ", ".join(malos[:4]))
            return
        total = len({self._clave(u) for u in registros})
        login = self.probar_login.get() if login is None else login
        if login and not messagebox.askyesno(
                "Probar login CIAM",
                "Se va a probar la contrasena de %d usuario(s) en Gigya (dev).\n\n"
                "Una clave errada cuenta para el bloqueo de la cuenta; una clave que "
                "ya dio errada no se vuelve a probar hasta que la cambies.\n\nSeguir?"
                % total):
            return
        self.refrescando = True
        self._hechos, self._total = 0, total
        self._llegados = {}
        self._error_refresco = None
        self._guardados_refresco = 0
        for b in (self.b_ref_sel, self.b_ref_vis, self.b_revisar):
            b.configure(state="disabled")
        self._una = "%s:%s" % self._clave(registros[0]) if total == 1 else None
        self._en_refresco = {self._clave(u) for u in registros}
        for k in self._en_refresco & set(self._fichas):
            self._pintar_ficha(k)
        self.estado.set(self._texto_refrescando())
        # cola nueva por refresco: lo que quede de uno anterior no se mezcla
        self._cola = queue.Queue()
        self._hilo_refresco = threading.Thread(target=self._trabajar_refresco,
                                               args=(registros, login, self._cola),
                                               daemon=True)
        self._hilo_refresco.start()
        self.after(300, self._drenar_refresco)

    def _texto_refrescando(self):
        texto = ("Refrescando %s..." % self._una if self._una
                 else "Refrescando %d/%d..." % (self._hechos, self._total))
        if self._auto_pendiente:
            texto += " Al terminar sigue la fila seleccionada."
        return texto

    @staticmethod
    def _trabajar_refresco(registros, login, cola):
        try:
            banco.refrescar(registros, login=login,
                            al_terminar_uno=lambda k, est: cola.put(("uno", k, est)))
            cola.put(("fin", None, None))
        except Exception as e:      # token.txt incompleto, sin red...
            cola.put(("error", None, str(e)))

    def _drenar_refresco(self):
        """Aplica lo que fue llegando. Nada de aqui puede dejar el panel en
        'Refrescando...' con los botones apagados: un error al aplicar, guardar
        o pintar queda en el mensaje y se sigue hasta que el hilo termine."""
        fin = False
        llegaron = []
        try:
            while True:
                try:
                    tipo, k, est = self._cola.get_nowait()
                except queue.Empty:
                    break
                if tipo == "uno":
                    try:
                        banco.aplicar(self.datos, k, est)
                    except Exception as e:      # esa cedula queda como estaba
                        self._error_refresco = ("error del panel al aplicar %s:%s: %s: %s"
                                                % (k[0], k[1], type(e).__name__, e))
                        continue
                    self._llegados[k] = est
                    self._hechos += 1
                    llegaron.append(k)
                    # con errores no cuenta como al dia: otro clic la reintenta
                    if not est.get("errores"):
                        self._recien[k] = time.time()
                else:
                    fin = True
                    if tipo == "error":
                        self._error_refresco = est
            if llegaron:
                # una copia al empezar el refresco, no una por cada tanda que llega
                self.volcar(respaldo=not self._guardados_refresco)
                self._guardados_refresco += 1
                self.refrescar()
                for k in llegaron:
                    self._en_refresco.discard(k)
                    self._pintar_ficha(k)
        except Exception as e:
            self._error_refresco = "error del panel al aplicar: %s: %s" % (type(e).__name__, e)
        # el hilo ya no esta y no dejo nada: no hay a quien esperar
        if not fin and not self._hilo_refresco.is_alive() and self._cola.empty():
            fin = True
        if not fin:
            self.estado.set(self._texto_refrescando())
            self.after(300, self._drenar_refresco)
            return
        # primero se sueltan los botones, despues el mensaje (que puede ser modal)
        self.refrescando = False
        for b in (self.b_ref_sel, self.b_ref_vis):
            b.configure(state="normal")
        self.b_revisar.configure(state="normal" if self._docs else "disabled")
        sin_llegar, self._en_refresco = self._en_refresco, set()
        try:
            for k in sin_llegar & set(self._fichas):
                self._pintar_ficha(k)
            self._terminar_refresco()
        except Exception as e:
            self.estado.set("Refresco listo (%d cedula(s)), sin resumen: %s: %s"
                            % (self._hechos, type(e).__name__, e))
        # la que se selecciono mientras se refrescaba otra
        if self._auto_pendiente:
            self._auto_pendiente = False
            self._auto_id = self.after(self.AUTO_DEMORA,
                                       lambda: self._auto_refrescar(avisar=False))

    def _terminar_refresco(self):
        if self._error_refresco and not self._hechos:
            self.estado.set("No se pudo refrescar: %s" % self._error_refresco[:200])
            messagebox.showerror("No se pudo refrescar", self._error_refresco)
            return
        extra = "  |  %s" % self._error_refresco[:200] if self._error_refresco else ""
        if self._total == 1 and self._llegados:
            # una cedula: como quedo, en la misma linea que da usuarios.py revisar
            k, est = next(iter(self._llegados.items()))
            u = next((u for u in self.datos if self._clave(u) == k), None)
            resumen = banco.ficha(u).splitlines()[-1].strip(" =>") if u else ""
            errores = sorted(est.get("errores") or {})
            if errores:
                self.estado.set("%s:%s refrescada, menos %s, que no respondio y conserva el "
                                "dato anterior (doble clic: el error)  |  %s%s"
                                % (k[0], k[1], ", ".join(errores), resumen, extra))
            else:
                self.estado.set("%s:%s refrescada: %s%s" % (k[0], k[1], resumen, extra))
            return
        # la parte que fallo conserva lo de antes: que se vea cual fue
        por = {}
        for est in self._llegados.values():
            for servicio in est.get("errores") or {}:
                por[servicio] = por.get(servicio, 0) + 1
        con_errores = sum(1 for est in self._llegados.values() if est.get("errores"))
        detalle = ", ".join("%s %d" % par for par in sorted(por.items(), key=lambda par: -par[1]))
        self.estado.set("Refresco listo: %d cedula(s)%s. Doble clic en una fila para ver "
                        "la ficha y sus errores.%s" % (
                            self._hechos, ", %d con errores (%s)" % (con_errores, detalle)
                            if con_errores else "", extra))

    def traer(self):
        """Agrega los del catalogo del repo que no tengas y suma sus etiquetas
        a los que ya tienes."""
        compartidos = _json_o_nada(catalogo_compartido())
        if not isinstance(compartidos, list):
            messagebox.showinfo("Sin catalogo",
                                "No hay %s en el repo."
                                % os.path.basename(USUARIOS_COMPARTIDOS))
            return
        tengo = banco.por_clave(self.datos)
        nuevos = [u for u in compartidos if self._clave(u) not in tengo]
        etiquetados = 0
        for c in compartidos:
            for u in tengo.get(self._clave(c), []):
                etiquetados += banco.etiquetar(u, c.get("etiquetas") or [])
        if not nuevos and not etiquetados:
            self.estado.set("El catalogo del repo no trae nada nuevo.")
            return
        self.datos.extend(nuevos)
        self.volcar()
        self.refrescar()
        self.estado.set("%d usuario(s) traidos del repo, %d con etiquetas nuevas."
                        % (len(nuevos), etiquetados))

    def publicar(self):
        """Escribe el catalogo que se versiona: la libreta y las etiquetas. La
        clave va solo si lo pediste; el estado y la reserva nunca (son de cada
        quien y cambian solos)."""
        con_claves = self.publicar_claves.get()
        aviso = ("Se van a publicar %d usuario(s) en %s, que SI se versiona.\n\n"
                 % (len(self.datos), os.path.basename(USUARIOS_COMPARTIDOS)))
        aviso += ("Las contrasenas van incluidas y quedaran en el historial de "
                  "git de forma permanente, aunque despues borres el archivo."
                  if con_claves else
                  "Las contrasenas NO van: cada quien completa las suyas.")
        if not messagebox.askyesno("Publicar al repo", aviso + "\n\nSeguir?"):
            return
        salida = []
        for u in self.datos:
            fila = {c: u.get(c, "") for c in self.COLS}
            if not con_claves:
                fila["clave"] = ""
            if u.get("etiquetas"):
                fila["etiquetas"] = list(u["etiquetas"])
            salida.append(fila)
        try:
            with open(USUARIOS_COMPARTIDOS, "w", encoding="utf-8") as f:
                json.dump(salida, f, ensure_ascii=False, indent=2)
        except OSError as e:
            messagebox.showerror("No se pudo publicar", str(e))
            return
        self.estado.set("%d usuario(s) publicados%s. Falta commitear el archivo."
                        % (len(salida), " con contrasena" if con_claves else
                           " sin contrasenas"))

    def abrir_datos(self):
        os.makedirs(BACKUPS, exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(DIR_DATOS)      # Windows
        else:
            webbrowser.open("file:///" + DIR_DATOS.replace("\\", "/"))

    def copiar(self, campo):
        i = self._sel()
        valor = self.datos[i].get(campo, "") if i is not None else self.vars[campo].get()
        if not valor:
            return
        self.clipboard_clear()
        self.clipboard_append(valor)
        self.estado.set("Copiado al portapapeles.")


# --- ventana ---------------------------------------------------------------
class Panel:
    def __init__(self, raiz):
        self.raiz = raiz
        raiz.title("Panel QA - Colsubsidio")
        raiz.geometry("960x640")
        raiz.minsize(780, 480)

        self.tabs = ttk.Notebook(raiz)
        self.tabs.pack(fill="both", expand=True)

        self.herramientas = {}
        for spec in HERRAMIENTAS:
            # declarada pero sin script/repo: se omite
            if spec.get("comando"):
                if not os.path.exists(spec.get("cwd", BASE)):
                    continue
            elif not hay_hijo(spec["script"]):
                continue
            h = Herramienta(self.tabs, spec)
            self.tabs.add(h, text="  %s  " % spec["nombre"])
            self.herramientas[spec["id"]] = h

        # Pastilla de color para la pestana de Validaciones API: ttk.Notebook
        # no deja pintar una pestana distinta de las demas, pero si acepta una
        # imagen junto al texto, y un cuadrito de color no depende de que la
        # maquina tenga fuente de emoji a color.
        self._sw_verde = tk.PhotoImage(width=10, height=10)
        self._sw_verde.put("#1b7f2b", to=(0, 0, 10, 10))
        self._sw_rojo = tk.PhotoImage(width=10, height=10)
        self._sw_rojo.put("#c62828", to=(0, 0, 10, 10))

        self.validaciones = None
        if hay_hijo("validaciones_api"):
            self.validaciones = Validaciones(self.tabs)
            self.tabs.add(self.validaciones, text="  Validaciones API  ")
            self.validaciones.al_terminar = [self._marcar_pestana_validaciones]

        self.usuarios = Usuarios(self.tabs)
        self.tabs.add(self.usuarios, text="  Usuarios  ")

        self.corridas = None
        if "observador" in self.herramientas:
            self.corridas = Corridas(self.tabs, self)
            self.tabs.add(self.corridas, text="  Corridas  ")
            self.herramientas["observador"].al_terminar = [self.corridas.refrescar]

        raiz.protocol("WM_DELETE_WINDOW", self.cerrar)
        raiz.after(120, self.bombear)

    def _marcar_pestana_validaciones(self):
        """Se llama al terminar una corrida de Validaciones API: pinta la
        pastilla verde o roja junto al titulo de la pestana, sin abrirla."""
        sw = self._sw_verde if self.validaciones.ok else self._sw_rojo
        self.tabs.tab(self.validaciones, image=sw, compound="right")

    def bombear(self):
        """Vuelca a cada log lo que su hilo fue dejando en la cola. Los widgets
        de tkinter solo se tocan desde el hilo principal."""
        for h in self.herramientas.values():
            h.drenar()
        if self.validaciones:
            self.validaciones.drenar()
        self.raiz.after(120, self.bombear)

    def cerrar(self):
        vivas = [h for h in self.herramientas.values() if h.ocupada()]
        if self.validaciones and self.validaciones.ocupada():
            vivas.append(self.validaciones)
        if vivas:
            nombres = ", ".join(h.spec["nombre"] for h in vivas)
            if not messagebox.askyesno(
                    "Procesos en curso",
                    "Sigue corriendo: %s.\n\nSi cierras ahora se cortan "
                    "(una captura quedaria sin reporte).\n\nCerrar de todas "
                    "formas?" % nombres):
                return
            for h in vivas:
                h.proc.terminate()
        self.raiz.destroy()


def main():
    # Congelado, el .exe hace de dos cosas: la ventana, y el interprete de sus
    # propios scripts cuando el se relanza a si mismo (ver comando_hijo). Esto
    # va antes de tocar tkinter: el hijo no tiene ventana que abrir.
    if len(sys.argv) > 2 and sys.argv[1] == "--child":
        return _correr_hijo(sys.argv[2], sys.argv[3:])
    raiz = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    Panel(raiz)
    raiz.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())

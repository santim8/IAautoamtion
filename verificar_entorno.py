#!/usr/bin/env python3
"""Revisa que esta maquina tenga lo que piden el panel y los scripts, y dice
que falta y como resolverlo.

    python verificar_entorno.py

Solo mira: no instala ni cambia nada. Va por bloques, uno por pestana o
grupo de pestanas, para que se sepa que deja de andar si algo falta. Sale con
1 si falta algo del primer bloque (sin eso el panel no abre); lo demas solo
apaga su pestana.
"""
import getpass
import importlib
import importlib.metadata
import os
import re
import shutil
import sys

import rutas

OK, FALTA, INFO = "OK", "FALTA", "INFO"


def _requisitos():
    """Paquetes de requirements.txt: asi este chequeo no se desfasa de el."""
    nombres = []
    try:
        with open(rutas.recurso("requirements.txt"), encoding="utf-8") as f:
            for linea in f:
                linea = linea.split("#", 1)[0].strip()
                if linea:
                    nombres.append(re.split(r"[<>=!~\[ ]", linea, 1)[0])
    except OSError:
        pass
    return nombres


# --- chequeos ---------------------------------------------------------------
# Cada uno devuelve [(estado, que se vio, como resolverlo o None)].
def python():
    v = sys.version_info
    texto = "Python %d.%d.%d" % v[:3]
    if v < (3, 10):
        return [(FALTA, texto, "instala Python 3.10 o superior desde python.org")]
    return [(OK, texto, None)]


def tkinter():
    try:
        importlib.import_module("tkinter")
    except ImportError:
        return [(FALTA, "tkinter (la ventana del panel)",
                 "reinstala Python desde python.org con la opcion tcl/tk marcada")]
    return [(OK, "tkinter", None)]


def paquetes():
    filas = []
    for nombre in _requisitos():
        try:
            filas.append((OK, "%s %s" % (nombre, importlib.metadata.version(nombre)),
                          None))
        except importlib.metadata.PackageNotFoundError:
            filas.append((FALTA, nombre, "python -m pip install -r requirements.txt"))
    return filas


def archivos_repo():
    """Lo que el panel importa al abrir. usuarios.py estuvo fuera de git y un
    clon recien hecho no abria."""
    faltan = [f for f in ("panel_observador.py", "usuarios.py", "rutas.py",
                          "sonda_check.py", "esquemas.py", "observador_flujo.py",
                          os.path.join("observador", "cli.py"))
              if not os.path.exists(rutas.recurso(f))]
    if faltan:
        return [(FALTA, "archivos del repo: " + ", ".join(faltan),
                 "git pull (o pide la ultima version a quien te paso el repo)")]
    return [(OK, "archivos del repo", None)]


def chrome():
    from observador.navegador import buscar_chrome
    exe = buscar_chrome()
    if not exe:
        return [(FALTA, "Google Chrome", "instala Chrome; el observador se engancha a el")]
    return [(OK, "Chrome en " + exe, None)]


def curl():
    exe = shutil.which("curl")
    if not exe:
        return [(FALTA, "curl", "viene con Windows 10/11; revisa el PATH")]
    return [(OK, "curl", None)]


def token_txt():
    import validaciones_api
    ruta = validaciones_api.TOKEN_PATH
    if not os.path.exists(ruta):
        return [(FALTA, "token.txt", "copy token.example.txt token.txt y pide las "
                 "claves a quien ya tenga el panel andando")]
    # las del bloque 1 de token.example.txt: las que leen los scripts del panel
    claves = ["api_key_card_validations", "apigee_client_id", "apigee_client_secret",
              "sso_password", "ciam_token_api_key", "ciam_gigya_api_key"]
    valores = validaciones_api._cargar_token_txt()
    vacias = [c for c in claves if not valores.get(c)]
    if vacias:
        return [(FALTA, "token.txt sin: " + ", ".join(vacias),
                 "llenalas en token.txt (token.example.txt dice cual es cada una)")]
    return [(OK, "token.txt con las %d claves" % len(claves), None)]


def _en_registro(nombre):
    """La variable esta guardada para el usuario (setx) aunque esta consola,
    abierta antes, todavia no la vea."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return bool(winreg.QueryValueEx(k, nombre)[0])
    except (ImportError, OSError):
        return False


def bizagi():
    filas = []
    for nombre in ("BIZAGI_USER", "BIZAGI_PASSWORD"):
        if os.environ.get(nombre):
            filas.append((OK, nombre, None))
        elif _en_registro(nombre):
            filas.append((FALTA, nombre + " (guardada, pero esta consola no la ve)",
                          "abre una consola nueva, o cierra y vuelve a abrir el panel"))
        else:
            filas.append((FALTA, nombre, 'setx %s "..." y abre una consola nueva' % nombre))
    return filas


def chromium():
    if rutas.chromium_instalado():
        return [(OK, "Chromium de Playwright", None)]
    return [(FALTA, "Chromium de Playwright",
             "python -m playwright install chromium (el .exe lo baja solo)")]


def bruno():
    import usuarios
    filas = []
    exe = shutil.which("bru.cmd") or shutil.which("bru")
    if exe:
        filas.append((OK, "CLI de Bruno (bru)", None))
    elif not shutil.which("node"):
        filas.append((FALTA, "Node.js y el CLI de Bruno",
                      "instala Node.js LTS y luego: npm install -g @usebruno/cli"))
    else:
        filas.append((FALTA, "CLI de Bruno (bru)", "npm install -g @usebruno/cli"))
    lote = os.path.join(usuarios.BRUNO_DIR, usuarios.BRUNO_LOTE)
    if not os.path.exists(lote):
        filas.append((FALTA, usuarios.BRUNO_LOTE, "git pull"))
    if not usuarios.clave_registro():
        filas.append((FALTA, "regPassword en el environment registro-dev",
                      "ponla en bruno/validate-request/environments/registro-dev.bru"))
    correo = usuarios._var_registro("regCorreoBase") or ""
    if "@" not in correo:
        filas.append((FALTA, "regCorreoBase en el environment registro-dev",
                      "pon tu correo en bruno/validate-request/environments/registro-dev.bru"))
    elif correo.split("@")[0].lower() != getpass.getuser().lower():
        # el correo de verificacion de cada cuenta nueva va a esa bandeja
        filas.append((INFO, "las cuentas CIAM nuevas se verifican en " + correo,
                      "si no es tu correo, cambia regCorreoBase en registro-dev.bru"))
    else:
        filas.append((OK, "registro-dev con tu correo", None))
    return filas


def usuarios_propios():
    import usuarios
    if os.path.exists(usuarios.ARCHIVO):
        return [(OK, "tus usuarios en " + usuarios.ARCHIVO, None)]
    return [(INFO, "sin usuarios propios todavia",
             "la pestana Usuarios arranca con usuarios_compartidos.json, sin claves")]


def front_local():
    """Lo mismo que busca front_consumo_local.js."""
    carpeta = os.path.abspath(os.environ.get("QA_FRONT_DIR")
                              or os.path.join(os.path.expanduser("~"), "qa-front-consumo"))
    nxt = os.path.join(carpeta, "node_modules", "next", "dist", "bin", "next")
    if os.path.exists(nxt) and shutil.which("node"):
        return [(OK, "front en " + carpeta, None)]
    return [(INFO, "sin front local en " + carpeta,
             "solo hace falta para levantarlo en local: clona feat/consumer-loans, "
             "npm install y setx QA_FRONT_DIR con su carpeta")]


# (titulo, obligatorio, chequeos). Solo el primero impide abrir el panel.
BLOQUES = [
    ("Panel (sin esto no abre)", True, [python, tkinter, paquetes, archivos_repo]),
    ("Observador de flujos y Analitica", False, [chrome]),
    ("Validaciones API, Suite biometria, Usuarios > Refrescar y /request/check",
     False, [curl, token_txt]),
    ("Cancelar caso, Consultar caso y Consultar JSON (Bizagi)", False,
     [bizagi, chromium]),
    ("Usuarios", False, [usuarios_propios]),
    ("Usuarios > Crear CIAM", False, [bruno]),
    ("Front de Consumo en local (opcional)", False, [front_local]),
]


def main():
    falta_base, apagados = False, []
    for titulo, obligatorio, chequeos in BLOQUES:
        print("\n" + titulo)
        filas = []
        for chequeo in chequeos:
            try:
                filas += chequeo()
            except Exception as e:     # un chequeo roto no tapa los demas
                filas.append((FALTA, "%s: %s: %s" % (chequeo.__name__,
                                                     type(e).__name__, e), None))
        for estado, texto, arreglo in filas:
            print("  %-6s %s" % (estado, texto))
            if arreglo and estado != OK:
                print("         -> %s" % arreglo)
        if any(f[0] == FALTA for f in filas):
            if obligatorio:
                falta_base = True
            else:
                apagados.append(titulo)
    print("")
    if falta_base:
        print("El panel NO va a abrir: resuelve primero el bloque 'Panel'.")
    elif apagados:
        print("El panel abre. No van a andar: " + "; ".join(apagados) + ".")
    else:
        print("Todo listo.")
    return 1 if falta_base else 0


if __name__ == "__main__":
    sys.exit(main())

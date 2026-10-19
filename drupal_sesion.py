#!/usr/bin/env python3
"""Sesion del admin de Drupal CERT para revisar contenido con Playwright.

    python drupal_sesion.py login              abre Chromium en el login de Drupal;
                                               la persona inicia sesion, presiona
                                               Enter en la consola y la sesion
                                               queda guardada en ~/.panel_qa
    python drupal_sesion.py estado             dice si la sesion guardada sigue viva
    python drupal_sesion.py ver RUTA [RUTA..]  abre cada RUTA con la sesion y vuelca
                                               el texto de la pagina

Nadie escribe la clave aqui: el login lo hace la persona en la ventana. Con
el Enter el script confirma que Drupal la dejo entrar, guarda las cookies y
cierra el navegador.

Todo lo que no es `login` va en SOLO LECTURA: el contexto aborta cualquier
peticion que no sea GET/HEAD/OPTIONS, asi que ni un clic accidental puede
guardar un nodo. RUTA puede ser relativa al sitio (/admin/content,
/jsonapi/node/casuistica...) o una URL completa del mismo sitio.
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

from rutas import DIR_DATOS

SITIO = "https://platform-test-external.colsubsidio.com/loans-cert-admin-solicitud"
LOGIN = SITIO + "/user/login"
# Pagina que solo ve alguien con sesion: sin ella Drupal responde 403.
PRUEBA = SITIO + "/admin/content"
SESION = os.path.join(DIR_DATOS, "drupal_cert_sesion.json")

METODOS_LECTURA = {"GET", "HEAD", "OPTIONS"}


def _cookie_de_sesion(cookies):
    """Drupal llama a su cookie SESS<hash> (SSESS<hash> en https)."""
    return next((c for c in cookies
                 if c["name"].startswith(("SESS", "SSESS"))), None)


def _solo_lectura(route):
    if route.request.method in METODOS_LECTURA:
        route.continue_()
    else:
        route.abort()


def abrir(p, headless=True):
    """Navegador y contexto con la sesion guardada, en solo lectura.

    Para otros scripts: `with sync_playwright() as p: browser, ctx = abrir(p)`.
    """
    if not os.path.exists(SESION):
        raise SystemExit("No hay sesion guardada. Corre primero: "
                         "python drupal_sesion.py login")
    browser = p.chromium.launch(headless=headless)
    context = browser.new_context(storage_state=SESION)
    context.route("**/*", _solo_lectura)
    return browser, context


def _hay_sesion(page):
    respuesta = page.goto(PRUEBA, wait_until="domcontentloaded")
    return (respuesta is not None and respuesta.status == 200
            and "/user/login" not in page.url)


_VENTANA_CERRADA = ("Cerraste la ventana antes de iniciar sesion; "
                    "no se guardo nada.")


def _entro(context, page):
    """Drupal ya acepto la clave? Solo mira cookies y URL: no navega, asi que
    no le borra el formulario a quien todavia esta escribiendo."""
    return (_cookie_de_sesion(context.cookies())
            and "/user/login" not in page.url)


def _esperar_enter(context, page):
    """La persona avisa con Enter. Si aun no entro, se le dice y se espera
    otro Enter: un Enter adelantado no tira el login."""
    print("Inicia sesion en la ventana de Chromium y despues presiona Enter "
          "aqui (Ctrl+C para cancelar).")
    while True:
        input()
        try:
            if _entro(context, page):
                return
        except Exception:
            raise SystemExit(_VENTANA_CERRADA)
        print("Drupal todavia no te deja entrar. Termina el login en la "
              "ventana y presiona Enter otra vez.")


def _esperar_sola(context, page, timeout_min):
    """Sin consola no hay Enter que esperar: se mira cada segundo."""
    print(f"Sin consola: espero el login hasta {timeout_min} min...")
    limite = time.time() + timeout_min * 60
    while time.time() < limite:
        try:
            if _entro(context, page):
                return
            page.wait_for_timeout(1000)
        except Exception:
            # Playwright revienta asi cuando la persona cierra la ventana.
            raise SystemExit(_VENTANA_CERRADA)
    raise SystemExit("Se acabo el tiempo sin iniciar sesion; "
                     "no se guardo nada.")


def login(timeout_min):
    os.makedirs(DIR_DATOS, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(LOGIN)
        try:
            try:
                _esperar_enter(context, page)
            except EOFError:
                _esperar_sola(context, page, timeout_min)

            # La cookie aparece apenas Drupal acepta la clave; se confirma con
            # una pagina que solo abre alguien con sesion.
            if not _hay_sesion(page):
                raise SystemExit("Drupal no dejo ver /admin/content con esa "
                                 "sesion; no se guardo nada.")
            context.storage_state(path=SESION)
        finally:
            browser.close()
    print(f"Sesion guardada en {SESION}")
    _imprimir_vencimiento()


def _imprimir_vencimiento():
    with open(SESION, encoding="utf-8") as f:
        cookie = _cookie_de_sesion(json.load(f).get("cookies", []))
    if cookie and cookie.get("expires", -1) > 0:
        vence = datetime.fromtimestamp(cookie["expires"])
        print(f"La cookie vence el {vence:%Y-%m-%d %H:%M} "
              "(Drupal puede cerrarla antes por inactividad).")


def estado():
    if not os.path.exists(SESION):
        print("No hay sesion guardada. Corre: python drupal_sesion.py login")
        return 1
    with sync_playwright() as p:
        browser, context = abrir(p)
        viva = _hay_sesion(context.new_page())
        browser.close()
    if not viva:
        print("La sesion guardada ya no sirve (Drupal pide login otra vez). "
              "Corre: python drupal_sesion.py login")
        return 1
    print("Sesion viva.")
    _imprimir_vencimiento()
    return 0


def _url(ruta):
    if ruta.startswith("http"):
        if not ruta.startswith(SITIO):
            raise SystemExit(f"{ruta} no es del Drupal de CERT; "
                             "la sesion no se usa fuera de el.")
        return ruta
    return SITIO + "/" + ruta.lstrip("/")


def ver(rutas, max_chars, salida):
    with sync_playwright() as p:
        browser, context = abrir(p)
        page = context.new_page()
        for ruta in rutas:
            url = _url(ruta)
            respuesta = page.goto(url, wait_until="domcontentloaded")
            codigo = respuesta.status if respuesta else "sin respuesta"
            print(f"===== {url}\nHTTP {codigo} | final: {page.url} | "
                  f"titulo: {page.title()}")
            # Sin sesion Drupal no siempre manda al login: en el admin responde
            # 403 en la misma URL.
            if "/user/login" in page.url or codigo == 403:
                print("Drupal no deja ver esta pagina: la sesion vencio o el "
                      "usuario no tiene permiso. Si vencio, corre: "
                      "python drupal_sesion.py login")
                continue
            # El area de contenido de Drupal; si el tema no la tiene, el body.
            zona = page.locator("main, [role=main]").first
            texto = (zona.inner_text() if zona.count()
                     else page.locator("body").inner_text())
            if salida:
                os.makedirs(salida, exist_ok=True)
                nombre = "".join(c if c.isalnum() else "_"
                                 for c in ruta.strip("/"))[:120] or "inicio"
                with open(os.path.join(salida, nombre + ".txt"), "w",
                          encoding="utf-8") as f:
                    f.write(texto)
            print(texto[:max_chars] if max_chars else texto)
        browser.close()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="comando", required=True)
    p_login = sub.add_parser("login", help="iniciar sesion a mano y guardarla")
    p_login.add_argument("--minutos", type=float, default=5,
                         help="sin consola (sin Enter posible), cuanto esperar "
                              "el login (por defecto 5)")
    sub.add_parser("estado", help="ver si la sesion guardada sigue viva")
    p_ver = sub.add_parser("ver", help="volcar el texto de paginas del admin")
    p_ver.add_argument("rutas", nargs="+")
    p_ver.add_argument("--max", type=int, default=0,
                       help="cortar el texto de cada pagina a N caracteres")
    p_ver.add_argument("--salida", help="carpeta donde guardar cada texto")
    args = parser.parse_args()

    if args.comando == "login":
        login(args.minutos)
    elif args.comando == "estado":
        sys.exit(estado())
    else:
        ver(args.rutas, args.max, args.salida)


if __name__ == "__main__":
    main()

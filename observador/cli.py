"""Argumentos, armado de las piezas y loop principal."""
import argparse
import os
import re
import threading
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

from observador.alcance import Alcance
from observador.cierre import cerrar
from observador.complementos import armar_sonda
from observador.config import (ENDPOINTS_RASTREADOS, ESQUEMAS_DEFAULT,
                               HOSTS_DEFAULT, RUTAS_APP, SCRIPT,
                               SHOT_RESPUESTA_DEFAULT)
from observador.disco import rehacer_reporte
from observador.navegador import lanzar_chrome, limpiar_navegador
from observador.observador import Observador
from observador.parada import (SIN_REPORTE, avisar_pendiente, modo_parada,
                               vigilar_parada)
from observador.util import es_url_real


def armar_parser():
    ap = argparse.ArgumentParser(
        description="Observador pasivo: tu navegas, el script captura pantallas y requests.")
    ap.add_argument("--flujo", default="flujo", help="nombre del flujo (va en la carpeta)")
    ap.add_argument("--puerto", type=int, default=9222, help="puerto CDP de Chrome")
    ap.add_argument("--out", default="evidences", help="carpeta raiz de evidencias")
    ap.add_argument("--hosts", default=",".join(HOSTS_DEFAULT),
                    help="hosts a capturar, separados por coma")
    ap.add_argument("--todos-los-hosts", action="store_true",
                    help="captura todo, sin filtro de dominio")
    ap.add_argument("--solo-url", default=None, metavar="PATRON",
                    help="observa SOLO la pestana cuya ruta contenga PATRON; "
                         "varias separadas por coma (las de la app: %s)"
                         % ", ".join(RUTAS_APP))
    ap.add_argument("--seguir-popups", action="store_true",
                    help="con --solo-url, sigue tambien las pestanas que abra la observada")
    ap.add_argument("--captura", choices=["endpoints", "hosts", "todo"], default="endpoints",
                    help="que requests se guardan: solo los endpoints rastreados (default), "
                         "todo lo de los hosts del backend, o absolutamente todo")
    ap.add_argument("--pantallazo-extra", default="cupo-de-credito/fin", metavar="PATRONES",
                    help="URLs (separadas por coma) que ademas llevan un segundo "
                         "pantallazo tardio; cadena vacia para desactivar")
    ap.add_argument("--extra-ms", type=int, default=3000,
                    help="espera del pantallazo extra tras abrir el paso")
    ap.add_argument("--screenshot-on-response", default=SHOT_RESPUESTA_DEFAULT,
                    metavar="PATRON",
                    help="pantallazo cuando responda un endpoint que case con "
                         "PATRON; varios separados por coma (default: %(default)s)")
    ap.add_argument("--solo-endpoints", action="store_true",
                    help=argparse.SUPPRESS)   # compat: equivale a --captura endpoints
    ap.add_argument("--endpoints", default=None, metavar="LISTA",
                    help="sobreescribe los endpoints rastreados, separados por coma")
    ap.add_argument("--rehacer-reporte", default=None, metavar="DIR",
                    help="regenera reporte/resumen/har desde una carpeta de evidencia ya capturada")
    ap.add_argument("--esquemas", default=ESQUEMAS_DEFAULT, metavar="ARCHIVO",
                    help="baseline JSON Schema de los servicios (default: %(default)s)")
    ap.add_argument("--generar-esquemas", action="store_true",
                    help="toma esta corrida como contrato bueno y actualiza el baseline "
                         "en vez de validar contra el")
    ap.add_argument("--sin-redactar", action="store_true",
                    help="NO redacta tokens ni cookies (cuidado con la evidencia)")
    ap.add_argument("--settle-ms", type=int, default=1200,
                    help="espera tras un cambio de pantalla antes del screenshot")
    ap.add_argument("--limpiar", action="store_true",
                    help="arranca sin sesion previa: borra cookies, cache y "
                         "almacenamiento antes de capturar (como incognito)")
    ap.add_argument("--stop-file", default=None, metavar="RUTA",
                    help="corta limpiamente cuando aparezca ese archivo; equivale a "
                         "Ctrl+C, asi que el reporte se genera igual (lo usa el panel)")
    ap.add_argument("--duracion", type=int, default=0,
                    help="corta solo tras N segundos (0 = hasta Ctrl+C)")
    ap.add_argument("--espera-en-vuelo", type=int, default=30, metavar="SEG",
                    help="al parar, espera hasta SEG segundos a los requests que "
                         "siguen sin respuesta (el API Gateway corta a los 29 s); "
                         "0 = no esperar (default: %(default)s)")
    ap.add_argument("--lanzar-chrome", action="store_true",
                    help="abre Chrome con el puerto de depuracion y sale")
    ap.add_argument("--request-check", action="store_true",
                    help="consulta /request/check al responder el login, al detectar "
                         "el documento y al llegar a informacion personal "
                         "(lo llama el servidor del front, el navegador no lo ve). "
                         "Necesita token.txt")
    ap.add_argument("--documento", default=None, metavar="TIPO:NUMERO",
                    help="documento para /request/check (CC:123, CO1C:123). Sin el, "
                         "se toma del primer request que lo traiga. Implica "
                         "--request-check")
    return ap


def armar_complementos(args):
    """Los complementos de esta corrida. ValueError si un argumento no sirve."""
    complementos = []
    sonda = armar_sonda(args.request_check, args.documento)
    if sonda:
        complementos.append(sonda)
    return complementos


def corregir_ruta_msys(solo_url):
    """Git Bash/MSYS convierte un argumento que empieza con "/" en ruta de
    Windows: "/creditos/solicitud" llega como
    "C:/Program Files/Git/creditos/solicitud"."""
    if solo_url and re.search(r"^[A-Za-z]:[/\\].*Git[/\\]", solo_url):
        limpio = re.sub(r"^[A-Za-z]:[/\\].*?Git[/\\]", "", solo_url)
        print("AVISO: tu shell convirtio el patron en una ruta de Windows.")
        print("       Recibido: %s" % solo_url)
        print("       Uso:      %s" % limpio)
        print("       Para evitarlo, no empieces el patron con \"/\".\n")
        return limpio
    return solo_url


def main():
    args = armar_parser().parse_args()

    if args.lanzar_chrome:
        return lanzar_chrome(args.puerto)

    endpoints = ([e.strip() for e in args.endpoints.split(",") if e.strip()]
                 if args.endpoints else list(ENDPOINTS_RASTREADOS))

    if args.rehacer_reporte:
        return rehacer_reporte(args.rehacer_reporte, endpoints,
                               ruta_esquemas=args.esquemas,
                               generar=args.generar_esquemas)

    try:
        complementos = armar_complementos(args)
    except ValueError as e:
        print("! %s" % e)
        return 2

    modo = "todo" if args.todos_los_hosts else args.captura
    if args.solo_endpoints:
        modo = "endpoints"
    hosts = [] if modo == "todo" else [h.strip() for h in args.hosts.split(",") if h.strip()]
    extras = [e.strip() for e in (args.pantallazo_extra or "").split(",") if e.strip()]
    marca = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dir_salida = os.path.join(args.out, "%s_%s" % (re.sub(r"[^A-Za-z0-9._-]+", "-", args.flujo), marca))
    os.makedirs(dir_salida, exist_ok=True)

    args.solo_url = corregir_ruta_msys(args.solo_url)
    # sin --solo-url no se filtra nada; con el, se aceptan varias rutas para
    # que el mismo comando sirva en los dos despliegues del front
    patrones = ([x.strip() for x in args.solo_url.split(",") if x.strip()]
                if args.solo_url else [])
    alcance = Alcance(hosts, endpoints=endpoints, solo_endpoints=(modo == "endpoints"),
                      patrones=patrones, seguir_popups=args.seguir_popups)
    obs = Observador(dir_salida, alcance, not args.sin_redactar, args.settle_ms,
                     pantallazo_extra=extras, extra_ms=args.extra_ms,
                     screenshot_on_response=args.screenshot_on_response,
                     complementos=complementos)

    # el reporte se genera al final, pase lo que pase con Playwright
    conectado = True
    try:
        conectado = observar(args, obs) is not False
    except BaseException as e:
        if not isinstance(e, KeyboardInterrupt):
            print("Playwright fallo (%s); genero el reporte igual." % type(e).__name__)
    if not conectado:
        try:
            os.rmdir(dir_salida)   # no dejar carpeta vacia si ni conectamos
        except OSError:
            pass
        return 1
    if getattr(obs, "sin_reporte", False):
        avisar_pendiente(obs)
    else:
        cerrar(obs, args.flujo, ruta_esquemas=args.esquemas,
               generar=args.generar_esquemas)
    return 0


def _fijar_inicio(obs, paginas, solo_url):
    """La pestana activa al arrancar, con su primer paso si ya esta en el flujo."""
    alcance = obs.alcance
    activa = paginas[0]
    if solo_url:
        # si la pestana objetivo ya esta abierta, la fijamos de una
        for pg in paginas:
            try:
                if alcance.intentar_lock(pg, pg.url):
                    activa = pg
                    obs.abrir_paso(pg, pg.url)
                    break
            except Exception:
                continue
        if alcance.lock is None:
            print("Aun no veo ninguna pestana con %s."
                  % " ni ".join('"%s"' % p for p in alcance.patrones))
            print("Navega a esa URL y la fijo automaticamente.")
    elif es_url_real(activa.url):
        obs.abrir_paso(activa, activa.url)
    else:
        print("Esperando la primera pantalla (la pestana esta en %s)..." % activa.url)
    return activa


def _banner(obs):
    for linea in obs.alcance.describir():
        print(linea)
    if obs.pantallazos.pantallazo_extra:
        print("Pantallazo extra en: %s" % ", ".join(obs.pantallazos.pantallazo_extra))
    print("Redaccion de credenciales: %s" % ("ON" if obs.redactar else "OFF"))
    for c in obs.complementos:
        linea = c.describir()
        if linea:
            print(linea)
    print("Escuchando. Navega normal. Ctrl+C para cerrar y generar el reporte.\n")


def _pedir_parada(args, obs):
    """True si el panel dejo el centinela. Segun lo que diga, se arma el
    reporte o se deja la evidencia cruda para generarlo luego."""
    if not (args.stop_file and os.path.exists(args.stop_file)):
        return False
    obs.sin_reporte = modo_parada(args.stop_file) == SIN_REPORTE
    print("\nParada solicitada%s." % (" (sin reporte)" if obs.sin_reporte else ""))
    try:
        os.remove(args.stop_file)
    except OSError:
        pass
    return True


def observar(args, obs):
    """Sesion de Playwright: engancha, escucha y devuelve al terminar."""
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:%d" % args.puerto)
        except Exception as e:
            print("No pude conectar al puerto %d: %s" % (args.puerto, e))
            print("Lanza Chrome primero:  python %s --lanzar-chrome" % SCRIPT)
            return False

        if not browser.contexts:
            print("Chrome esta conectado pero no tiene contexto abierto.")
            return False
        # todos los contextos y todas sus pestanas, mas las que abras despues
        paginas = []
        for ctx in browser.contexts:
            for pg in ctx.pages:
                obs.enganchar(pg)
                paginas.append(pg)
            ctx.on("page", lambda pg: obs.enganchar(pg))
        if not paginas:
            paginas = [browser.contexts[0].new_page()]
            obs.enganchar(paginas[0])
        print("Pestanas enganchadas al inicio: %d" % len(paginas))
        if args.limpiar:
            limpiar_navegador(browser, paginas, obs.alcance.hosts or HOSTS_DEFAULT)

        activa = _fijar_inicio(obs, paginas, args.solo_url)
        _banner(obs)

        limite = (time.time() + args.duracion) if args.duracion else None
        if args.stop_file and os.path.exists(args.stop_file):
            os.remove(args.stop_file)   # sobra de una corrida anterior
        if args.stop_file:
            threading.Thread(
                target=vigilar_parada, daemon=True,
                args=(obs, args.flujo, args.esquemas, args.generar_esquemas,
                      args.stop_file)).start()
        try:
            while True:
                # parada limpia pedida desde afuera: sale por el mismo camino
                # que Ctrl+C
                if _pedir_parada(args, obs):
                    break
                if limite and time.time() >= limite:
                    print("\nLimite de %d s alcanzado." % args.duracion)
                    break
                try:
                    activa.wait_for_timeout(200)  # bombea los eventos de Playwright
                except Exception:
                    # cerraste esa pestana: seguimos con cualquier otra viva
                    vivas = [p for c in browser.contexts for p in c.pages]
                    if not vivas:
                        print("\nNo quedan pestanas abiertas.")
                        break
                    activa = vivas[0]
                    continue
                obs.tick()
        except KeyboardInterrupt:
            print("\nCerrando...")
        finally:
            obs.parar(activa, args.espera_en_vuelo)
    return True

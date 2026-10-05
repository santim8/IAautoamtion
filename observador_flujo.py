#!/usr/bin/env python3
"""
Observador pasivo de flujos: tu navegas a mano, el script mira y guarda evidencia.

Se engancha a un Chrome ya abierto (CDP, puerto 9222) igual que open_chrome.py.
NO maneja el navegador: solo escucha.

La unidad de evidencia es el PASO (una pantalla). Se abre un paso nuevo cuando
cambia la URL -- por navegacion real o por ruta de SPA (history.pushState) -- y
todos los requests que ocurren hasta el siguiente cambio quedan agrupados ahi.

Salida:
  evidences/<flujo>_<fecha>/
      00_<slug>/screenshot.png
      00_<slug>/requests.jsonl
      ...
      captura.har        (HAR 1.2 derivado de lo capturado)
      resumen.json
      reporte.html       (timeline: pantalla | requests, lado a lado)

Uso:
  1. python observador_flujo.py --lanzar-chrome
  2. python observador_flujo.py --flujo "validaciones-card"
  3. Navegas normal. Ctrl+C para cerrar y generar el reporte.

Por defecto solo captura los hosts del backend (ver HOSTS_DEFAULT) y redacta
credenciales. --todos-los-hosts y --sin-redactar desactivan cada cosa.

--request-check consulta ademas /request/check (ver sonda_check.py): apenas
responde el login de Gigya (con el documento que trae), al detectar el documento
en validaciones y al llegar a informacion personal, cuando el caso ya esta
creado: ese endpoint lo llama el servidor del front, no el navegador, asi que
sin la sonda nunca aparece en la evidencia.

Los requests que el front nunca pudo leer tambien quedan, marcados: los que
Chrome bloquea por CORS (con el status real que respondio el servidor), los
cortados por la red y los que seguian en vuelo al parar. Al parar se espera
hasta --espera-en-vuelo segundos a que estos ultimos respondan.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

import esquemas as esq
import rutas
import sonda_check

# Hosts del backend que interesan (match por substring sobre la URL).
# Sacados de bruno/validate-request/.
HOSTS_DEFAULT = [
    "colsubsidio-test.apigee.net",
    "platform-test-external.colsubsidio.com",
    "platform-test-internal.colsubsidio.com",
    "dev.colsubsidio.com",
    "d2b80yrnend1dj.cloudfront.net",
]

# Rutas de la aplicacion, una por despliegue. Es lo que --solo-url usa por
# defecto para reconocer la pestana del flujo.
RUTAS_APP = ["creditos/solicitud", "loans-dev-solicitud"]

# Endpoints de negocio que interesan (match por substring sobre la URL).
# Login de Gigya (CIAM). Su respuesta trae el documento del afiliado, con el
# que --request-check consulta la retoma apenas se loguea.
LOGIN_GIGYA = "/accounts.login"

# Espejo de TRACKED_ENDPOINTS del framework Java, para poder comparar 1:1.
ENDPOINTS_RASTREADOS = [
    "/decision-engine",
    "validate-request",
    "/eligibility/external/v2/affiliation-validations",
    "/card-validations",
    "/eligibility/external/v1/product-validations",
    "/eligibility/external/v1/campaigns/",
    "/eligibility/internal/v1/campaigns/",
    "/request/validate-request",
    "/external/v1/product/2/request/offer-config",
    "/request/offer/",
    "/loans/req-mgr/external/v1/product/2/request/offer-config",
    "/loans/req-mgr/external/v1/product/2/request/request-data",
    "/request/request-data",
    "/request/cancel-request",
    "/request/decision-engine/start",
    "/loans/loan-util/external/modification-quota-amount",
    LOGIN_GIGYA,     # fuera del espejo Java, ver ENDPOINTS_SIN_PAYLOAD
]

# Endpoints cuyo payload NUNCA se guarda, ni con --sin-redactar: el login de
# Gigya manda loginID y password en form-urlencoded, que la redaccion por clave
# JSON no alcanza. Se queda la respuesta (redactada como cualquier otra).
ENDPOINTS_SIN_PAYLOAD = [LOGIN_GIGYA]

# Endpoints tras los que el front recarga la pagina apenas responden. Al
# recargar, Chrome descarta el cuerpo de la respuesta y leido desde el loop
# llegaba tarde ("body no disponible"): se lee dentro del handler.
ENDPOINTS_CUERPO_INMEDIATO = [LOGIN_GIGYA]

# La version del path es un comodin: los servicios pasan de v1 a v2 segun se
# activen las novedades, y con la version fija ese trafico dejaria de
# reconocerse justo cuando mas interesa mirarlo. Se guarda la version que
# realmente llego para poder avisar del cambio.
RE_VERSION = re.compile(r"/v(\d+)/")


def patron_endpoint(endpoint):
    """Compila un endpoint rastreado dejando /vN/ como comodin."""
    partes = [re.escape(t) for t in RE_VERSION.split(endpoint)[::2]]
    return re.compile(r"/v\d+/".join(partes))


def version_declarada(endpoint):
    m = RE_VERSION.search(endpoint)
    return m.group(1) if m else None


def version_de(url):
    m = RE_VERSION.search(url)
    return m.group(1) if m else None


def casan(endpoints, url):
    """Patrones rastreados que casan con esta URL, con la version al vuelo."""
    return [e for e in endpoints if patron_endpoint(e).search(url)]


def va_a_hosts(url, hosts):
    """El request va a uno de esos hosts. Se mira solo el host: los beacons de
    Google y Gigya llevan la URL de la app en la query (url=, pageURL=) y con
    un match sobre la URL entera pasaban por trafico del backend."""
    try:
        host = urlsplit(url).netloc
    except ValueError:
        return False
    return any(h in host for h in hosts)


def sin_payload(url):
    return bool(casan(ENDPOINTS_SIN_PAYLOAD, url or ""))


# --- redaccion -------------------------------------------------------------
HEADERS_SENSIBLES = {
    "authorization", "cookie", "set-cookie", "x-api-key", "apikey",
    "x-auth-token", "proxy-authorization",
}
CLAVES_SENSIBLES = re.compile(
    r"(token|password|passwd|secret|authorization|cookie|clientsecret|client_secret|signature|uidsig)",
    re.I,
)
RE_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9\-_\.=]{20,}", re.I)
RE_JWT = re.compile(r"\beyJ[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]*")

REDACTADO = "<REDACTED>"
MAX_BODY = 200_000     # bytes; mas alla de esto se trunca
MAX_BODY_HTML = 8_000  # lo que se pinta en reporte.html (el resto, en requests.jsonl)

# Tipos de recurso cuyo cuerpo no aporta a una evidencia de QA. Los bundles JS
# solos pesaban decenas de MB. Se guardan igual el metodo, la URL y el status.
TIPOS_SIN_CUERPO = {"image", "font", "media", "stylesheet", "script", "manifest"}

# Margen para decidir a que pantalla pertenece un request que arranca justo
# antes de que la SPA cambie de ruta. La app suele disparar la peticion de datos
# de la pantalla nueva unas decenas de ms ANTES del pushState, asi que sin este
# margen ese trafico queda archivado en la pantalla anterior.
TOLERANCIA_CAMBIO_MS = 300

# Un request que el navegador corta (CORS, red caida) llega por dos vias: el
# requestfailed de Playwright y, por la sesion CDP propia, el status que el
# servidor si respondio. Se espera este margen antes de registrarlo para que
# las dos hayan hablado.
ESPERA_FALLO_MS = 400
# Requests que la sesion CDP recuerda mientras se sabe si fallan o no.
MAX_CDP_RED = 500
# Lo que CDP vio terminar y Playwright no reporto en este margen se registra
# desde CDP (ver drenar_huerfanos). Holgado: Playwright lee el body en el loop.
ESPERA_HUERFANO_S = 2.0
# Lo que quedo sin respuesta al cerrar el observador.
SIN_RESPUESTA = "sin respuesta"

# Contrato observado de cada servicio. Vive en el repo (no en evidences/) porque
# es lo que se compara entre corridas y lo que se revisa en un PR. Se ESCRIBE
# con --generar-esquemas, asi que va a BASE: dentro del .exe seria una carpeta
# temporal que se borra al cerrar.
ESQUEMAS_DEFAULT = os.path.join(rutas.BASE, "esquemas_servicios.json")

# Servicios cuya respuesta pinta una pantalla que vale la pena dejar retratada
# en ese instante. Todos son OPCIONALES: si el flujo no pasa por esa pantalla
# el servicio no responde y simplemente no hay pantallazo, sin ruido.
SHOT_RESPUESTA_DEFAULT = ",".join([
    "request/offer",                 # personalizacion de oferta
    "parametros/estado_civil",       # datos personales; a veces se omite
    "modification-quota-amount",     # modificacion del cupo en personalizacion
    "creditos/solicitud/login",      # pantalla de login (documento)
    "accounts.login",                # login de Gigya (CIAM)
])

# Disparadores tras los que la app recarga la pagina (patron -> metodo que
# dispara): despues del login de Gigya el front recarga /login, y retratarla
# dentro del handler colgaba el screenshot hasta el timeout. Se retratan desde
# el loop cuando la pantalla se asienta, reintentando sin limite de tiempo (ver
# tomar_shots_tarde). Solo cuenta la respuesta del POST: es la del login.
SHOT_TRAS_RECARGA = {"accounts.login": "POST"}
# Tope del intervalo entre reintentos de un pantallazo que no sale: cada
# intento fallido bloquea el loop hasta el timeout del screenshot.
MAX_REINTENTO_SHOT_MS = 10_000


def redactar_texto(txt):
    if not isinstance(txt, str):
        return txt
    txt = RE_BEARER.sub(r"\1" + REDACTADO, txt)
    txt = RE_JWT.sub(REDACTADO, txt)
    return txt


def redactar_headers(headers):
    return {
        k: (REDACTADO if k.lower() in HEADERS_SENSIBLES else redactar_texto(v))
        for k, v in headers.items()
    }


def redactar_json(obj):
    """Recorre un JSON y redacta valores cuya clave parezca sensible."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if CLAVES_SENSIBLES.search(str(k)):
                out[k] = REDACTADO
            else:
                out[k] = redactar_json(v)
        return out
    if isinstance(obj, list):
        return [redactar_json(v) for v in obj]
    return redactar_texto(obj)


def redactar_body(texto):
    """Intenta como JSON (redaccion por clave); si no, redaccion por regex."""
    if not texto:
        return texto
    try:
        return json.dumps(redactar_json(json.loads(texto)), ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return redactar_texto(texto)


# --- utilidades ------------------------------------------------------------
def slug_de_url(url):
    """Nombre corto y legible para la carpeta del paso, sacado del path."""
    try:
        sin_query = url.split("?")[0].split("#")[0]
        partes = [p for p in sin_query.split("/")[3:] if p]
    except (IndexError, AttributeError):
        partes = []
    base = "-".join(partes[-2:]) if partes else "home"
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-").lower()
    return (base or "home")[:48]


def ahora_iso():
    return datetime.now(timezone.utc).isoformat()


def ruta_de(url):
    """La URL sin query ni fragmento: esquema, host y path.

    El patron de --solo-url tiene que casar contra la ruta real. Las paginas
    auxiliares de SSO llevan la URL de la app dentro del fragmento
    (#origin=https://.../creditos/solicitud/login) y se hacian pasar por la
    pestana buena: el observador se fijaba a una de ellas y la app quedaba
    ignorada, con la corrida entera vacia.
    """
    return (url or "").split("#")[0].split("?")[0]


def cabeceras_request(request, completas=True):
    """Cabeceras del request; las completas solo con el request ya terminado.

    completas=False no toca Playwright (las provisionales ya estan cargadas):
    es lo que se puede usar al cerrar o desde el hilo vigilante.
    """
    if request is None:
        return {}
    if completas:
        try:
            return request.all_headers()
        except Exception:
            pass
    try:
        return dict(request.headers)
    except Exception:
        return {}


def es_url_real(url):
    """about:blank y chrome:// no son pantallas del flujo, son ruido de arranque."""
    return bool(url) and url.startswith(("http://", "https://"))


def lanzar_chrome(puerto):
    """Abre Chrome con puerto de depuracion y perfil aparte (el login persiste)."""
    candidatos = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    exe = next((c for c in candidatos if os.path.exists(c)), None)
    if not exe:
        print("No encontre chrome.exe. Lanzalo a mano con:")
        print(f'  chrome.exe --remote-debugging-port={puerto} '
              r'--user-data-dir="%USERPROFILE%\.chrome-qa-debug"')
        return 1
    perfil = os.path.join(os.path.expanduser("~"), ".chrome-qa-debug")
    os.makedirs(perfil, exist_ok=True)
    subprocess.Popen([exe, f"--remote-debugging-port={puerto}",
                      f"--user-data-dir={perfil}", "--no-first-run",
                      "--no-default-browser-check"])
    print(f"Chrome lanzado en el puerto {puerto} con perfil {perfil}")
    print("Es un perfil aparte: la primera vez toca loguearte de nuevo.")
    print("\nEste script ya termino; Chrome queda abierto. Ahora:")
    print(f"  python {os.path.basename(__file__)} --flujo \"mi-flujo\"")
    return 0


def origenes_app(hosts, paginas):
    """Origenes cuyo almacenamiento hay que vaciar.

    Los hosts del backend mas el de la pestana que este abierta: la sesion no
    vive solo en la app, tambien en el proveedor de SSO que la autentica.
    """
    origenes = {"https://%s" % h for h in hosts if "." in h}
    for pg in paginas:
        try:
            partes = (pg.url or "").split("/")
            if len(partes) > 2 and partes[0].startswith("http"):
                origenes.add("%s//%s" % (partes[0], partes[2]))
        except Exception:
            continue
    return sorted(origenes)


def limpiar_navegador(browser, paginas, hosts):
    """Deja el navegador como recien abierto: sin cookies, cache ni storage.

    Es el equivalente a abrir una ventana de incognito, pero sobre el Chrome que
    ya esta conectado: crear un contexto de incognito por CDP no es algo que
    Playwright permita sobre un navegador al que solo se engancho.
    """
    if not paginas:
        return
    pagina = paginas[0]
    borrados = []
    try:
        sesion = pagina.context.new_cdp_session(pagina)
    except Exception as e:
        print("! No pude abrir sesion CDP para limpiar: %s" % e)
        return
    for comando in ("Network.clearBrowserCookies", "Network.clearBrowserCache"):
        try:
            sesion.send(comando)
            borrados.append(comando.split(".")[1])
        except Exception as e:
            print("! %s fallo: %s" % (comando, e))
    n = 0
    for origen in origenes_app(hosts, paginas):
        try:
            sesion.send("Storage.clearDataForOrigin",
                        {"origin": origen, "storageTypes": "all"})
            n += 1
        except Exception:
            continue          # origen que Chrome no reconoce: no es un problema
    # sessionStorage es por pestana, no por origen: Storage.clearDataForOrigin
    # no lo toca y sobrevivia a la limpieza. Hay que vaciarlo desde la pagina.
    vaciadas = 0
    for pg in paginas:
        try:
            if not es_url_real(pg.url):
                continue
            pg.evaluate("() => { try { sessionStorage.clear(); } catch (e) {}"
                        " try { localStorage.clear(); } catch (e) {} }")
            vaciadas += 1
        except Exception:
            continue
    print("Limpieza: %s, storage de %d origen(es), %d pestana(s) vaciadas."
          % (", ".join(borrados) or "nada", n, vaciadas))
    # sin recargar, la pagina sigue con la sesion viva en memoria
    for pg in paginas:
        try:
            if es_url_real(pg.url):
                pg.reload(wait_until="domcontentloaded", timeout=15000)
        except Exception:
            continue


# --- observador ------------------------------------------------------------
JS_HOOK_RUTA = """
(() => {
  if (window.__obsHooked) return;
  window.__obsHooked = true;
  const avisar = () => { try { window.__obsRuta(location.href); } catch (e) {} };
  for (const m of ['pushState', 'replaceState']) {
    const orig = history[m];
    history[m] = function () { const r = orig.apply(this, arguments); avisar(); return r; };
  }
  window.addEventListener('popstate', avisar);
  window.addEventListener('hashchange', avisar);
})();
"""


class Observador:
    def __init__(self, dir_salida, hosts, redactar, settle_ms,
                 patron_pestana=None, seguir_popups=False,
                 endpoints=None, solo_endpoints=False,
                 pantallazo_extra=None, extra_ms=3000,
                 screenshot_on_response=None, sonda=None):
        self.dir = dir_salida
        self.sonda = sonda           # SondaCheck o None: /request/check por pantalla
        self.hosts = hosts           # [] = capturar todo
        self.endpoints = endpoints or []   # endpoints de negocio a marcar
        self.endpoints_rx = [(e, patron_endpoint(e)) for e in self.endpoints]
        self.solo_endpoints = solo_endpoints
        # pantallas que ademas merecen un segundo pantallazo mas tarde
        # (pantalla final / thank-you page: suele pintar contenido async)
        self.pantallazo_extra = pantallazo_extra or []
        self.extra_ms = extra_ms
        # tomar pantallazo cuando responda ciertos endpoints clave
        # (hardcodeado: request/offer para capturar estado de personalización)
        patrones = screenshot_on_response or SHOT_RESPUESTA_DEFAULT
        if isinstance(patrones, str):
            patrones = [x.strip() for x in patrones.split(",") if x.strip()]
        self.screenshot_on_response = patrones
        self.redactar = redactar
        self.settle_ms = settle_ms
        # --- alcance por pestana (independiente del filtro de hosts) ---
        # lista de rutas aceptadas; vacia = todas las pestanas
        if isinstance(patron_pestana, str):
            patron_pestana = [x.strip() for x in patron_pestana.split(",")
                              if x.strip()]
        self.patrones = list(patron_pestana or [])
        self.seguir_popups = seguir_popups
        self.lock = None             # la pestana elegida, una vez encontrada
        self.hijas = set()           # pestanas abiertas POR la elegida
        self.sin_pestana = 0         # requests sin frame (service worker), para avisar
        self.pasos = []              # [{idx, url, slug, dir, ts, pestana, requests: [...]}]
        self.cola_resp = []          # respuestas pendientes de leer body
        self.cuerpos = {}            # response -> body ya leido en el handler
        self.pendientes = {}         # pagina -> (url, timestamp_ms) cambio en espera
        self.extras = []             # [(paso, pagina, cuando_ms)] pantallazos extra
        self.shots_dif = []          # [(paso, pagina, cuando_ms)] shot de paso adelantado
        self.shots_resp = []         # [(pagina, nombre, bytes)] shots por responder
        self.shots_tarde = []        # [(pagina, nombre, cuando_ms, intentos)] esperan render
        self.disparados = set()      # (paso, patron) ya disparados, para no repetir
        self.sin_reporte = False     # se paro pidiendo NO generar el reporte
        self.pend_req = {}           # request -> metadata, para casar con su response
        self.cola_fallos = []        # [(request, cuando_ms)] cortados por el navegador
        self.cdp_red = {}            # requestId CDP -> {url, metodo, status, headers, error}
        # (metodo, url) que Playwright SI emitio como 'request'. Lo que CDP vio
        # y no esta aqui es un huerfano: se registra desde CDP (drenar_huerfanos)
        self.pw_vistos = {}
        self.paso_por_pagina = {}    # pagina -> su paso actual (soporte multi-pestana)
        self.ids_pagina = {}         # pagina -> numero de pestana, para el reporte
        self.pagina_actual = None

    # -- endpoints de negocio
    def casar_endpoints(self, url):
        """Todos los patrones rastreados que casan con esta URL (pueden ser varios)."""
        return [e for e, rx in self.endpoints_rx if rx.search(url)]

    # -- filtro por destino (a que host va el request)
    def api_fuera_catalogo(self, url, tipo):
        """fetch/xhr a los hosts de la app que no esta en el catalogo.

        En modo endpoints solo se guarda el catalogo; pero si el front cambia
        la ruta de un servicio (otra version, un BFF propio en cloudfront) su
        fallo desaparecia sin rastro. Estos se siguen y se guardan SOLO si
        fallan (status >= 400, CORS o red cortada).
        """
        if not self.solo_endpoints or (tipo or "").lower() not in ("fetch", "xhr"):
            return False
        if not url.startswith("http"):
            return False
        return not self.hosts or va_a_hosts(url, self.hosts)

    def interesa(self, url):
        if not url.startswith("http"):
            return False
        if self.solo_endpoints:
            return bool(self.casar_endpoints(url))
        if not self.hosts:
            return True
        return va_a_hosts(url, self.hosts)

    # -- filtro por origen (de que pestana viene)
    def intentar_lock(self, page, url):
        """Engancha el candado a la primera pestana cuya URL case con el patron."""
        if self.lock is not None or not self.patrones:
            return False
        ruta = ruta_de(url)
        if not any(p in ruta for p in self.patrones):
            return False
        self.lock = page
        print("\n>> Pestana fijada: %s" % url)
        print(">> Se ignora todo lo que pase en las demas pestanas.\n")
        return True

    def pagina_permitida(self, page):
        if not self.patrones:
            return True              # sin --solo-url: todas las pestanas
        if self.lock is None:
            return False             # aun no encontramos la pestana objetivo
        return page is self.lock or (self.seguir_popups and page in self.hijas)

    # -- pasos
    def paso_actual(self):
        return self.pasos[-1] if self.pasos else None

    def id_pestana(self, page):
        if page not in self.ids_pagina:
            self.ids_pagina[page] = len(self.ids_pagina)
        return self.ids_pagina[page]

    def marcar_cambio(self, page, url, forzar=False):
        """Handler ligero: solo agenda. El screenshot lo toma el loop principal.

        Se agenda POR PAGINA: si hay varias pestanas abiertas, cada una lleva su
        propio hilo de pantallas y no se pisan entre si.

        forzar=True abre paso nuevo aunque la URL sea la misma: es lo que hace
        que una recarga (F5) quede como su propia evidencia.
        """
        if not es_url_real(url):
            return
        self.intentar_lock(page, url)      # quiza esta pestana es la que esperabamos
        if not self.pagina_permitida(page):
            return
        actual = self.paso_por_pagina.get(page)
        if not forzar and actual and actual["url"] == url and page not in self.pendientes:
            return
        self.pendientes[page] = (url, time.time() * 1000)

    def detectar_recarga(self, page, request):
        """Recarga = documento pedido de nuevo para la MISMA url del paso actual.

        Es la senal que separa un F5 de un cambio de ruta de la SPA: el pushState
        no pide documento, la recarga si. Sin esto marcar_cambio deduplica la
        recarga por URL repetida y la pantalla nueva nunca se captura.
        """
        try:
            if request.resource_type != "document" or request.frame != page.main_frame:
                return
            url = request.url
        except Exception:
            return
        actual = self.paso_por_pagina.get(page)
        if actual and actual["url"] == url and page not in self.pendientes:
            print("   (recarga de %s)" % url)
            self.marcar_cambio(page, url, forzar=True)

    def abrir_paso(self, page, url, shot_en=None):
        idx = len(self.pasos)
        slug = slug_de_url(url)
        d = os.path.join(self.dir, f"{idx:02d}_{slug}")
        os.makedirs(d, exist_ok=True)
        paso = {"idx": idx, "url": url, "slug": slug, "dir": d,
                "ts": ahora_iso(), "requests": [], "sockets": [], "titulo": "",
                "pestana": self.id_pestana(page)}
        self.pasos.append(paso)
        self.paso_por_pagina[page] = paso
        try:
            paso["titulo"] = page.title()
        except Exception:
            pass
        if shot_en is None:
            try:
                page.screenshot(path=os.path.join(d, "screenshot.png"), full_page=True)
            except Exception as e:
                print(f"  ! no pude capturar pantalla del paso {idx}: {e}")
        else:
            # el paso se abrio antes de tiempo para no perder trafico; el
            # screenshot igual espera a que la pantalla termine de pintar
            self.shots_dif.append((paso, page, shot_en))
        etiqueta = f" [pestana {paso['pestana']}]" if len(self.ids_pagina) > 1 else ""
        print(f"[paso {idx:02d}]{etiqueta} {url}")
        if any(pat in url for pat in self.pantallazo_extra):
            self.extras.append((paso, page, time.time() * 1000 + self.extra_ms))
            print(f"         -> pantallazo extra en {self.extra_ms} ms")
        if self.sonda and sonda_check.PANTALLA_CASO in url:
            # aqui el caso ya existe: es la segunda y ultima consulta
            self.sonda.pedir(paso, "informacion personal", una_vez=True)
        elif self.sonda and not self.sonda.motivos:
            # con --documento no hay "documento detectado": el inicio va aqui
            self.sonda.pedir(paso, "inicio", una_vez=True)
        return paso

    def tomar_extras(self, forzar=False):
        """Segundo pantallazo de las pantallas marcadas, ya con el contenido pintado."""
        ahora = time.time() * 1000
        quedan = []
        for paso, page, cuando in self.extras:
            if not forzar and ahora < cuando:
                quedan.append((paso, page, cuando))
                continue
            try:
                page.screenshot(path=os.path.join(paso["dir"], "screenshot_2.png"),
                                full_page=True)
                print(f"[paso {paso['idx']:02d}] pantallazo extra guardado")
            except Exception as e:
                print(f"  ! pantallazo extra del paso {paso['idx']} fallo: {e}")
        self.extras = quedan

    def tomar_shots_diferidos(self, forzar=False):
        """Screenshot de los pasos que se abrieron antes de cumplirse el settle."""
        ahora = time.time() * 1000
        quedan = []
        for paso, page, cuando in self.shots_dif:
            if not forzar and ahora < cuando:
                quedan.append((paso, page, cuando))
                continue
            try:
                page.screenshot(path=os.path.join(paso["dir"], "screenshot.png"),
                                full_page=True)
            except Exception as e:
                print(f"  ! no pude capturar pantalla del paso {paso['idx']}: {e}")
        self.shots_dif = quedan

    def adelantar_paso(self, pagina):
        """Abre ya el paso que esperaba el settle, para que el request caiga ahi."""
        url_nueva, t_cambio = self.pendientes.pop(pagina)
        try:
            url_real = pagina.url or url_nueva
        except Exception:
            url_real = url_nueva
        actual = self.paso_por_pagina.get(pagina)
        if actual and actual["url"] == url_real:
            return
        try:
            self.abrir_paso(pagina, url_real, shot_en=t_cambio + self.settle_ms)
        except Exception:
            pass

    def vaciar_pendientes(self):
        """Al cerrar, abrir los pasos que quedaron esperando el settle.

        Sin esto se pierde la ultima pantalla del flujo, que es justo la que
        importa (pantalla final / thank-you page) si das Ctrl+C apenas llegas.
        """
        for pagina, (url, _t0) in list(self.pendientes.items()):
            self.pendientes.pop(pagina, None)
            try:
                url_real = pagina.url
                actual = self.paso_por_pagina.get(pagina)
                if not actual or actual["url"] != url_real:
                    self.abrir_paso(pagina, url_real)
            except Exception:
                continue

    # -- red
    @staticmethod
    def pagina_de(request):
        """Pagina que origino el request (los de service worker no tienen frame)."""
        try:
            return request.frame.page
        except Exception:
            return None

    def descartar(self, request):
        """True si el request no pertenece a la pestana bajo observacion."""
        if not self.patrones:
            return False
        pagina = self.pagina_de(request)
        if pagina is None:
            # sin frame (service worker): no podemos saber de que pestana salio.
            # No lo inventamos: lo descartamos y lo contamos para avisarte al final.
            self.sin_pestana += 1
            return True
        return not self.pagina_permitida(pagina)

    def on_request(self, request):
        fuera = False
        if not self.interesa(request.url):
            if not self.api_fuera_catalogo(request.url, request.resource_type):
                return
            fuera = True
        # antes de descartar: lo que Playwright tira por ser de otra pestana
        # tampoco debe volver a entrar como huerfano de CDP
        clave = (request.method, request.url)
        self.pw_vistos[clave] = self.pw_vistos.get(clave, 0) + 1
        if self.descartar(request):
            return
        omitir = sin_payload(request.url)
        try:
            post = None if omitir else request.post_data
        except Exception:
            post = None
        self.pend_req[request] = {
            "ts": ahora_iso(),
            "t0": time.time(),
            "metodo": request.method,
            "url": request.url,
            "tipo": request.resource_type,
            # all_headers() aqui bloqueaba el handler hasta que el request
            # terminaba: lo que nunca respondia no llegaba a registrarse, y un
            # fallo CORS se avisaba antes de quedar en pend_req. Se piden al
            # registrar, desde el loop (ver registro).
            "request_headers": None,
            "request_body": post,
        }
        if fuera:
            self.pend_req[request]["fuera_catalogo"] = True

    def on_response(self, response):
        pagina = self.pagina_de(response.request)
        if self.patrones and not self.pagina_permitida(pagina):
            return
        # Antes del filtro de captura a proposito: hay disparadores que no son
        # endpoints rastreados (estado_civil), y en modo "endpoints" interesa()
        # los descartaria y el pantallazo no se tomaria nunca.
        self.mirar_disparadores(response, pagina)
        if not self.interesa(response.url):
            meta = self.pend_req.get(response.request)
            if meta is None or not meta.get("fuera_catalogo"):
                return
            if response.status < 400:
                self.pend_req.pop(response.request, None)   # fuera del catalogo y OK
                return
        if casan(ENDPOINTS_CUERPO_INMEDIATO, response.url):
            try:
                self.cuerpos[response] = response.body()
            except Exception:
                pass             # drenar_respuestas lo intenta otra vez y lo anota
        self.cola_resp.append(response)

    def mirar_disparadores(self, response, pagina):
        """Retrata la pantalla en el instante en que responde un servicio clave.

        Se dispara una sola vez por paso y por patron: el preflight OPTIONS y el
        POST de un mismo endpoint casan igual, y no hace falta el mismo
        pantallazo dos veces.
        """
        if not self.screenshot_on_response or pagina is None:
            return
        paso = self.paso_por_pagina.get(pagina)
        idx = paso["idx"] if paso else -1
        for patron in self.screenshot_on_response:
            if patron not in response.url:
                continue
            metodo = SHOT_TRAS_RECARGA.get(patron)
            if metodo and response.request.method != metodo:
                continue
            if (idx, patron) in self.disparados:
                continue
            self.disparados.add((idx, patron))
            slug = re.sub(r"[^A-Za-z0-9._-]+", "-", patron).strip("-")
            nombre = "screenshot_on_response_%s.png" % slug
            # Un documento acaba de llegar: la pagina todavia no pinto nada y
            # retratarla ahora daria una hoja en blanco. Los XHR si valen en el
            # instante, que es de lo que se trata: ver la pantalla con el dato
            # que acaba de responder.
            try:
                es_documento = response.request.resource_type == "document"
            except Exception:
                es_documento = False
            if es_documento or metodo:
                self.shots_tarde.append(
                    (pagina, nombre, time.time() * 1000 + self.settle_ms, 0))
                print("   [shot] %s %s; retrato cuando la pantalla se asiente"
                      % (patron, "cargo" if es_documento
                         else "respondio al " + metodo))
                continue
            try:
                self.shots_resp.append((pagina, nombre,
                                        pagina.screenshot(full_page=True,
                                                          timeout=5000)))
                print("   [shot] %s respondio; pantalla capturada" % patron)
            except Exception as e:
                # no se pierde: lo reintenta el loop (ver tomar_shots_tarde)
                self.shots_tarde.append(
                    (pagina, nombre, time.time() * 1000 + self.settle_ms, 1))
                print("! pantallazo al responder %s fallo (%s); reintento cuando "
                      "la pantalla se asiente" % (patron, type(e).__name__))

    def tomar_shots_tarde(self, forzar=False):
        """Retrata lo que espero a que la pagina pintara.

        Mientras la pestana tenga un cambio sin asentar (recarga, ruta nueva) se
        sigue esperando: un screenshot a mitad de navegacion se cuelga hasta el
        timeout. Si aun asi falla, se reintenta sin limite de tiempo hasta que
        salga o se cierre la pestana; al parar (forzar) va un ultimo intento.
        """
        ahora = time.time() * 1000
        quedan = []
        for pagina, nombre, cuando, intentos in self.shots_tarde:
            if not forzar and (ahora < cuando or pagina in self.pendientes):
                quedan.append((pagina, nombre, cuando, intentos))
                continue
            etiqueta = nombre[23:-4]
            try:
                self.shots_resp.append(
                    (pagina, nombre, pagina.screenshot(full_page=True,
                                                       timeout=5000)))
                if intentos:
                    print("   [shot] %s capturado al intento %d"
                          % (etiqueta, intentos + 1))
            except Exception as e:
                if forzar or pagina.is_closed():
                    print("! pantallazo de %s fallo: %s" % (etiqueta, e))
                    continue
                intentos += 1
                if intentos == 1:
                    print("   [shot] %s: la pantalla sigue cargando; reintento"
                          % etiqueta)
                espera = min(self.settle_ms * intentos, MAX_REINTENTO_SHOT_MS)
                quedan.append((pagina, nombre, time.time() * 1000 + espera,
                               intentos))
        self.shots_tarde = quedan

    def volcar_shots(self):
        """Escribe los pantallazos ya con el paso resuelto.

        Se hace desde el loop y despues de drenar respuestas, para que un
        request que adelanta de paso deje su pantallazo en el paso correcto.
        """
        if not self.shots_resp:
            return
        pendientes, self.shots_resp = self.shots_resp, []
        for pagina, nombre, datos in pendientes:
            paso = self.paso_por_pagina.get(pagina) or self.paso_actual()
            if paso is None:
                continue
            try:
                with open(os.path.join(paso["dir"], nombre), "wb") as f:
                    f.write(datos)
                print("[paso %02d] pantallazo al responder %s"
                      % (paso["idx"], nombre[23:-4]))
            except OSError as e:
                print("! no pude guardar %s: %s" % (nombre, e))

    def drenar_respuestas(self):
        """Lee los bodies en el loop principal, no dentro del handler."""
        # de a una: si un Ctrl+C corta a mitad, lo que falta sigue en la cola
        # y rescatar_en_vuelo lo registra con su status
        while self.cola_resp:
            response = self.cola_resp.pop(0)
            meta = self.pend_req.pop(response.request, None) or {
                "ts": ahora_iso(), "t0": time.time(), "metodo": response.request.method,
                "url": response.url, "tipo": response.request.resource_type,
                "request_headers": None, "request_body": None,
            }
            cuerpo, nota = None, None
            # un endpoint rastreado siempre conserva su cuerpo, sea del tipo que sea
            es_rastreado = bool(self.casar_endpoints(meta["url"]))
            if meta["tipo"] in TIPOS_SIN_CUERPO and not es_rastreado:
                nota = "cuerpo omitido (%s)" % meta["tipo"]
            else:
                try:
                    raw = self.cuerpos.pop(response, None)
                    if raw is None:
                        raw = response.body()
                    if len(raw) > MAX_BODY:
                        cuerpo = raw[:MAX_BODY].decode("utf-8", "replace")
                        nota = f"truncado en {MAX_BODY} bytes (real: {len(raw)})"
                    else:
                        cuerpo = raw.decode("utf-8", "replace")
                except Exception as e:
                    nota = f"body no disponible: {type(e).__name__}"
            try:
                resp_headers = response.all_headers()
            except Exception:
                resp_headers = {}

            reg = self.registro(meta, response.status, resp_headers, cuerpo, nota,
                                request=response.request)
            # se lee antes de redactar, sobre el body crudo
            doc_nuevo = bool(self.sonda) and self.sonda.aprender(meta["request_body"])
            doc_login = (bool(self.sonda) and bool(casan([LOGIN_GIGYA], meta["url"]))
                         and self.sonda.aprender_login(cuerpo))
            paso = self.guardar(reg, self.pagina_de(response.request),
                                t0_ms=meta["t0"] * 1000)
            if doc_login:
                # apenas se loguea: si no hay solicitud que retomar responde 404
                self.sonda.pedir(paso, "login", forzar=True)
            if doc_nuevo:
                # la pantalla donde aparecio el documento no alcanzo a consultarse
                self.sonda.pedir(paso, "documento detectado", forzar=True)

    def registro(self, meta, status, resp_headers, cuerpo, nota=None, fin=None,
                 request=None, al_cerrar=False):
        """La linea de evidencia de un request, ya marcada y redactada."""
        req_headers = meta["request_headers"]
        if req_headers is None:
            req_headers = cabeceras_request(request, completas=not al_cerrar)
        reg = {
            "ts": meta["ts"],
            "metodo": meta["metodo"],
            "url": meta["url"],
            "tipo": meta["tipo"],
            "status": status,
            "duracion_ms": round(((fin or time.time()) - meta["t0"]) * 1000),
            "request_headers": req_headers,
            "request_body": meta["request_body"],
            "response_headers": resp_headers,
            "response_body": cuerpo,
        }
        if sin_payload(meta["url"]):
            nota = ("payload omitido: lleva credenciales. " + (nota or "")).strip()
        if nota:
            reg["nota"] = nota
        if meta.get("fuera_catalogo"):
            reg["fuera_catalogo"] = True
            reg["nota"] = ("Fuera del catalogo de endpoints rastreados: se guarda "
                           "porque fallo. " + (nota or "")).strip()
        rastreados = self.casar_endpoints(meta["url"])
        if rastreados:
            reg["rastreados"] = rastreados
        if self.redactar:
            reg["request_headers"] = redactar_headers(reg["request_headers"])
            reg["response_headers"] = redactar_headers(reg["response_headers"])
            reg["request_body"] = redactar_body(reg["request_body"])
            reg["response_body"] = redactar_body(reg["response_body"])
        return reg

    # -- requests que nunca llegan a tener Response
    def on_request_failed(self, request):
        """El navegador corto el request: CORS, red caida, abortado.

        Playwright no emite 'response' para estos, asi que sin este handler
        desaparecian sin rastro. El caso tipico: un 404/500 que CloudFront
        contesta con su pagina de error HTML, sin Access-Control-Allow-Origin.
        El servidor SI respondio, pero Chrome no deja que el front la lea.
        """
        if request in self.pend_req:
            self.cola_fallos.append((request, time.time() * 1000))

    def enganchar_cdp(self, page):
        """Sesion CDP propia para saber que status tenia lo que se bloqueo.

        Un request bloqueado por CORS no tiene Response en Playwright, pero
        Chrome informa el status y las cabeceras reales en
        Network.responseReceivedExtraInfo: es lo que DevTools pinta como
        "404 Not Found" en una fila marcada "CORS error".
        """
        try:
            cdp = page.context.new_cdp_session(page)
            cdp.on("Network.requestWillBeSent",
                   lambda ev, _p=page, _s=cdp: self.cdp_request(ev, _p, _s))
            cdp.on("Network.responseReceived", self.cdp_respuesta)
            cdp.on("Network.responseReceivedExtraInfo", self.cdp_extra)
            cdp.on("Network.loadingFinished", self.cdp_fin)
            cdp.on("Network.loadingFailed", self.cdp_fallo)
            cdp.send("Network.enable")
        except Exception:
            pass   # sin CDP el fallo se registra igual, solo que sin status

    def cdp_request(self, ev, page=None, sesion=None):
        req = ev.get("request") or {}
        fuera = False
        if not self.interesa(req.get("url", "")):
            if not self.api_fuera_catalogo(req.get("url", ""), ev.get("type")):
                return
            fuera = True
        self.cdp_red[ev.get("requestId")] = {
            "fuera_catalogo": fuera,
            "url": req["url"], "metodo": req.get("method"),
            # lo que hace falta para registrarlo solo, si Playwright no lo ve
            "pagina": page, "sesion": sesion, "ts": ahora_iso(), "t0": time.time(),
            "tipo": (ev.get("type") or "").lower() or None,
            "req_headers": dict(req.get("headers") or {}),
            "post": None if sin_payload(req["url"]) else req.get("postData"),
        }
        while len(self.cdp_red) > MAX_CDP_RED:
            self.cdp_red.pop(next(iter(self.cdp_red)))

    def cdp_respuesta(self, ev):
        info = self.cdp_red.get(ev.get("requestId"))
        resp = ev.get("response") or {}
        if info is not None:
            info.setdefault("status", resp.get("status"))
            info.setdefault("headers", {k.lower(): v for k, v
                                        in (resp.get("headers") or {}).items()})

    def cdp_extra(self, ev):
        info = self.cdp_red.get(ev.get("requestId"))
        if info is not None:
            info["status"] = ev.get("statusCode")
            info["headers"] = {k.lower(): v for k, v in (ev.get("headers") or {}).items()}

    def cdp_fin(self, ev):
        info = self.cdp_red.get(ev.get("requestId"))
        if info is not None:
            info["fin"] = time.time()

    def cdp_fallo(self, ev):
        info = self.cdp_red.get(ev.get("requestId"))
        if info is not None:
            info["error"] = ev.get("errorText") or "fallo"
            info["cors"] = (ev.get("corsErrorStatus") or {}).get("corsError")
            info["fin"] = time.time()

    def _consumir_visto(self, info):
        """True si Playwright ya emitio este request (y lo descuenta)."""
        clave = (info.get("metodo"), info["url"])
        n = self.pw_vistos.get(clave, 0)
        if n <= 0:
            return False
        if n == 1:
            self.pw_vistos.pop(clave)
        else:
            self.pw_vistos[clave] = n - 1
        return True

    def info_cdp(self, metodo, url):
        """Lo que CDP vio del fallo de este metodo+URL (el mas viejo; se consume)."""
        for rid, info in self.cdp_red.items():
            if info["url"] == url and info.get("metodo") == metodo and "error" in info:
                self._consumir_visto(info)
                return self.cdp_red.pop(rid)
        return {}

    def drenar_huerfanos(self, forzar=False, al_cerrar=False):
        """Registra lo que Chrome vio y Playwright nunca reporto.

        Un POST con JSON lleva preflight OPTIONS; si el preflight falla (500 o
        sin Access-Control-Allow-Origin), Chrome corta el POST y DevTools lo
        pinta como "CORS error", pero Playwright puede no emitir ni 'request'
        ni 'requestfailed' para el: el request-data que fallaba desaparecia de
        la evidencia. La sesion CDP si lo ve, asi que se registra desde ahi.
        """
        ahora = time.time()
        for rid, info in list(self.cdp_red.items()):
            fin = info.get("fin")
            if fin is None and not forzar:
                continue                      # sigue en vuelo
            if fin is not None and not forzar and ahora - fin < ESPERA_HUERFANO_S:
                continue                      # da tiempo a que Playwright hable
            self.cdp_red.pop(rid, None)
            if self._consumir_visto(info):
                continue                      # Playwright ya lo registro
            pagina = info.get("pagina")
            if self.patrones and not self.pagina_permitida(pagina):
                continue
            status = info.get("status") or 0
            error = info.get("error")
            # Playwright nunca ve los preflight, y lo de fuera del catalogo
            # solo se guarda si fallo
            if (info.get("metodo") == "OPTIONS" or info.get("tipo") == "preflight"
                    or info.get("fuera_catalogo")) and not error and status < 400:
                continue
            headers = info.get("headers") or {}
            cuerpo = None
            if fin is not None and not error and not al_cerrar and info.get("sesion"):
                try:
                    r = info["sesion"].send("Network.getResponseBody", {"requestId": rid})
                    cuerpo = r.get("body")
                except Exception:
                    pass
            partes = ["Playwright no reporto este request; se registro desde la "
                      "sesion CDP de Chrome."]
            if info.get("metodo") == "OPTIONS":
                partes.append("Es el preflight CORS del request real: con este "
                              "status Chrome no llega a enviarlo.")
            if info.get("cors"):
                partes.append("Chrome lo bloqueo por CORS (%s): el servidor respondio "
                              "%s sin un Access-Control-Allow-Origin valido."
                              % (info["cors"], status or "?"))
            elif error:
                partes.append("El navegador corto el request (%s)%s."
                              % (error, ", status %s" % status if status else ""))
            elif fin is None:
                partes.append("Seguia en vuelo cuando se cerro el observador.")
            pistas = ["%s: %s" % (k, headers[k]) for k in ("x-cache", "content-type")
                      if headers.get(k)]
            if pistas:
                partes.append(" | ".join(pistas))
            meta = {"ts": info["ts"], "t0": info["t0"], "metodo": info.get("metodo"),
                    "url": info["url"], "tipo": info.get("tipo") or "fetch",
                    "request_headers": info.get("req_headers") or {},
                    "request_body": info.get("post"),
                    "fuera_catalogo": info.get("fuera_catalogo")}
            reg = self.registro(meta, status, headers, cuerpo, " ".join(partes),
                                fin=fin, al_cerrar=al_cerrar)
            reg["origen"] = "cdp"
            if error or fin is None:
                reg["fallo"] = error or SIN_RESPUESTA
            if info.get("cors"):
                reg["cors"] = info["cors"]
            self.guardar(reg, pagina, t0_ms=info["t0"] * 1000, al_cerrar=al_cerrar)
            print("   [x] %s %s -> %s %s (visto solo por CDP)"
                  % (meta["metodo"], meta["url"], status or "-",
                     "bloqueado por CORS" if info.get("cors") else (error or "")))

    def drenar_fallos(self, forzar=False, al_cerrar=False):
        """Registra los requests que el navegador corto, con el status real si
        el servidor alcanzo a responder."""
        ahora = time.time() * 1000
        quedan = []
        for request, cuando in self.cola_fallos:
            if not forzar and ahora - cuando < ESPERA_FALLO_MS:
                quedan.append((request, cuando))
                continue
            meta = self.pend_req.pop(request, None)
            if meta is None:
                continue
            info = self.info_cdp(meta["metodo"], meta["url"])
            status = info.get("status") or 0
            headers = info.get("headers") or {}
            error = request.failure or info.get("error") or "fallo"
            if info.get("cors"):
                nota = ("Chrome bloqueo la respuesta por CORS (%s): el servidor "
                        "respondio %s sin Access-Control-Allow-Origin valido, asi "
                        "que el front nunca la pudo leer." % (info["cors"], status or "?"))
            elif status:
                nota = "El servidor respondio %s, pero el navegador corto el request (%s)." % (status, error)
            else:
                nota = "El navegador corto el request sin respuesta del servidor (%s)." % error
            pistas = ["%s: %s" % (k, headers[k]) for k in ("x-cache", "content-type")
                      if headers.get(k)]
            if pistas:
                nota += " " + " | ".join(pistas)
            reg = self.registro(meta, status, headers, None, nota, fin=cuando / 1000,
                                request=request, al_cerrar=al_cerrar)
            reg["fallo"] = error
            if info.get("cors"):
                reg["cors"] = info["cors"]
            self.guardar(reg, self.pagina_de(request), t0_ms=meta["t0"] * 1000,
                         al_cerrar=al_cerrar)
            print("   [x] %s %s -> %s %s" % (meta["metodo"], meta["url"], status or "-",
                                            "bloqueado por CORS" if info.get("cors") else error))
        self.cola_fallos = quedan

    def esperar_en_vuelo(self, pagina, segundos):
        """Al parar, da tiempo a que respondan los requests que siguen en vuelo.

        Un request-data que tarda 12 s y se para la captura a los 5 quedaba
        fuera de la evidencia, aunque luego DevTools mostrara su 500.
        """
        limite = time.time() + segundos
        if self.pend_req and segundos > 0:
            print("Esperando %d request(s) en vuelo (max %d s):"
                  % (len(self.pend_req), segundos))
            for m in self.pend_req.values():
                print("   %s %s" % (m["metodo"], ruta_de(m["url"])))
        while (self.pend_req or self.huerfanos_en_vuelo()) and time.time() < limite:
            pagina.wait_for_timeout(200)
            self.drenar_respuestas()
            self.drenar_fallos()
            self.drenar_huerfanos()
        self.drenar_huerfanos(forzar=True)

    def huerfanos_en_vuelo(self):
        """Requests que solo CDP vio salir y que todavia no terminan."""
        return [i for i in self.cdp_red.values()
                if i.get("fin") is None and not i.get("fuera_catalogo")
                and not self.pw_vistos.get((i.get("metodo"), i["url"]))
                and i.get("metodo") != "OPTIONS"]

    def rescatar_en_vuelo(self):
        """Lo que no se pudo leer al cerrar igual queda en la evidencia, marcado.

        No toca Playwright (solo atributos ya cargados en Python): tambien lo
        llama el hilo vigilante cuando el loop se colgo.
        """
        pendientes, self.cola_resp = self.cola_resp, []
        for response in pendientes:
            meta = self.pend_req.pop(response.request, None)
            if meta is None:
                continue
            raw = self.cuerpos.pop(response, None)
            reg = self.registro(meta, response.status, {},
                                raw[:MAX_BODY].decode("utf-8", "replace") if raw else None,
                                None if raw else
                                "Respondio, pero el observador cerro antes de leer el cuerpo.",
                                request=response.request, al_cerrar=True)
            self.guardar(reg, self.pagina_de(response.request), al_cerrar=True)
        self.drenar_fallos(forzar=True, al_cerrar=True)
        self.drenar_huerfanos(forzar=True, al_cerrar=True)
        for request, meta in list(self.pend_req.items()):
            self.pend_req.pop(request, None)
            reg = self.registro(meta, 0, {}, None,
                                "Seguia en vuelo cuando se cerro el observador: no se "
                                "alcanzo a ver su respuesta.",
                                request=request, al_cerrar=True)
            reg["fallo"] = SIN_RESPUESTA
            self.guardar(reg, self.pagina_de(request), al_cerrar=True)
            print("   [x] %s %s -> sin respuesta al cerrar" % (meta["metodo"], meta["url"]))

    def volcar_sonda(self):
        """Escribe lo que respondio /request/check en el paso que lo pidio.

        Desde el loop, igual que el resto de la evidencia: el hilo de la sonda
        solo hace la llamada HTTP.
        """
        if not self.sonda:
            return
        for paso, reg in self.sonda.recoger():
            paso["requests"].append(reg)
            with open(os.path.join(paso["dir"], "requests.jsonl"), "a",
                      encoding="utf-8") as f:
                f.write(json.dumps(reg, ensure_ascii=False) + "\n")
            print("[paso %02d] /request/check (%s) -> %s  %s  [%d ms]"
                  % (paso["idx"], reg["motivo"], reg["status"],
                     sonda_check.linea(reg["check"]), reg["duracion_ms"]))

    def enganchar_socket(self, pagina, ws):
        """Los frames del socket son evidencia de primera: llevan el avance del
        flujo (step / stepStatus), que no viaja por HTTP.

        No se les aplica el filtro de hosts ni el de endpoints: son pocos, van
        a un dominio distinto al del backend (API Gateway) y perderlos deja el
        reporte sin la mitad de la historia.
        """
        if self.patrones and not self.pagina_permitida(pagina):
            return
        print("   [ws] abierto %s" % ws.url)
        ws.on("framesent",
              lambda datos: self.guardar_frame(pagina, ws, "enviado", datos))
        ws.on("framereceived",
              lambda datos: self.guardar_frame(pagina, ws, "recibido", datos))
        ws.on("close", lambda _ws=ws: print("   [ws] cerrado %s" % _ws.url))

    def guardar_frame(self, pagina, ws, direccion, datos):
        """Un frame cae en el paso que estuviera abierto en esa pestana."""
        if isinstance(datos, (bytes, bytearray)):
            texto = datos.decode("utf-8", "replace")
        else:
            texto = str(datos)
        if len(texto) > MAX_BODY:
            texto = texto[:MAX_BODY]
        if self.redactar:
            texto = redactar_body(texto)
        frame = {"ts": ahora_iso(), "direccion": direccion, "url": ws.url,
                 "payload": texto}
        paso = self.paso_por_pagina.get(pagina) or self.paso_actual()
        if paso is None:
            return
        paso.setdefault("sockets", []).append(frame)
        with open(os.path.join(paso["dir"], "websocket.jsonl"), "a",
                  encoding="utf-8") as f:
            f.write(json.dumps(frame, ensure_ascii=False) + "\n")
        flecha = "->" if direccion == "enviado" else "<-"
        # el payload cortado a lo bruto tapaba justo step/stepStatus, que es lo
        # unico que se mira en vivo; el JSON completo queda en el .jsonl
        resumen = None
        try:
            d = json.loads(texto)
            if isinstance(d, dict) and d.get("step"):
                resumen = "%-14s %s" % (d["step"], d.get("stepStatus", ""))
                if d.get("idCase"):
                    resumen += "  (caso %s)" % d["idCase"]
        except (json.JSONDecodeError, TypeError):
            pass
        print("   [ws %s] %s" % (flecha, resumen or texto[:120]))

    def guardar(self, reg, pagina=None, t0_ms=None, al_cerrar=False):
        # Si la ruta de esta pestana ya cambio y el paso nuevo sigue esperando el
        # settle, el request es de la pantalla NUEVA: el settle existe para que la
        # pantalla pinte antes del screenshot, no para agrupar el trafico.
        # al_cerrar=True no abre pasos: eso toca Playwright, y al cerrar puede
        # estar colgado (o hablarse desde el hilo vigilante).
        if not al_cerrar and pagina is not None and pagina in self.pendientes:
            _url, t_cambio = self.pendientes[pagina]
            if t0_ms is None or t0_ms >= t_cambio - TOLERANCIA_CAMBIO_MS:
                self.adelantar_paso(pagina)
        # el request va al paso de SU pestana, no al ultimo paso global
        paso = self.paso_por_pagina.get(pagina) if pagina is not None else None
        if paso is None:
            paso = self.paso_actual()
        if paso is None:
            # llego trafico antes de la primera pantalla: abrimos paso al vuelo
            # para no perderlo (se corre desde el loop principal, es seguro)
            pag = pagina or self.pagina_actual
            if pag is None or al_cerrar:
                return None
            try:
                paso = self.abrir_paso(pag, pag.url)
            except Exception:
                return None
        paso["requests"].append(reg)
        # append inmediato: si matan el proceso, la evidencia ya esta en disco
        with open(os.path.join(paso["dir"], "requests.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(reg, ensure_ascii=False) + "\n")
        return paso

    # -- enganche a una pagina
    def registrar_hija(self, madre, hija):
        """La pestana observada abrio otra. Solo la seguimos si lo pediste."""
        if self.lock is not None and madre is self.lock:
            self.hijas.add(hija)
            if self.seguir_popups:
                print(">> La pestana observada abrio otra; la sigo tambien.")
            else:
                print(">> La pestana observada abrio otra; la IGNORO "
                      "(usa --seguir-popups si la necesitas).")

    def enganchar(self, page):
        if page in self.ids_pagina:
            return  # ya enganchada
        self.id_pestana(page)
        page.on("request", self.on_request)
        page.on("request", lambda req, _p=page: self.detectar_recarga(_p, req))
        page.on("response", self.on_response)
        page.on("requestfailed", self.on_request_failed)
        self.enganchar_cdp(page)
        page.on("framenavigated",
                lambda fr: self.marcar_cambio(page, fr.url) if fr == page.main_frame else None)
        page.on("close", lambda _p=page: self.pendientes.pop(_p, None))
        # una pestana abierta POR la observada (popup de biometria, OAuth, etc.)
        page.on("popup", lambda hija, _p=page: self.registrar_hija(_p, hija))
        page.on("websocket", lambda ws, _p=page: self.enganchar_socket(_p, ws))
        try:
            # expose_binding (no expose_function) para saber DESDE QUE pestana llego
            page.expose_binding("__obsRuta",
                                lambda source, url: self.marcar_cambio(source["page"], url))
        except Exception:
            pass  # ya estaba expuesta en esta pagina
        try:
            page.add_init_script(JS_HOOK_RUTA)   # documentos futuros
            page.evaluate(JS_HOOK_RUTA)          # documento actual
        except Exception:
            pass
        self.pagina_actual = page


# --- salidas ---------------------------------------------------------------
def escribir_har(obs, ruta):
    """HAR 1.2 derivado de lo capturado (no es el HAR nativo de Chrome)."""
    entradas = []
    for paso in obs.pasos:
        for r in paso["requests"]:
            entrada = {
                "startedDateTime": r["ts"],
                "time": r["duracion_ms"],
                "_paso": paso["idx"],
                "request": {
                    "method": r["metodo"],
                    "url": r["url"],
                    "httpVersion": "HTTP/1.1",
                    "headers": [{"name": k, "value": v}
                                for k, v in r["request_headers"].items()],
                    "queryString": [],
                    "cookies": [],
                    "headersSize": -1,
                    "bodySize": len(r["request_body"] or ""),
                },
                "response": {
                    "status": r["status"],
                    "statusText": "",
                    "httpVersion": "HTTP/1.1",
                    "headers": [{"name": k, "value": v}
                                for k, v in r["response_headers"].items()],
                    "cookies": [],
                    "redirectURL": "",
                    "headersSize": -1,
                    "bodySize": len(r["response_body"] or ""),
                    "content": {
                        "size": len(r["response_body"] or ""),
                        "mimeType": r["response_headers"].get("content-type", ""),
                        "text": r["response_body"],
                    },
                },
                "cache": {},
                "timings": {"send": 0, "wait": r["duracion_ms"], "receive": 0},
            }
            if r["request_body"]:
                entrada["request"]["postData"] = {
                    "mimeType": r["request_headers"].get("content-type", ""),
                    "text": r["request_body"],
                }
            if r.get("fallo"):
                entrada["_error"] = r["fallo"]   # el mismo campo que usa el HAR de Chrome
            entradas.append(entrada)
    har = {"log": {"version": "1.2",
                   "creator": {"name": "observador_flujo.py", "version": "1.0"},
                   "entries": entradas}}
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(har, f, ensure_ascii=False, indent=2)


CSS_REPORTE = """
  :root { --bg:#fff; --fg:#1a1a1a; --mut:#666; --bd:#e2e2e2; --card:#fafafa;
          --ok:#2e7d32; --err:#c62828; --acc:#CE4F3B; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#161616; --fg:#e8e8e8; --mut:#999; --bd:#333; --card:#1e1e1e;
            --ok:#81c784; --err:#ef9a9a; } }
  * { box-sizing:border-box; }
  body { margin:0; padding:24px; background:var(--bg); color:var(--fg);
         font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif; }
  header { border-bottom:3px solid var(--acc); padding-bottom:12px; margin-bottom:24px; }
  h1 { margin:0 0 4px; font-size:20px; }
  .resumen { color:var(--mut); font-size:13px; }
  .paso { display:flex; gap:20px; padding:20px 0; border-bottom:1px solid var(--bd);
          align-items:flex-start; }
  .shot { flex:0 0 300px; }
  .shot img { width:100%; border:1px solid var(--bd); border-radius:6px; }
  .info { flex:1; min-width:0; }
  .info h2 { margin:0 0 4px; font-size:16px; }
  .idx { background:var(--acc); color:#fff; padding:1px 7px; border-radius:4px;
         font-size:12px; margin-right:6px; }
  .url { margin:0 0 2px; color:var(--mut); font-size:12px; word-break:break-all; }
  .meta { margin:0 0 12px; color:var(--mut); font-size:12px; }
  .vacio { color:var(--mut); font-style:italic; }
  .req { background:var(--card); border:1px solid var(--bd); border-left:3px solid var(--ok);
         border-radius:4px; margin-bottom:6px; }
  .req.err { border-left-color:var(--err); }
  summary { cursor:pointer; padding:7px 10px; display:flex; gap:10px; align-items:center;
            font-size:12px; }
  .m { font-weight:700; min-width:52px; }
  .s { font-weight:700; min-width:34px; }
  .req.err .s { color:var(--err); }
  .req.ok .s { color:var(--ok); }
  .u { flex:1; word-break:break-all; font-family:ui-monospace,Consolas,monospace; }
  .d { color:var(--mut); white-space:nowrap; }
  .det { padding:0 12px 12px; }
  .det h5 { margin:10px 0 4px; font-size:11px; text-transform:uppercase; color:var(--mut); }
  pre { background:var(--bg); border:1px solid var(--bd); border-radius:4px; padding:8px;
        overflow-x:auto; font-size:11px; max-height:320px; margin:0; }
  .nota { color:var(--err); font-size:12px; }
  .ws { background:var(--card); border:1px solid var(--bd); border-left:3px solid var(--acc);
        border-radius:4px; margin-bottom:6px; }
  .ws summary { font-size:12px; }
  .ws .dir { font-weight:700; min-width:20px; }
  .ws .paso-st { font-weight:700; }
  .ws.fail { border-left-color:var(--err); }
  .ws.fail .paso-st { color:var(--err); }
  .ws.okk .paso-st { color:var(--ok); }
  .subt { margin:14px 0 6px; font-size:11px; text-transform:uppercase;
          color:var(--mut); letter-spacing:.4px; }
  .shot .cap { font-size:10px; color:var(--mut); margin:2px 0 0; }
  .shot img + a img { margin-top:6px; }
"""


def _bloque_endpoints(cob, esc):
    """Indice de endpoints rastreados para la cabecera del reporte."""
    if not cob:
        return ""
    vistos = sorted([c for c in cob.values() if c["veces"]], key=lambda x: -x["veces"])
    faltan = [c for c in cob.values() if not c["veces"]]
    filas = []
    for c in vistos:
        cls = "malo" if endpoint_con_error(c) else "bueno"
        # una version distinta a la declarada no es un fallo, pero hay que verla
        esperado = c.get("version_declarada")
        movida = bool(esperado and c.get("versiones") and esperado not in c["versiones"])
        filas.append(
            '<tr class="' + cls + '">'
            '<td class="n">' + esc(c["veces"]) + '&times;</td>'
            '<td class="e">' + esc(c["endpoint"]) + '</td>'
            '<td class="ver' + (' movida' if movida else '') + '">'
            + esc(nota_version(c)) + '</td>'
            '<td class="p">paso ' + esc(", ".join(str(p) for p in c["pasos"])) + '</td>'
            '<td class="st">' + esc(", ".join(str(s) if s else "-" for s in c["statuses"]))
            + ((' &middot; ' + esc(c["fallos"]) + ' bloqueado(s)/sin respuesta')
               if c.get("fallos") else '') + '</td>'
            '</tr>')
    for c in faltan:
        filas.append(
            '<tr class="ausente">'
            '<td class="n">&mdash;</td>'
            '<td class="e">' + esc(c["endpoint"]) + '</td>'
            '<td class="p" colspan="3">no aparecio</td>'
            '</tr>')
    return ('<section class="idx-ep"><h3>Endpoints rastreados '
            '<small>' + esc(len(vistos)) + ' de ' + esc(len(cob)) + '</small></h3>'
            '<table>' + "".join(filas) + '</table></section>')


CSS_ENDPOINTS = """
  .idx-ep { margin-bottom:24px; }
  .idx-ep h3 { font-size:14px; margin:0 0 8px; }
  .idx-ep h3 small { color:var(--mut); font-weight:400; margin-left:6px; }
  .idx-ep table { border-collapse:collapse; width:100%; font-size:12px; }
  .idx-ep td { padding:4px 8px; border-bottom:1px solid var(--bd); }
  .idx-ep .n { width:44px; text-align:right; font-weight:700; }
  .idx-ep .e { font-family:ui-monospace,Consolas,monospace; word-break:break-all; }
  .idx-ep .p, .idx-ep .st { color:var(--mut); white-space:nowrap; width:1%; }
  .idx-ep .ver { color:var(--mut); white-space:nowrap; width:1%; font-size:11px; }
  .idx-ep .ver.movida { color:var(--acc); font-weight:700; }
  .idx-ep tr.bueno .n { color:var(--ok); }
  .idx-ep tr.malo .n, .idx-ep tr.malo .st { color:var(--err); font-weight:700; }
  .idx-ep tr.ausente td { color:var(--mut); opacity:.65; }
  .tag { background:var(--acc); color:#fff; font-size:9px; font-weight:700;
         padding:1px 5px; border-radius:3px; letter-spacing:.4px; }
  .req.track { border-left-width:5px; }
  .req.track summary { background:color-mix(in srgb, var(--acc) 7%, transparent); }
  .tag.sonda { background:var(--mut); }
  .tag.fallo { background:var(--err); }
  .req.sonda { border-left:3px dashed var(--mut); }
  .req.sonda .s { color:var(--mut); }
  .nota-sonda { color:var(--mut); font-size:12px; }
  .idx-ep tr.cambio td { font-weight:700; }
  .idx-ep tr.cambio .e { color:var(--acc); }
"""


def es_fallo(r):
    """Status >= 400, o el navegador lo corto (CORS, red) / quedo sin respuesta."""
    return (r["status"] >= 400 or bool(r.get("fallo"))) and not r.get("sonda")


def etiqueta_fallo(r):
    """Marca corta para un request que el front nunca pudo leer."""
    fallo = r.get("fallo")
    if not fallo:
        return ""
    if r.get("cors"):
        return "CORS"
    if fallo == SIN_RESPUESTA:
        return "SIN RESPUESTA"
    if "ABORTED" in fallo.upper():
        return "ABORTADO"
    return "FALLO RED"


def endpoint_con_error(c):
    return any(not s or s >= 400 for s in c["statuses"]) or bool(c.get("fallos"))


def linea_check(pasos):
    """Las respuestas de /request/check en orden: la historia del caso."""
    filas = []
    for paso in pasos:
        for r in paso["requests"]:
            if r.get("sonda") != "request/check":
                continue
            filas.append(dict(r.get("check") or {}, paso=paso["idx"],
                              pantalla=paso["url"], motivo=r.get("motivo"),
                              status=r["status"], ts=r["ts"]))
    return sorted(filas, key=lambda f: f["ts"])


def _bloque_check(filas, esc):
    """Lo que habria respondido la retoma en cada pantalla. Se resaltan las
    filas donde cambio el estado o el paso pendiente, que es lo que se busca."""
    if not filas:
        return ""
    trs, previa = [], None
    for f in filas:
        clave = (f.get("estado"), f.get("pasoPendiente"), f.get("idCaso"))
        cls = "cambio" if previa is not None and clave != previa else ""
        previa = clave
        trs.append(
            '<tr class="' + cls + '">'
            '<td class="p">paso ' + esc("%02d" % f["paso"]) + '</td>'
            '<td class="p">' + esc(f["ts"][11:19]) + '</td>'
            '<td class="p">' + esc(f.get("motivo")) + '</td>'
            '<td class="st">' + esc(f["status"]) + '</td>'
            '<td class="e">' + esc(f.get("estado", "")) + '</td>'
            '<td class="e">' + esc(f.get("pasoPendiente", "")) + '</td>'
            '<td class="p">' + esc(("caso %s" % f["idCaso"]) if f.get("idCaso") else "")
            + '</td></tr>')
    return ('<section class="idx-ep"><h3>/request/check durante el flujo '
            '<small>lo que responderia la retoma en cada pantalla</small></h3>'
            '<table>' + "".join(trs) + '</table></section>')

def _rango_disparador(nombre):
    """Ordena los pantallazos por el orden en que se declaro cada disparador.

    Alfabeticamente, modification-quota-amount le ganaba a request/offer y
    quedaba de principal una pantalla que no es la que retrata el paso.
    """
    slug = nombre[len("screenshot_on_response_"):-len(".png")]
    patrones = [re.sub(r"[^A-Za-z0-9._-]+", "-", x).strip("-")
                for x in SHOT_RESPUESTA_DEFAULT.split(",")]
    return (patrones.index(slug) if slug in patrones else len(patrones), slug)


def _bloque_socket(frames, esc, esc_cuerpo):
    """Los frames del websocket del paso, con el step/stepStatus a la vista.

    Ese par es lo que dice si el flujo avanzo o se cayo, asi que se saca del
    payload y se pinta en el encabezado en vez de esconderlo en el JSON.
    """
    if not frames:
        return ""
    filas = []
    for fr in frames:
        paso_ws = est = ""
        try:
            d = json.loads(fr["payload"])
            paso_ws, est = d.get("step", ""), d.get("stepStatus", "")
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
        cls = "fail" if est.upper() in ("FAIL", "ERROR") else ("okk" if est else "")
        flecha = "&rarr;" if fr["direccion"] == "enviado" else "&larr;"
        etiqueta = (esc(paso_ws) + " " + esc(est)) if paso_ws else esc(fr["direccion"])
        filas.append(
            '<details class="ws ' + cls + '"><summary>'
            '<span class="dir">' + flecha + '</span>'
            '<span class="paso-st">' + etiqueta + '</span>'
            '<span class="d">' + esc(fr["ts"][11:19]) + '</span>'
            '</summary><div class="det"><pre>' + esc_cuerpo(fr["payload"]) + '</pre>'
            '<h5>Socket</h5><pre>' + esc(fr["url"]) + '</pre></div></details>')
    return '<p class="subt">WebSocket (' + esc(len(frames)) + ' mensajes)</p>' + "".join(filas)


def escribir_reporte(obs, flujo, ruta):
    import html as _h

    def esc(x):
        return _h.escape(str(x) if x is not None else "")

    def esc_cuerpo(txt):
        """El cuerpo completo vive en requests.jsonl; aqui solo un extracto.
        Si es JSON, lo formatea con indentacion; si no, lo deja como texto."""
        if not txt:
            return "(vacio)"
        # intentar parsear como JSON y formatear
        try:
            obj = json.loads(txt)
            formateado = json.dumps(obj, indent=2, ensure_ascii=False)
            txt_fmt = formateado
        except (json.JSONDecodeError, TypeError):
            txt_fmt = txt
        # truncar si es muy grande
        if len(txt_fmt) > MAX_BODY_HTML:
            return (_h.escape(txt_fmt[:MAX_BODY_HTML])
                    + "\n\n... [%d caracteres mas; el cuerpo completo esta en "
                      "requests.jsonl de este paso]" % (len(txt_fmt) - MAX_BODY_HTML))
        return _h.escape(txt_fmt)

    # la sonda no es trafico del front: ni se cuenta como capturado ni su 404
    # (sin caso abierto) como fallo
    total = sum(1 for p in obs.pasos for r in p["requests"] if not r.get("sonda"))
    fallos = sum(1 for p in obs.pasos for r in p["requests"] if es_fallo(r))
    n_sonda = len(linea_check(obs.pasos))
    multi = len({p.get("pestana", 0) for p in obs.pasos}) > 1

    secciones = []
    for paso in obs.pasos:
        reqs = []
        for r in paso["requests"]:
            clase = "err" if es_fallo(r) else "ok"
            nota = ("<p class='nota'>" + esc(r["nota"]) + "</p>") if r.get("nota") else ""
            tag = '<span class="tag">API</span>' if r.get("rastreados") else ''
            if r.get("rastreados"):
                clase += " track"
            if r.get("fallo"):
                tag += '<span class="tag fallo">' + esc(etiqueta_fallo(r)) + '</span>'
            if r.get("sonda"):
                clase = "sonda"
                tag = '<span class="tag sonda">SONDA</span>'
                nota = ("<p class='nota-sonda'>" + esc(sonda_check.linea(r.get("check") or {}))
                        + " &middot; consultado por el observador (" + esc(r.get("motivo"))
                        + "); el front lo llama desde su servidor, no desde el navegador.</p>")
            cuerpo_resp = esc_cuerpo(r["response_body"])
            if r.get("sonda") and r["response_body"] is None:
                cuerpo_resp = "null"   # un 404 sin caso: no hay cuerpo que mostrar
            reqs.append(
                '<details class="req ' + clase + '">'
                '<summary>' + tag +
                '<span class="m">' + esc(r["metodo"]) + '</span>'
                '<span class="s">' + (esc(r["status"]) if r["status"] else "&mdash;") + '</span>'
                '<span class="u">' + esc(r["url"]) + '</span>'
                '<span class="d">' + esc(r["duracion_ms"]) + ' ms</span>'
                '</summary>'
                '<div class="det">'
                '<h5>Request body</h5><pre>' + esc_cuerpo(r["request_body"]) + '</pre>'
                '<h5>Response body</h5><pre>' + cuerpo_resp + '</pre>'
                + nota +
                '</div></details>'
            )
        # imagenes del paso: el pantallazo disparado por la respuesta del
        # servicio manda (es el estado real de la pantalla con datos), y el
        # de la navegacion queda abajo como referencia.
        base = "%02d_%s/" % (paso["idx"], paso["slug"])
        onresp = sorted((f for f in os.listdir(paso["dir"])
                         if f.startswith("screenshot_on_response_")
                         and f.endswith(".png")), key=_rango_disparador)                  if os.path.isdir(paso["dir"]) else []
        imgs = [(base + f, "al responder " + f[23:-4].replace("-", "/")) for f in onresp]
        if os.path.exists(os.path.join(paso["dir"], "screenshot.png")):
            imgs.append((base + "screenshot.png", "al entrar a la pantalla"))
        if os.path.exists(os.path.join(paso["dir"], "screenshot_2.png")):
            imgs.append((base + "screenshot_2.png", "pantallazo extra (mas tarde)"))
        shot = esc(imgs[0][0]) if imgs else ""
        shot2 = "".join(
            '<a href="' + esc(src_) + '" target="_blank">'
            '<img src="' + esc(src_) + '" alt="' + esc(cap) + '"></a>'
            '<p class="cap">' + esc(cap) + '</p>'
            for src_, cap in imgs[1:])
        cuerpo = "".join(reqs) or '<p class="vacio">Sin requests al backend en este paso.</p>'
        cuerpo += _bloque_socket(paso.get("sockets") or [], esc, esc_cuerpo)
        secciones.append(
            '<section class="paso">'
            '<div class="shot">'
            + (('<a href="' + shot + '" target="_blank">'
                '<img src="' + shot + '" alt="paso ' + esc(paso["idx"]) + '"></a>'
                '<p class="cap">' + esc(imgs[0][1]) + '</p>') if shot else '')
            + shot2 + '</div>'
            '<div class="info">'
            '<h2><span class="idx">' + ("%02d" % paso["idx"]) + '</span> '
            + esc(paso["titulo"] or paso["slug"]) + '</h2>'
            '<p class="url">' + esc(paso["url"]) + '</p>'
            '<p class="meta">' + esc(len(paso["requests"])) + ' request(s) &middot; '
            + ('pestana ' + esc(paso.get("pestana", 0)) + ' &middot; ' if multi else '')
            + esc(paso["ts"]) + '</p>'
            + cuerpo +
            '</div></section>'
        )

    doc = (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Evidencia - ' + esc(flujo) + '</title>'
        '<style>' + CSS_REPORTE + CSS_ENDPOINTS + esq.CSS + '</style></head><body>'
        '<header><h1>Evidencia de flujo &mdash; ' + esc(flujo) + '</h1>'
        '<p class="resumen">' + esc(len(obs.pasos)) + ' pasos &middot; '
        + esc(total) + ' requests capturados &middot; '
        + esc(fallos) + ' con error (status &ge; 400, CORS o sin respuesta) &middot; '
        + ((esc(n_sonda) + ' consultas a /request/check &middot; ') if n_sonda else '')
        + 'generado ' + esc(ahora_iso()) + '</p>'
        '</header>'
        + esq.bloque_html(getattr(obs, "validacion", []),
                          getattr(obs, "ruta_esquemas", None), esc)
        + _bloque_endpoints(cobertura_endpoints(obs.pasos, obs.endpoints), esc)
        + _bloque_check(linea_check(obs.pasos), esc)
        + "".join(secciones) + '</body></html>'
    )
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(doc)


def _quizas_json(txt):
    """Deja el cuerpo como objeto si es JSON; si no, como texto tal cual."""
    if not txt:
        return None
    try:
        return json.loads(txt)
    except (json.JSONDecodeError, TypeError):
        return txt


def cobertura_endpoints(pasos, endpoints):
    """Por cada endpoint rastreado: cuantas veces salio, en que pasos y con que status.

    Es lo que responde "el flujo si llamo a decision-engine?" de un vistazo,
    incluyendo los que NUNCA se vieron (que suele ser el hallazgo interesante).
    """
    cob = {e: {"endpoint": e, "veces": 0, "pasos": [], "statuses": [], "urls": [],
               "version_declarada": version_declarada(e), "versiones": [], "fallos": 0}
           for e in endpoints}
    for paso in pasos:
        for r in paso["requests"]:
            for e in r.get("rastreados", []):
                if e not in cob:
                    continue
                c = cob[e]
                c["veces"] += 1
                if paso["idx"] not in c["pasos"]:
                    c["pasos"].append(paso["idx"])
                if r["status"] not in c["statuses"]:
                    c["statuses"].append(r["status"])
                if r.get("fallo"):
                    c["fallos"] += 1
                if len(c["urls"]) < 5 and r["url"] not in c["urls"]:
                    c["urls"].append(r["url"])
                v = version_de(r["url"])
                if v and v not in c["versiones"]:
                    c["versiones"].append(v)
    return cob


def nota_version(c):
    """'v2 (declarado v1)' cuando la version que llego no es la esperada."""
    if not c["versiones"]:
        return ""
    visto = "/".join("v" + v for v in c["versiones"])
    esperado = c["version_declarada"]
    if esperado and esperado not in c["versiones"]:
        return "%s  <-- declarado v%s" % (visto, esperado)
    return visto


def imprimir_cobertura(cob):
    vistos = [c for c in cob.values() if c["veces"]]
    faltantes = [c for c in cob.values() if not c["veces"]]
    if not cob:
        return
    print("\n--- endpoints rastreados ---")
    for c in sorted(vistos, key=lambda x: -x["veces"]):
        malos = [s for s in c["statuses"] if not s or s >= 400]
        marca = "  <-- %s" % malos if malos else ""
        if c.get("fallos"):
            marca += "  <-- %d bloqueado(s)/sin respuesta" % c["fallos"]
        ver = nota_version(c)
        print("  %2dx  pasos %-12s %-58s %s%s"
              % (c["veces"], ",".join(str(p) for p in c["pasos"]), c["endpoint"],
                 ver, marca))
    if faltantes:
        print("  no aparecieron (%d):" % len(faltantes))
        for c in faltantes:
            print("       %s" % c["endpoint"])

_CERRANDO = threading.Lock()
_CERRADO = [False]


def cerrar(obs, flujo, ruta_esquemas=None, generar=False):
    with _CERRANDO:
        if _CERRADO[0]:
            return
        _CERRADO[0] = True
    return _cerrar(obs, flujo, ruta_esquemas, generar)


def _cerrar(obs, flujo, ruta_esquemas=None, generar=False):
    # Los pantallazos por respuesta se capturan en el handler y se escriben
    # desde el loop; si el loop se colgo siguen en memoria. Volcarlos aqui es
    # lo unico que los salva, y no toca Playwright, asi que es seguro incluso
    # desde el hilo vigilante.
    try:
        obs.volcar_shots()
    except (AttributeError, OSError):
        pass
    try:
        obs.rescatar_en_vuelo()  # idem con los requests que no alcanzaron a leerse
    except (AttributeError, OSError):
        pass
    try:
        obs.volcar_sonda()       # idem con lo que alcanzo a responder /request/check
    except (AttributeError, OSError):
        pass
    resumen = {
        "flujo": flujo,
        "generado": ahora_iso(),
        "pasos": [{"idx": p["idx"], "url": p["url"], "titulo": p["titulo"], "ts": p["ts"],
                   "pestana": p.get("pestana", 0), "requests": len(p["requests"]),
                   "websocket": len(p.get("sockets") or []),
                   "fallos": sum(1 for r in p["requests"] if es_fallo(r))}
                  for p in obs.pasos],
    }
    checks = linea_check(obs.pasos)
    if checks:
        resumen["request_check"] = checks
        with open(os.path.join(obs.dir, "request_check.json"), "w", encoding="utf-8") as f:
            json.dump(checks, f, ensure_ascii=False, indent=2)
    cob = cobertura_endpoints(obs.pasos, obs.endpoints)
    resumen["endpoints"] = cob
    with open(os.path.join(obs.dir, "resumen.json"), "w", encoding="utf-8") as f:
        json.dump(resumen, f, ensure_ascii=False, indent=2)
    with open(os.path.join(obs.dir, "endpoints.json"), "w", encoding="utf-8") as f:
        json.dump(cob, f, ensure_ascii=False, indent=2)

    # servicios.json: la llamada a llamada de los endpoints de negocio, en orden,
    # con payload y respuesta. Es el archivo que se lee para verificar el flujo.
    servicios = []
    for paso in obs.pasos:
        for r in paso["requests"]:
            if not r.get("rastreados"):
                continue
            llamada = {"method": r["metodo"], "status": r["status"],
                       "duracion_ms": r["duracion_ms"]}
            if r.get("fallo"):
                llamada["fallo"] = r["fallo"]
                if r.get("cors"):
                    llamada["cors"] = r["cors"]
            servicios.append({
                "url": r["url"],
                "request": llamada,
                "payload": _quizas_json(r.get("request_body")),
                "contexto": {
                    "paso": paso["idx"],
                    "pantalla": paso["url"],
                    "endpoint": r["rastreados"][0],
                    "timestamp": r["ts"],
                }
            })
    with open(os.path.join(obs.dir, "servicios.json"), "w", encoding="utf-8") as f:
        json.dump(servicios, f, ensure_ascii=False, indent=2)

    # esquemas: el contrato que se observo en ESTA corrida queda siempre en la
    # evidencia; el soft assert solo corre si ya hay un baseline con que comparar
    with open(os.path.join(obs.dir, "esquemas_observados.json"), "w", encoding="utf-8") as f:
        json.dump(esq.esquemas_de_corrida(obs.pasos), f,
                  ensure_ascii=False, indent=2, sort_keys=True)
    obs.ruta_esquemas = ruta_esquemas
    obs.validacion = []
    if generar:
        esq.escribir_baseline(obs.pasos, ruta_esquemas)
        print("\nBaseline de esquemas actualizado: %s" % os.path.abspath(ruta_esquemas))
    else:
        baseline = esq.leer_baseline(ruta_esquemas)
        if baseline is None:
            print("\nNo hay baseline de esquemas todavia (%s)."
                  % (ruta_esquemas or "-"))
            print("Genera uno desde una corrida buena:  --generar-esquemas")
        else:
            obs.validacion = esq.validar(obs.pasos, baseline)
            with open(os.path.join(obs.dir, "validacion_esquemas.json"),
                      "w", encoding="utf-8") as f:
                json.dump({"generado": ahora_iso(),
                           "baseline": os.path.abspath(ruta_esquemas),
                           "resumen": esq.resumir(obs.validacion),
                           "resultados": obs.validacion},
                          f, ensure_ascii=False, indent=2)

    # websockets.json: todos los frames en orden, con el paso en que cayeron
    frames = [dict(fr, paso=p["idx"], pantalla=p["url"])
              for p in obs.pasos for fr in (p.get("sockets") or [])]
    if frames:
        with open(os.path.join(obs.dir, "websockets.json"), "w", encoding="utf-8") as f:
            json.dump(frames, f, ensure_ascii=False, indent=2)

    escribir_har(obs, os.path.join(obs.dir, "captura.har"))
    escribir_reporte(obs, flujo, os.path.join(obs.dir, "reporte.html"))

    total = sum(1 for p in obs.pasos for r in p["requests"] if not r.get("sonda"))
    fallos = sum(s["fallos"] for s in resumen["pasos"])
    print("\n%d pasos, %d requests, %d con error (status >= 400, CORS o sin respuesta)"
          % (len(obs.pasos), total, fallos))
    if checks:
        print("\n--- /request/check ---")
        for c in checks:
            print("  paso %02d  %-20s %s" % (c["paso"], c["motivo"], sonda_check.linea(c)))
    n_ws = sum(len(p.get("sockets") or []) for p in obs.pasos)
    if n_ws:
        malos = [fr for fr in frames if '"stepStatus":"FAIL"' in fr["payload"].replace(" ", "")]
        print("%d mensaje(s) de websocket%s"
              % (n_ws, (", %d con stepStatus FAIL" % len(malos)) if malos else ""))
    if obs.sin_pestana:
        print("Aviso: %d request(s) sin pestana identificable (service worker) "
              "quedaron fuera." % obs.sin_pestana)
    imprimir_cobertura(cob)
    esq.imprimir(getattr(obs, "validacion", []), ruta_esquemas)
    print("")
    print("Evidencia: " + os.path.abspath(obs.dir))
    print("Reporte:   " + os.path.abspath(os.path.join(obs.dir, "reporte.html")))


class ObsDesdeDisco:
    """Un Observador de mentira, reconstruido leyendo una carpeta de evidencia.

    Sirve para regenerar el reporte cuando la corrida murio antes de escribirlo:
    los requests.jsonl se escriben incrementalmente, asi que el dato crudo esta.
    """

    def __init__(self, dir_evidencia, endpoints):
        self.dir = dir_evidencia
        self.endpoints = endpoints
        self.sin_pestana = 0
        self.pasos = []
        for nombre in sorted(os.listdir(dir_evidencia)):
            d = os.path.join(dir_evidencia, nombre)
            if not os.path.isdir(d) or not re.match(r"^\d+_", nombre):
                continue
            idx, slug = nombre.split("_", 1)
            reqs = []
            jsonl = os.path.join(d, "requests.jsonl")
            if os.path.exists(jsonl):
                with open(jsonl, encoding="utf-8") as f:
                    for ln in f:
                        ln = ln.strip()
                        if not ln:
                            continue
                        try:
                            r = json.loads(ln)
                        except json.JSONDecodeError:
                            continue   # linea a medias por un cierre abrupto
                        sonda_check.sin_caso_vigente(r)   # evidencia de antes del cambio
                        # re-marcar contra la lista de endpoints vigente
                        marcados = casan(endpoints, r.get("url", ""))
                        if marcados:
                            r["rastreados"] = marcados
                        reqs.append(r)
            frames = []
            jsonlws = os.path.join(d, "websocket.jsonl")
            if os.path.exists(jsonlws):
                with open(jsonlws, encoding="utf-8") as f:
                    for ln in f:
                        ln = ln.strip()
                        if not ln:
                            continue
                        try:
                            frames.append(json.loads(ln))
                        except json.JSONDecodeError:
                            continue
            self.pasos.append({
                "idx": int(idx), "url": (reqs[0]["url"] if reqs else ""), "slug": slug,
                "dir": d, "ts": (reqs[0]["ts"] if reqs else ""), "requests": reqs,
                "sockets": frames, "titulo": "", "pestana": 0,
            })


def rehacer_reporte(dir_evidencia, endpoints, ruta_esquemas=None, generar=False):
    """Regenera resumen/har/reporte desde una carpeta de evidencia existente."""
    if not os.path.isdir(dir_evidencia):
        print("No existe la carpeta: %s" % dir_evidencia)
        return 1
    obs = ObsDesdeDisco(dir_evidencia, endpoints)
    if not obs.pasos:
        print("No encontre carpetas de paso (NN_algo) en %s" % dir_evidencia)
        return 1
    # la URL del paso sale del resumen de la corrida (la pantalla real); si no
    # lo hay, del documento principal, y si tampoco, del slug. Sin el resumen
    # quedaba la URL del primer request, que capturando endpoints es una API.
    try:
        with open(os.path.join(dir_evidencia, "resumen.json"), encoding="utf-8") as f:
            previos = {p["idx"]: p for p in json.load(f).get("pasos", [])}
    except (OSError, ValueError, KeyError, TypeError):
        previos = {}
    for paso in obs.pasos:
        previo = previos.get(paso["idx"]) or {}
        if previo.get("url"):
            for k in ("url", "titulo", "ts", "pestana"):
                if previo.get(k) not in (None, ""):
                    paso[k] = previo[k]
            continue
        doc = next((r for r in paso["requests"] if r.get("tipo") == "document"), None)
        if doc:
            paso["url"] = doc["url"]
        elif not paso["url"]:
            paso["url"] = paso["slug"]
    print("Reconstruyendo desde %s" % os.path.abspath(dir_evidencia))
    print("%d pasos, %d requests"
          % (len(obs.pasos), sum(len(p["requests"]) for p in obs.pasos)))
    cerrar(obs, os.path.basename(dir_evidencia.rstrip("/\\")),
           ruta_esquemas=ruta_esquemas, generar=generar)
    return 0

SIN_REPORTE = "sin-reporte"


def modo_parada(stop_file):
    """Que pidio quien escribio el centinela: parar y reportar, o solo parar."""
    try:
        with open(stop_file, encoding="utf-8") as f:
            return f.read().strip().lower()
    except OSError:
        return ""


def avisar_pendiente(obs):
    """Corrida detenida a proposito sin reporte: la evidencia cruda ya esta."""
    try:
        obs.volcar_shots()
    except (AttributeError, OSError):
        pass
    print("\nDetenido sin generar el reporte.")
    print("Evidencia: " + os.path.abspath(obs.dir))
    print("Cuando quieras el reporte:  --rehacer-reporte \"%s\""
          % os.path.abspath(obs.dir))


def vigilar_parada(obs, flujo, ruta_esquemas, generar, stop_file, gracia=20):
    """Escribe el reporte aunque el loop no conteste al centinela.

    Playwright puede quedarse leyendo el cuerpo de una respuesta que nunca
    termina, o hablando con una pestana que se colgo. En ese caso el loop no
    vuelve a mirar el centinela y la corrida se quedaria sin reporte pese a
    tener toda la evidencia ya escrita en disco. Este hilo espera un margen y,
    si nadie atendio, cierra el mismo y sale.
    """
    while True:
        time.sleep(1)
        if not os.path.exists(stop_file):
            continue
        limite = time.time() + gracia
        while os.path.exists(stop_file) and time.time() < limite:
            time.sleep(0.5)
        if not os.path.exists(stop_file) or _CERRADO[0]:
            return                       # el loop lo atendio; todo normal
        if modo_parada(stop_file) == SIN_REPORTE:
            obs.sin_reporte = True
        print("\n! El navegador no responde tras %d s. Salgo%s."
              % (gracia, "" if getattr(obs, "sin_reporte", False)
                 else " y genero el reporte con lo capturado"))
        try:
            os.remove(stop_file)
        except OSError:
            pass
        try:
            if getattr(obs, "sin_reporte", False):
                avisar_pendiente(obs)
            else:
                cerrar(obs, flujo, ruta_esquemas=ruta_esquemas, generar=generar)
        except Exception as e:
            print("! el cierre fallo: %s" % e)
        sys.stdout.flush()
        os._exit(0)     # sin cleanup de Playwright: es justo lo que esta colgado


# --- main ------------------------------------------------------------------
def main():
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
    args = ap.parse_args()

    if args.lanzar_chrome:
        return lanzar_chrome(args.puerto)

    endpoints = ([e.strip() for e in args.endpoints.split(",") if e.strip()]
                 if args.endpoints else list(ENDPOINTS_RASTREADOS))

    if args.rehacer_reporte:
        return rehacer_reporte(args.rehacer_reporte, endpoints,
                               ruta_esquemas=args.esquemas,
                               generar=args.generar_esquemas)

    sonda = None
    if args.request_check or args.documento:
        try:
            doc = sonda_check.parse_documento(args.documento) if args.documento else None
        except ValueError as e:
            print("! %s" % e)
            return 2
        sonda = sonda_check.SondaCheck(doc)
        if not sonda.arrancar():
            sonda = None          # sin token.txt: se captura igual, sin la sonda

    modo = "todo" if args.todos_los_hosts else args.captura
    if args.solo_endpoints:
        modo = "endpoints"
    hosts = [] if modo == "todo" else [h.strip() for h in args.hosts.split(",") if h.strip()]
    extras = [e.strip() for e in (args.pantallazo_extra or "").split(",") if e.strip()]
    marca = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dir_salida = os.path.join(args.out, "%s_%s" % (re.sub(r"[^A-Za-z0-9._-]+", "-", args.flujo), marca))
    os.makedirs(dir_salida, exist_ok=True)

    # Git Bash/MSYS convierte un argumento que empieza con "/" en ruta de Windows:
    # "/creditos/solicitud" llega como "C:/Program Files/Git/creditos/solicitud".
    if args.solo_url and re.search(r"^[A-Za-z]:[/\\].*Git[/\\]", args.solo_url):
        limpio = re.sub(r"^[A-Za-z]:[/\\].*?Git[/\\]", "", args.solo_url)
        print("AVISO: tu shell convirtio el patron en una ruta de Windows.")
        print("       Recibido: %s" % args.solo_url)
        print("       Uso:      %s" % limpio)
        print("       Para evitarlo, no empieces el patron con \"/\".\n")
        args.solo_url = limpio

    # sin --solo-url no se filtra nada; con el, se aceptan varias rutas para
    # que el mismo comando sirva en los dos despliegues del front
    patrones_pestana = ([x.strip() for x in args.solo_url.split(",") if x.strip()]
                        if args.solo_url else [])
    obs = Observador(dir_salida, hosts, not args.sin_redactar, args.settle_ms,
                     patron_pestana=patrones_pestana, seguir_popups=args.seguir_popups,
                     endpoints=endpoints, solo_endpoints=(modo == "endpoints"),
                     pantallazo_extra=extras, extra_ms=args.extra_ms,
                     screenshot_on_response=args.screenshot_on_response,
                     sonda=sonda)

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


def observar(args, obs):
    """Sesion de Playwright: engancha, escucha y devuelve al terminar."""
    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:%d" % args.puerto)
        except Exception as e:
            print("No pude conectar al puerto %d: %s" % (args.puerto, e))
            print("Lanza Chrome primero:  python %s --lanzar-chrome" % os.path.basename(__file__))
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
            limpiar_navegador(browser, paginas, obs.hosts or HOSTS_DEFAULT)

        activa = paginas[0]
        if args.solo_url:
            # si la pestana objetivo ya esta abierta, la fijamos de una
            for pg in paginas:
                try:
                    if obs.intentar_lock(pg, pg.url):
                        activa = pg
                        obs.abrir_paso(pg, pg.url)
                        break
                except Exception:
                    continue
            if obs.lock is None:
                print("Aun no veo ninguna pestana con %s."
                      % " ni ".join('"%s"' % p for p in obs.patrones))
                print("Navega a esa URL y la fijo automaticamente.")
        elif es_url_real(activa.url):
            obs.abrir_paso(activa, activa.url)
        else:
            print("Esperando la primera pantalla (la pestana esta en %s)..." % activa.url)

        print("Alcance: %s"
              % ("SOLO la pestana con "
                 + " o ".join('"%s"' % p for p in obs.patrones)
                 if obs.patrones else "todas las pestanas"))
        if obs.solo_endpoints:
            print("Se guardan: solo los %d endpoints rastreados" % len(obs.endpoints))
        elif obs.hosts:
            print("Se guardan: todo lo que vaya a: " + ", ".join(obs.hosts))
        else:
            print("Se guardan: TODOS los requests (incluye analytics y CDN)")
        if obs.pantallazo_extra:
            print("Pantallazo extra en: %s" % ", ".join(obs.pantallazo_extra))
        print("Redaccion de credenciales: %s" % ("ON" if obs.redactar else "OFF"))
        if obs.sonda:
            print("/request/check: al inicio y en informacion personal, con %s"
                  % ("%s %s" % obs.sonda.doc if obs.sonda.doc
                     else "el documento que aparezca en el trafico"))
        print("Escuchando. Navega normal. Ctrl+C para cerrar y generar el reporte.\n")

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
                if args.stop_file and os.path.exists(args.stop_file):
                    # parada limpia pedida desde afuera: sale por el mismo camino
                    # que Ctrl+C. Segun lo que diga el centinela, se arma el
                    # reporte o se deja la evidencia cruda para generarlo luego.
                    obs.sin_reporte = modo_parada(args.stop_file) == SIN_REPORTE
                    print("\nParada solicitada%s."
                          % (" (sin reporte)" if obs.sin_reporte else ""))
                    try:
                        os.remove(args.stop_file)
                    except OSError:
                        pass
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
                obs.drenar_respuestas()
                obs.drenar_fallos()
                obs.drenar_huerfanos()
                obs.volcar_sonda()
                ahora = time.time() * 1000
                # cada pestana con un cambio ya "asentado" abre su propio paso
                for pagina, (url, t0) in list(obs.pendientes.items()):
                    if ahora - t0 < obs.settle_ms:
                        continue
                    obs.pendientes.pop(pagina, None)
                    try:
                        url_real = pagina.url
                    except Exception:
                        continue  # pestana cerrada mientras esperabamos
                    actual = obs.paso_por_pagina.get(pagina)
                    if not actual or actual["url"] != url_real:
                        obs.abrir_paso(pagina, url_real)
                obs.tomar_shots_tarde()
                obs.volcar_shots()
                obs.tomar_extras()
                obs.tomar_shots_diferidos()
        except KeyboardInterrupt:
            print("\nCerrando...")
        finally:
            # Tras un Ctrl+C, Playwright ya esta cancelando sus tareas: leer los
            # bodies pendientes puede reventar. Que eso NO impida el reporte.
            try:
                obs.tomar_shots_tarde(forzar=True)
                obs.volcar_shots()        # no perder los del ultimo instante
                obs.vaciar_pendientes()   # no perder la ultima pantalla
                obs.tomar_shots_diferidos(forzar=True)
                obs.tomar_extras(forzar=True)
            except BaseException:
                pass
            try:
                obs.drenar_respuestas()
                obs.esperar_en_vuelo(activa, args.espera_en_vuelo)
                # lo que respondio mientras se esperaba (el login, p. ej.)
                # tambien deja su pantallazo
                obs.tomar_shots_tarde(forzar=True)
                obs.volcar_shots()
            except BaseException:
                pend = len(obs.cola_resp)
                if pend:
                    print("(%d respuesta(s) pendientes no se pudieron leer)" % pend)
            # lo que siga sin leer o sin respuesta queda marcado, no desaparece
            try:
                obs.rescatar_en_vuelo()
            except BaseException:
                pass
            # no toca Playwright: solo HTTP y disco. No hay consulta final:
            # solo se espera lo que siga en vuelo y se guarda lo que respondio.
            try:
                if obs.sonda and not obs.sin_reporte:
                    obs.sonda.cerrar(obs.paso_actual())
                obs.volcar_sonda()
            except BaseException:
                pass
    return True


if __name__ == "__main__":
    sys.exit(main())

"""Login -> validaciones -> politicas, sin pasar de ahi, con el observador
grabando los servicios. Sirve para Consumo (por slug) y, con --entrada cupo,
para Cupo.

Dos formas de iniciar sesion (--sesion):
  token  (default) sin clave: pide a token/ciam de Apigee un JWT a nombre de
         la cedula y lo guarda como lo hace el front tras el login de Gigya
         (useAuth.processAndRedirect: POST {basePath}/api/auth/session y los
         datos del afiliado en sessionStorage), y entra a validaciones. Se
         salta Gigya y authciam; de ahi en adelante el flujo es el real.
  clave  el login de verdad por el formulario de Gigya.

Se detiene al aterrizar en politicas SIN tocar "Continuar" (ese boton crea el
caso), en el mensaje de rechazo de validaciones, en la salida a otro sitio
(CFA) o en otra pantalla (retoma de un caso en curso). La evidencia queda en
evidences/hasta-politicas_<producto>_<numero>_<fecha>/, igual que la del
observador: reporte.html, servicios.json, requests.jsonl y pantallazo por paso.

No esta en Java: es nuevo, armado con los page objects y el observador.
"""
import json
import os
import re
import time
from datetime import datetime
from urllib.parse import urlsplit

from .. import _rutas  # noqa: F401
from ..core import reporte as log
from ..pages import LoginCreditoPage, OnboardingPage, TermsAndConditionsPage
from ..pages.login_credito_page import decode_jwt

import rutas  # noqa: E402  (raiz del repo, via _rutas)
import validaciones_api as va  # noqa: E402
from observador import cierre  # noqa: E402
from observador.alcance import Alcance  # noqa: E402
from observador.complementos import ComplementoCamino  # noqa: E402
from observador.config import (ENDPOINTS_RASTREADOS, ESQUEMAS_DEFAULT,  # noqa: E402
                               HOSTS_DEFAULT, SELECTOR_MENSAJE,
                               SHOT_RESPUESTA_DEFAULT)
from observador.observador import Observador  # noqa: E402
from observador.util import es_url_real  # noqa: E402

NOMBRE = "HastaPoliticas"
TEST_ID = "225425"
AUTORES = "Santiago Correa"
CATEGORIAS = ("REGRESSION",)
DATA_PROVIDER = "hasta_politicas"
BASE = "https://d2b80yrnend1dj.cloudfront.net/loans-dev-solicitud"
URL = BASE + "/consumo/libre-inversion/onboarding"
MANEJA_HASTA_LOGIN = True

# Ademas de los del observador: lo que pinta politicas y los textos de los
# rechazos, que salen de Drupal.
ENDPOINTS = list(ENDPOINTS_RASTREADOS) + [
    "/parametros/politicas/",
    "/parametros/v2/forms/politicas",
    "/parametros/v2/listas/",
    "/parametros/casuisticas",
    "/validate-holder",
    "/habeas-data",
    "/request/validate",
]
# Lo que tarda en desconectarse lo que siga en vuelo al parar.
ESPERA_EN_VUELO_S = 10
# customer.documentType del JWT -> DocumentTypes del front (userDataUtils.ts).
# token/ciam lo manda como texto ("3"); en JS da igual, aqui no.
TIPO_FRONT = {"2": "CO1C", "3": "CO1E"}


def necesita_clave(opciones):
    return opciones.get("sesion") == "clave"


def url_inicial(_opciones):
    # El observador se engancha antes de la primera pantalla.
    return "about:blank"


def base_de(opciones):
    return (opciones.get("base") or BASE).rstrip("/")


def ruta(url, opciones):
    base = base_de(opciones)
    return url[len(base):] if url.startswith(base) else url


def prefijo(opciones):
    base = base_de(opciones)
    if opciones.get("entrada") == "cupo":
        return base + "/cupo-de-credito"
    return "%s/consumo/%s" % (base, opciones.get("slug") or "libre-inversion")


def producto(opciones):
    return "cupo" if opciones.get("entrada") == "cupo" else (opciones.get("slug") or "libre-inversion")


def armar_observador(usuario, opciones, nombre="hasta-politicas"):
    sello = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    flujo = "%s_%s_%s" % (nombre, producto(opciones), usuario.numero)
    directorio = rutas.dato("evidences", "%s_%s" % (flujo, sello))
    os.makedirs(directorio, exist_ok=True)
    alcance = Alcance(HOSTS_DEFAULT, endpoints=ENDPOINTS, solo_endpoints=True)
    obs = Observador(directorio, alcance, redactar=True, settle_ms=1200,
                     screenshot_on_response=SHOT_RESPUESTA_DEFAULT,
                     complementos=[ComplementoCamino()])
    return obs, flujo


def esperar(driver, obs, segundos):
    """Espera bombeando los eventos de Playwright y el loop del observador."""
    fin = time.time() + segundos
    while time.time() < fin:
        driver.page.wait_for_timeout(200)
        obs.tick()


def iniciar_sesion_token(driver, usuario, opciones):
    jwt = va.token_ciam_usuario(usuario.tipo, usuario.numero)
    log.info_token("JWT de token/ciam", jwt)
    ruta_sesion = urlsplit(base_de(opciones)).path + "/api/auth/session"
    status, texto = driver.page.evaluate(
        """async ([jwt, ruta]) => {
             const r = await fetch(ruta, {method: 'POST', cache: 'no-cache',
               headers: {'Content-Type': 'application/json'}, body: JSON.stringify({jwt})});
             return [r.status, await r.text()];
           }""", [jwt, ruta_sesion])
    if status != 200:
        log.fail("POST %s respondio %s: %s" % (ruta_sesion, status, texto[:200]))
        return False
    cliente = decode_jwt(jwt).get("customer") or {}
    driver.page.evaluate(
        "(datos) => { for (const [k, v] of Object.entries(datos)) if (v) sessionStorage.setItem(k, v); }",
        {"documentType": TIPO_FRONT.get(str(cliente.get("documentType")), ""),
         "documentNumber": str(cliente.get("documentNumber") or ""),
         "userName": cliente.get("firstName"), "lastName": cliente.get("lastName"),
         "cellPhone": cliente.get("telephoneNumber"), "email": cliente.get("mail")})
    log.pass_("Sesion guardada sin Gigya (cookie userToken por /api/auth/session)")
    destino = "/validaciones"
    if opciones.get("directo"):
        # la cookie que deja Validations.tsx al pasar; con ella el middleware
        # deja entrar a politicas sin caso en curso. gtmUserBasic lo guarda
        # SAP al pasar (storeUserTrackingGtmData): sin el, la analitica de
        # Continuar revienta y nunca se llama a validate.
        driver.page.evaluate(
            "() => { document.cookie = 'validationsSuccess=true; path=/';"
            " localStorage.setItem('gtmUserBasic', JSON.stringify({usCategory: 'NA',"
            " bsName: 'NA', bsDocumentNumber: 'NA', bsDocumentType: 'NA'})); }")
        if opciones.get("entrada") == "cupo":
            # en Cupo ASCARD deja la novedad (1 = originacion) y validate la
            # manda como tipoSolicitud (useAscardValidator / useAffiliation)
            driver.page.evaluate("() => { document.cookie = 'caseType=1; path=/'; }")
        log.warning("--directo: entra a politicas sin pasar por validaciones")
        destino = "/politicas"
    driver.page.goto(prefijo(opciones) + destino, wait_until="domcontentloaded", timeout=60000)
    return True


def iniciar_sesion_clave(driver, usuario, opciones):
    onboarding = OnboardingPage(driver)
    onboarding.walk_steps()
    onboarding.click_start_request()
    driver.page.wait_for_url(re.compile(r".*/login(\?.*)?$"), timeout=30000)
    login = LoginCreditoPage(driver).wait_form_visible()
    if opciones.get("hasta_login"):
        log.info("--hasta-login: se detiene antes de escribir la clave")
        return False
    (login
     .select_document_type(usuario.tipo)
     .enter_identification(usuario.numero)
     .enter_password(usuario.clave)
     .click_submit())
    if not login.get_user_token_cookie(45):
        return False
    TermsAndConditionsPage(driver).close_gigya_dialog_if_present()
    return True


def esperar_desenlace(driver, obs, opciones):
    """Hasta politicas, un mensaje en pantalla, otra pantalla u otro sitio."""
    base = base_de(opciones)
    pre = prefijo(opciones)
    de_paso = (pre + "/validaciones", pre + "/onboarding", base + "/login")
    fin = time.time() + (opciones.get("espera") or 90)
    while time.time() < fin:
        esperar(driver, obs, 0.5)
        url = driver.page.url.split("?")[0]
        if not url.startswith(base):
            return "otro sitio", url
        if url.rstrip("/").endswith("/politicas"):
            # sin "Continuar": solo dejar que cargue el contenido de Drupal
            try:
                driver.page.locator("input[type='checkbox']").first.wait_for(
                    state="attached", timeout=15000)
            except Exception:
                pass
            esperar(driver, obs, 3)
            return "politicas", url
        if driver.page.locator(SELECTOR_MENSAJE).count():
            esperar(driver, obs, 4)   # el texto del mensaje llega despues de Drupal
            return "mensaje", url
        if not url.startswith(de_paso):
            esperar(driver, obs, 4)
            return "otra pantalla", url
    return "tiempo agotado", driver.page.url


def texto_pantalla(driver):
    try:
        return re.sub(r"\s+", " ", driver.page.inner_text("body")).strip()
    except Exception:
        return ""


def resumir_servicios(obs):
    """Los servicios capturados, en orden, con lo esencial de la respuesta."""
    print("\n--- servicios ---")
    for paso in obs.pasos:
        for r in paso["requests"]:
            if not r.get("rastreados"):
                continue
            cuerpo = r.get("response_body") or ""
            try:
                cuerpo = json.dumps(json.loads(cuerpo), ensure_ascii=False, separators=(",", ":"))
            except (TypeError, ValueError):
                cuerpo = re.sub(r"\s+", " ", cuerpo)
            print("  paso %02d  %-4s %-5s %s" % (paso["idx"], r["metodo"],
                                                r.get("status") or r.get("fallo"),
                                                urlsplit(r["url"]).path))
            if cuerpo:
                print("           %s" % cuerpo[:300])


def llegar_a_politicas(driver, obs, usuario, opciones):
    """Onboarding -> inicio de sesion -> validaciones -> politicas. Devuelve
    el desenlace ("politicas", "mensaje", "otra pantalla", "otro sitio",
    "tiempo agotado") o None si no se inicio sesion."""
    driver.page.goto(prefijo(opciones) + "/onboarding", wait_until="domcontentloaded",
                     timeout=60000)
    esperar(driver, obs, 3)
    if opciones.get("sesion") == "clave":
        entro = iniciar_sesion_clave(driver, usuario, opciones)
    elif opciones.get("hasta_login"):
        log.info("--hasta-login no aplica con --sesion token: se queda en el Onboarding")
        entro = False
    else:
        entro = iniciar_sesion_token(driver, usuario, opciones)
    if not entro:
        return None
    desenlace, url = esperar_desenlace(driver, obs, opciones)
    if desenlace == "politicas":
        log.pass_("Llega a politicas sin tocar 'Continuar': %s" % ruta(url, opciones))
    elif desenlace == "tiempo agotado":
        log.fail("No llego a politicas en %ss; sigue en %s"
                 % (opciones.get("espera") or 90, ruta(url, opciones)))
    else:
        log.warning("Se detuvo antes de politicas (%s): %s" % (desenlace, ruta(url, opciones)))
    log.info("Pantalla: %s" % texto_pantalla(driver)[:400])
    return desenlace


def capturar(driver, usuario, opciones, nombre, pasos, al_parar=None):
    """Corre pasos(obs) con el observador grabando; al final escribe la
    evidencia e imprime los servicios. al_parar(obs) corre con la captura ya
    completa y antes de escribir el reporte (lo usa el validador e2e)."""
    obs, flujo = armar_observador(usuario, opciones, nombre)
    obs.enganchar(driver.page)
    if es_url_real(driver.page.url):
        obs.abrir_paso(driver.page, driver.page.url)   # enganchado a una sesion abierta
    try:
        pasos(obs)
    finally:
        obs.parar(driver.page, ESPERA_EN_VUELO_S)
        if al_parar:
            try:
                al_parar(obs)
            except Exception as e:
                log.fail("Validador al cerrar: %s" % str(e).strip().split("\n")[0])
        cierre.reiniciar()
        cierre.cerrar(obs, flujo, ruta_esquemas=ESQUEMAS_DEFAULT)
    resumir_servicios(obs)


def run(driver, usuario, opciones):
    capturar(driver, usuario, opciones, "hasta-politicas",
             lambda obs: llegar_a_politicas(driver, obs, usuario, opciones))

"""HU 225423 escenario 1 "Conservacion y trazabilidad del producto": entra
por el Onboarding de Consumo, inicia sesion y verifica que la identificacion
del producto (cookie subproductSlug) se conserve hasta la pantalla post-login
sin contenido de otro producto. Con --entrada cupo hace el mismo recorrido por
Cupo como regresion.

No esta en Java: es nuevo, armado con los mismos page objects.
"""
import re
import time

from ..core import datalayer
from ..core import reporte as log
from ..pages import LoginCreditoPage, OnboardingPage, TermsAndConditionsPage

NOMBRE = "ConsumoPuntosEntrada225423"
TEST_ID = "225423"
AUTORES = "Santiago Correa"
CATEGORIAS = ("REGRESSION",)
DATA_PROVIDER = "consumo_225423"
BASE = "https://d2b80yrnend1dj.cloudfront.net/loans-dev-solicitud"
URL = BASE + "/consumo/libre-inversion/onboarding"
MANEJA_HASTA_LOGIN = True

# Texto de Cupo que no deberia verse en un flujo de Consumo.
PATRON_CUPO = re.compile(r"\bcupo\b|tarjeta de afiliaci[oó]n", re.I)
# Las dos 404 que hay: la del front (ErrorMessage) y la generica que pinta el
# servidor cuando Next responde 404 ("Error 404 - Pagina No Encontrada").
PATRON_404 = re.compile(r"no encontramos esta p[aá]gina|c[oó]d\. error 404|"
                        r"error 404|p[aá]gina no encontrada", re.I)
# Cookies del front que dicen en que producto y en que caso va el afiliado.
COOKIES_FLUJO = ("subproductSlug", "productId", "requestId", "requestState",
                 "currentStepOfRequestRecovery", "quotaUpdateVariant",
                 "validationsSuccess", "checkError", "userAffiliationType")
COOKIES_SOLO_PRESENCIA = ("userToken", "offerData", "campaingData")


def url_inicial(opciones):
    base = (opciones.get("base") or BASE).rstrip("/")
    if opciones.get("entrada") == "cupo":
        return base + "/cupo-de-credito/onboarding"
    return "%s/consumo/%s/onboarding" % (base, opciones.get("slug") or "libre-inversion")


def check(ok, nombre, detalle=""):
    texto = nombre + (" -- " + detalle if detalle else "")
    (log.pass_ if ok else log.fail)(texto)
    return ok


def ruta_url(url, base):
    return url[len(base):] if url.startswith(base) else url


def ruta(driver, opciones):
    return ruta_url(driver.page.url, (opciones.get("base") or BASE).rstrip("/"))


def esperar_estable(driver, opciones, segundos, quieto=5):
    """Espera a que la URL deje de cambiar fuera de /login: el middleware
    puede encadenar redirecciones despues del login."""
    fin = time.time() + segundos
    ultima, desde = driver.page.url, time.time()
    while time.time() < fin:
        driver.page.wait_for_timeout(500)
        if driver.page.url != ultima:
            ultima, desde = driver.page.url, time.time()
            continue
        actual = ruta(driver, opciones)
        en_login = actual.split("?")[0] == "/login"
        if time.time() - desde >= quieto and (not en_login or "requestState=" in actual):
            return


def run(driver, usuario, opciones):
    es_consumo = opciones.get("entrada") != "cupo"
    slug = opciones.get("slug") or "libre-inversion"
    navegacion, redirecciones = [], []
    driver.page.on("framenavigated", lambda f: f == driver.page.main_frame
                   and navegacion.append(ruta(driver, opciones)))
    # Solo las redirecciones del propio front, no las de los pixeles de terceros.
    base = (opciones.get("base") or BASE).rstrip("/")
    driver.page.on("request", lambda r: r.redirected_from
                   and r.redirected_from.url.startswith(base)
                   and redirecciones.append("%s -> %s" % (ruta_url(r.redirected_from.url, base),
                                                          ruta_url(r.url, base))))
    datalayer.install(driver)

    # 1. Onboarding
    onboarding = OnboardingPage(driver)
    cookie = driver.cookies().get("subproductSlug")
    if es_consumo:
        check(cookie == slug, "Cookie subproductSlug en Onboarding", "valor=%r" % cookie)
    else:
        check(not cookie, "Cupo sin cookie subproductSlug", "valor=%r" % cookie)
    pasos = onboarding.walk_steps()
    check(len(pasos) == 3, "Onboarding con 3 pasos", "%d pasos" % len(pasos))
    if es_consumo:
        con_cupo = [PATRON_CUPO.search(texto) for _, texto in pasos if PATRON_CUPO.search(texto)]
        check(not con_cupo, "Onboarding sin contenido de Cupo",
              "aparece '%s'" % con_cupo[0].group(0) if con_cupo else "")
    onboarding.click_start_request()

    # 2. Login
    driver.page.wait_for_url(re.compile(r".*/login(\?.*)?$"), timeout=30000)
    cookie = driver.cookies().get("subproductSlug")
    check(True, "Llega a /login", ruta(driver, opciones))
    check(cookie == slug if es_consumo else not cookie,
          "Cookie de producto en /login", "subproductSlug=%r" % cookie)
    login = LoginCreditoPage(driver).wait_form_visible()
    if opciones.get("hasta_login"):
        log.info("--hasta-login: se detiene antes de escribir la clave")
        return

    (login
     .select_document_type(usuario.tipo)
     .enter_identification(usuario.numero)
     .enter_password(usuario.clave)
     .click_submit())
    if not login.get_user_token_cookie(45):
        return
    login.validate_user_token(usuario.tipo, usuario.numero)
    TermsAndConditionsPage(driver).close_gigya_dialog_if_present()

    # 3. Despues del login
    esperar_estable(driver, opciones, opciones.get("espera") or 40)
    final = ruta(driver, opciones)
    texto = OnboardingPage(driver).get_visible_text()
    cookies = driver.cookies()
    log.info("Navegacion: %s" % " > ".join(dict.fromkeys(navegacion)))
    for r in redirecciones:
        log.info("Redireccion: %s" % r)
    log.info("Cookies del flujo: %s" % (", ".join(
        "%s=%s" % (k, cookies[k]) for k in COOKIES_FLUJO if k in cookies) or "-"))
    log.info("Cookies presentes: %s" % (", ".join(
        k for k in COOKIES_SOLO_PRESENCIA if k in cookies) or "-"))
    log.info("Pantalla: %s" % re.sub(r"\s+", " ", texto)[:400])

    if es_consumo:
        check(final.startswith("/consumo/%s/" % slug), "URL final dentro de /consumo/%s/" % slug, final)
        check(cookies.get("subproductSlug") == slug, "Cookie subproductSlug conservada tras login",
              "valor=%r" % cookies.get("subproductSlug"))
        m = PATRON_CUPO.search(texto)
        check(not m, "Pantalla sin contenido de Cupo", "aparece '%s'" % m.group(0) if m else "")
    else:
        check(final.startswith(("/cupo-de-credito/", "/login")),
              "URL final dentro de /cupo-de-credito/ o /login", final)
        check("subproductSlug" not in cookies, "Cupo sigue sin subproductSlug",
              "valor=%r" % cookies.get("subproductSlug"))
    check(not PATRON_404.search(texto), "Pantalla final no es 404", final)

    eventos = [e["payload"] for e in datalayer.get_events(driver)
               if isinstance(e.get("payload"), dict) and e["payload"].get("eventName") == "login"]
    esperado = "consumo" if es_consumo else "cupo_credito"
    productos = sorted({str(e.get("producto")) for e in eventos})
    if eventos:
        check(productos == [esperado], "Analitica login con producto %s" % esperado,
              "producto=%s" % productos)
    else:
        log.warning("Sin evento 'login' en el dataLayer (la pagina pudo recargarse)")

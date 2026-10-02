"""BasePage + ExplicitWaitFactory.

Los metodos encadenables devuelven self, como en Java (alli recibian la pagina
como primer argumento: actionMessage(page, msg) -> page.action_message(msg)).
Igual que en Java, click/send_keys/get_text no cortan el test cuando fallan:
registran el fallo en el reporte y el flujo sigue.
"""
import os
import re
import time

from .core import network
from .core import reporte as log
from .core.enums import WaitStrategy

# WebDriverWait de BasePage (40 s) y los de ExplicitWaitFactory (5 s; 10 s en sendKeys).
ESPERA_PAGINA = 40
ESPERA_EXPLICITA = 5
ESPERA_SEND_KEYS = 10


def xpath_literal(valor):
    """Literal XPath seguro aunque el texto traiga comillas."""
    if "'" not in valor:
        return "'%s'" % valor
    if '"' not in valor:
        return '"%s"' % valor
    partes = valor.split("'")
    return "concat(%s)" % ", \"'\", ".join("'%s'" % p for p in partes)


class BasePage:
    def __init__(self, driver):
        self.driver = driver
        self.saved_url = None

    @property
    def page(self):
        return self.driver.page

    def loc(self, selector):
        """Locator de Playwright a partir de css/xpath (o un Locator ya armado)."""
        return self.page.locator(selector) if isinstance(selector, str) else selector

    def perform_explicit_wait(self, estrategia, selector, segundos=ESPERA_EXPLICITA):
        locator = self.loc(selector)
        ms = segundos * 1000
        if estrategia in (WaitStrategy.CLICKABLE, WaitStrategy.VISIBLE):
            locator.wait_for(state="visible", timeout=ms)
        elif estrategia == WaitStrategy.PRESENCE:
            locator.wait_for(state="attached", timeout=ms)
        elif estrategia == WaitStrategy.INVISIBLE:
            locator.wait_for(state="hidden", timeout=ms)
        return locator

    def await_visible(self, selector, segundos):
        try:
            return self.perform_explicit_wait(WaitStrategy.VISIBLE, selector, segundos)
        except Exception as e:
            log.fail("Element not visible, locator {%s}: %s" % (selector, _primera_linea(e)))
            raise

    def await_clickable(self, selector, segundos):
        try:
            return self.perform_explicit_wait(WaitStrategy.CLICKABLE, selector, segundos)
        except Exception as e:
            log.fail("Element not clickable, locator {%s}: %s" % (selector, _primera_linea(e)))
            raise

    def await_present(self, selector, segundos):
        try:
            return self.perform_explicit_wait(WaitStrategy.PRESENCE, selector, segundos)
        except Exception as e:
            log.fail("Element not present, locator {%s}: %s" % (selector, _primera_linea(e)))
            raise

    def click(self, selector, estrategia=WaitStrategy.CLICKABLE, nombre=None):
        try:
            locator = self.perform_explicit_wait(estrategia, selector)
            locator.click(timeout=ESPERA_EXPLICITA * 1000)
            if nombre:
                log.pass_("%s was clicked correctly" % nombre)
        except Exception as e:
            donde = "[%s] " % nombre if nombre else ""
            log.fail("Click failed on %slocator {%s}: %s" % (donde, selector, _primera_linea(e)))

    def click_with_fallback(self, selector):
        """scrollIntoView + click; si lo interceptan, click por JS."""
        locator = self.loc(selector)
        locator.scroll_into_view_if_needed(timeout=ESPERA_PAGINA * 1000)
        try:
            locator.click(timeout=ESPERA_EXPLICITA * 1000)
        except Exception:
            locator.evaluate("el => el.click()")

    def send_keys(self, selector, estrategia, data, ocultar=False):
        try:
            locator = self.perform_explicit_wait(estrategia, selector, ESPERA_SEND_KEYS)
            locator.press_sequentially(data)
            # En Java se registraba el valor tal cual (incluida la clave): aqui no.
            log.pass_("The information %s entered correctly" % ("***" if ocultar else data))
        except Exception as e:
            log.fail("SendKeys failed on locator {%s}: %s" % (selector, _primera_linea(e)))

    def get_text(self, selector, estrategia, nombre, segundos=ESPERA_EXPLICITA):
        try:
            texto = self.perform_explicit_wait(estrategia, selector, segundos).inner_text()
            log.pass_("text retrieved: %s" % texto)
            return texto
        except Exception as e:
            log.fail("Failed to retrieve text from [%s] locator {%s}: %s"
                     % (nombre, selector, _primera_linea(e)))
            return None

    def first_visible(self, selector, segundos):
        """Primer elemento VISIBLE del selector, o None. Hace falta cuando hay
        varios iguales en el DOM y el primero esta oculto (un .first fallaria)."""
        fin = time.time() + segundos
        while True:
            todos = self.loc(selector)
            for i in range(todos.count()):
                if todos.nth(i).is_visible():
                    return todos.nth(i)
            if time.time() >= fin:
                return None
            self.page.wait_for_timeout(500)

    def set_native_value(self, selector, texto):
        """Native value setter + eventos input/change: para inputs controlados
        de React que no reaccionan a un type normal (ver feedback_react_selenium)."""
        self.loc(selector).evaluate(
            """(el, v) => {
                 const setter = Object.getOwnPropertyDescriptor(
                     window.HTMLInputElement.prototype, 'value').set;
                 setter.call(el, v);
                 el.dispatchEvent(new Event('input', { bubbles: true }));
                 el.dispatchEvent(new Event('change', { bubbles: true }));
               }""", texto)

    # ----------------------------------------------------- pasos encadenables

    def run_if(self, condicion, paso):
        """Corre paso(self) solo si condicion; si no, sigue la cadena igual."""
        if condicion:
            return paso(self)
        log.info("Step skipped by precondition gate")
        return self

    def wait_interaction_user(self, mensaje):
        input("[Accion manual] %s -- Enter para seguir..." % mensaje)
        return self

    def action_message(self, mensaje):
        log.info(mensaje)
        return self

    def take_screenshot_report(self, nombre):
        log.info(nombre)
        self._guardar_captura(nombre)
        return self

    def take_screenshot_and_save_it_local(self, nombre):
        self._guardar_captura(nombre)
        return self

    def _guardar_captura(self, nombre):
        # Solo con --capturas: el script no deja evidencias por su cuenta.
        if not self.driver.capturas:
            return
        archivo = re.sub(r"[^\w.-]+", "_", nombre).strip("_") + ".png"
        try:
            self.page.screenshot(path=os.path.join(self.driver.capturas, archivo),
                                 full_page=True)
        except Exception as e:
            log.warning("No se pudo guardar la captura %s: %s" % (archivo, _primera_linea(e)))

    def wait_for_service_ok(self, fragmento, timeout_s):
        log.info("-> waitForServiceOk: '%s' (max %ss)" % (fragmento, timeout_s))
        resultado = network.await_service_ok(self.driver, fragmento, timeout_s)
        if resultado == network.OkOutcome.ALREADY_RESPONDED:
            log.pass_("Service had ALREADY answered 200 before the wait: " + fragmento)
        elif resultado == network.OkOutcome.RESPONDED_AFTER_WAIT:
            log.pass_("Service answered 200 during the wait: " + fragmento)
        else:
            log.fail("Service did NOT return 200 within %ss -- flow blocked: %s"
                     % (timeout_s, fragmento))
            raise AssertionError("Service did not return 200 (flow blocked): " + fragmento)
        return self

    def wait_for_offer_case_id(self, fragmento, timeout_s):
        """Espera un 200 en fragmento y devuelve el ultimo segmento de la URL
        (el idCaso de /request/offer/{idCaso}). None si se acaba el tiempo."""
        log.info("-> waitForOfferCaseId: '%s' (max %ss)" % (fragmento, timeout_s))
        url = network.await_service_ok_get_url(self.driver, fragmento, timeout_s)
        if url is None:
            log.fail("Timeout waiting for: " + fragmento)
            return None
        id_caso = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
        log.pass_("Case ID extracted from %s: %s" % (fragmento, id_caso))
        return id_caso

    def delay(self, millis):
        log.info("Delay de %s ms" % millis)
        time.sleep(millis / 1000.0)
        return self

    def save_current_url(self):
        self.saved_url = self.page.url
        log.info("URL actual: %s" % self.saved_url)
        return self

    def get_saved_url(self):
        return self.saved_url

    def reload_page(self):
        try:
            self.page.reload(wait_until="load", timeout=15000)
            log.info("Pagina recargada")
        except Exception as e:
            log.info("reloadPage: espera de carga agotada o fallo -- se continua: %s"
                     % _primera_linea(e))
        return self

    def set_dimensions_screen(self, ancho, alto):
        self.page.set_viewport_size({"width": ancho, "height": alto})
        return self


def _primera_linea(error):
    return str(error).strip().split("\n")[0]

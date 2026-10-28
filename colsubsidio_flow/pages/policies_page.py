"""PoliciesPage: "Conoce y acepta las politicas de tu solicitud".

Es la vista Policies del front (app-cre-solicitud, src/views/Policies), la
misma para Cupo (/cupo-de-credito/politicas) y Consumo
(/consumo/{slug}/politicas). Todo el contenido sale de Drupal, asi que se
localiza por estructura y no por texto:
  - documentos: cada uno es un rich text (<p>, con <a> si tiene enlace)
  - pregunta de salud (solo Consumo): Switch con un boton por opcion,
    data-name = id del campo de Drupal y clase 'selected' en la elegida
  - casillas: Checkbox de MUI con su texto al lado
  - Continuar: dos botones (Button.Primary en movil, Button.Arrow en
    escritorio); el CSS muestra uno segun el ancho
"""
import re

from ..base_page import BasePage
from ..core import reporte as log

TITULO = "#root-content h2"
DOCUMENTOS = "#root-content h2 + div > div"
OPCIONES_SWITCH = "button[data-name]"
CASILLAS = "#root-content input[type='checkbox']"
CONTINUAR = "//button[normalize-space(.)='Continuar']"


def limpio(texto):
    return re.sub(r"\s+", " ", texto or "").strip()


class PoliciesPage(BasePage):

    def pulsar(self, locator):
        """Toque en movil emulado, clic en escritorio."""
        (locator.tap if self.driver.dispositivo else locator.click)()
        return self

    def wait_loaded(self, segundos=30):
        self.loc(CASILLAS).first.wait_for(state="attached", timeout=segundos * 1000)
        return self

    def get_title(self):
        """El h2 de la vista nueva; la de la rama qa (Cupo) lo pinta en un <p>."""
        return limpio(self.page.evaluate(
            "() => (document.querySelector('#root-content h2')"
            " || document.querySelector('#root-content p') || {}).innerText || ''"))

    def get_documents(self):
        """[(texto, href o None)] en el orden de la pantalla. La vista nueva
        pinta rich text de Drupal (un documento puede no tener enlace); la de
        la rama qa, solo enlaces."""
        return [(limpio(d["texto"]), d["href"]) for d in self.page.evaluate(
            """(sel) => {
                 const items = [...document.querySelectorAll(sel)];
                 if (items.length) return items.map(e => { const a = e.querySelector('a');
                   return {texto: e.innerText, href: a ? a.getAttribute('href') : null}; });
                 return [...document.querySelectorAll('#root-content a')]
                   .map(a => ({texto: a.innerText, href: a.getAttribute('href')}));
               }""", DOCUMENTOS)]

    def get_question(self):
        """Texto de la pregunta que va sobre el switch ('' si no hay switch)."""
        if not self.loc(OPCIONES_SWITCH).count():
            return ""
        return limpio(self.loc(OPCIONES_SWITCH).first.evaluate(
            "b => b.parentElement.parentElement.previousElementSibling?.innerText || ''"))

    def get_options(self):
        """[(texto, seleccionada)] de la pregunta de salud."""
        return [(limpio(o["texto"]), o["sel"]) for o in self.loc(OPCIONES_SWITCH).evaluate_all(
            "els => els.map(b => ({texto: b.innerText, sel: b.classList.contains('selected')}))")]

    def option(self, texto):
        return self.loc(OPCIONES_SWITCH).filter(has_text=re.compile(r"^\s*%s\s*$" % re.escape(texto)))

    def select_option(self, texto):
        self.pulsar(self.option(texto).first)
        self.page.wait_for_timeout(300)
        log.info("Opcion '%s' elegida" % texto)
        return self

    def get_checkboxes(self):
        """[(texto, marcada)] de las casillas visibles."""
        return [(limpio(c["texto"]), c["marcada"]) for c in self.loc(CASILLAS).evaluate_all(
            "els => els.map(i => ({marcada: i.checked,"
            " texto: i.closest('.MuiCheckbox-root').parentElement.innerText}))")]

    def checkbox(self, indice):
        return self.loc(CASILLAS).nth(indice)

    def set_checkbox(self, indice, marcada):
        casilla = self.checkbox(indice)
        if casilla.is_checked() != marcada:
            self.pulsar(casilla)
            self.page.wait_for_timeout(200)
        return self

    def checkbox_text(self, indice):
        """El texto que acompana la casilla (hermano del Checkbox de MUI)."""
        return self.checkbox(indice).locator(
            "xpath=ancestor::span[contains(@class,'MuiCheckbox-root')]/following-sibling::*[1]")

    def document_links(self):
        enlaces = self.loc(DOCUMENTOS + " a").all()
        return enlaces or self.loc("#root-content a").all()

    def layout(self):
        """Medidas en px CSS de lo que importa para ver si la pantalla cabe y se
        puede tocar: viewport, scroll y la caja de cada elemento."""
        return self.page.evaluate("""() => {
          const caja = el => { const b = el.getBoundingClientRect();
            return {x: b.left, y: b.top, w: b.width, h: b.height, r: b.right}; };
          const todos = s => [...document.querySelectorAll(s)];
          const visible = el => !!(el.offsetWidth || el.offsetHeight);
          const textos = todos('#root-content *').filter(e => visible(e)
            && [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()));
          return {
            ancho: innerWidth, scrollAncho: document.documentElement.scrollWidth,
            elementos: [
              ...todos('#root-content h2').map(e => ['titulo', caja(e)]),
              ...todos('%(docs)s').map(e => ['documento ' + e.innerText.trim().slice(0, 30), caja(e)]),
              ...todos('%(opciones)s').map(e => ['opcion ' + e.innerText.trim(), caja(e)]),
              ...todos('#root-content .MuiCheckbox-root').map((e, i) => ['casilla ' + (i + 1), caja(e)]),
              ...todos('button').filter(b => visible(b) && b.innerText.trim() === 'Continuar')
                 .map(b => ['Continuar', caja(b)]),
            ],
            letraMinima: Math.min(...textos.map(e => parseFloat(getComputedStyle(e).fontSize))),
          };
        }""" % {"docs": DOCUMENTOS, "opciones": OPCIONES_SWITCH})

    def accessibility(self):
        """Lo que un lector de pantalla puede saber de las casillas y de Si/No."""
        return self.page.evaluate("""() => ({
          casillas: [...document.querySelectorAll('#root-content input[type=checkbox]')].map(i =>
            ({etiquetas: i.labels.length, ariaLabel: i.getAttribute('aria-label') || '',
              ariaLabelledby: i.getAttribute('aria-labelledby') || ''})),
          opciones: [...document.querySelectorAll('%s')].map(b =>
            ({texto: b.innerText.trim(), ariaPressed: b.getAttribute('aria-pressed'),
              ariaChecked: b.getAttribute('aria-checked'), role: b.getAttribute('role')})),
        })""" % OPCIONES_SWITCH)

    def get_continue_buttons(self):
        """[(visible, habilitado)] de los dos botones Continuar."""
        return [(b["visible"], not b["disabled"]) for b in self.loc(CONTINUAR).evaluate_all(
            "els => els.map(b => ({disabled: b.disabled,"
            " visible: !!(b.offsetWidth || b.offsetHeight) &&"
            " getComputedStyle(b).visibility !== 'hidden'}))")]

    def continue_enabled(self):
        """El estado del Continuar que se ve (el otro lo oculta el CSS)."""
        visibles = [hab for vis, hab in self.get_continue_buttons() if vis]
        return bool(visibles) and all(visibles)

    def click_continue(self):
        for boton in self.loc(CONTINUAR).all():
            if boton.is_visible():
                boton.click()
                log.info("Click en 'Continuar'")
                return self
        raise AssertionError("No hay un boton 'Continuar' visible")

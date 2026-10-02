"""OnboardingPage: los 3 pasos previos al login, de Cupo y de Consumo.

Reemplaza a SolicitudCreditoOnboarding1/2/3 y SolicitudCupoCredito, que
buscaban textos que ya no existen ("¡Empieza tu solicitud digital!",
"Cupo de Crédito en tu Tarjeta de Afiliación"). El contenido sale de Drupal,
asi que aqui solo se localiza por los botones y se leen los textos.
"""
from ..base_page import BasePage
from ..core import reporte as log
from ..core.enums import WaitStrategy

SIGUIENTE = "//button[normalize-space(.)='Siguiente']"
VOLVER = "//button[normalize-space(.)='Volver']"
COMENZAR_SOLICITUD = "//button[normalize-space(.)='Comenzar solicitud']"


class OnboardingPage(BasePage):

    def wait_loaded(self, segundos=30):
        self.await_visible(self.loc("button:visible").first, segundos)
        return self

    def get_title(self):
        parrafos = self.loc("p").all_inner_texts()
        return parrafos[1].strip() if len(parrafos) > 1 else ""

    def get_items(self):
        """Textos de las vinetas del paso actual (los que llegan de Drupal)."""
        return [t.strip() for t in
                self.loc("//img[@alt='bullet item']/following-sibling::div").all_inner_texts()]

    def get_visible_text(self):
        return self.page.inner_text("body")

    def is_last_step(self):
        return self.loc(COMENZAR_SOLICITUD).count() > 0

    def click_next(self):
        self.click(self.loc(SIGUIENTE).first, WaitStrategy.CLICKABLE, "Siguiente")
        self.page.wait_for_timeout(600)
        return self

    def click_back(self):
        self.click(self.loc(VOLVER).first, WaitStrategy.CLICKABLE, "Volver")
        self.page.wait_for_timeout(600)
        return self

    def click_start_request(self):
        self.click(self.loc(COMENZAR_SOLICITUD).first, WaitStrategy.CLICKABLE,
                   "Comenzar solicitud")
        return self

    def walk_steps(self, max_pasos=5):
        """Avanza con 'Siguiente' hasta el paso de 'Comenzar solicitud'.
        Devuelve [(titulo, texto_visible)] de cada paso visto."""
        pasos = []
        for _ in range(max_pasos):
            self.wait_loaded()
            pasos.append((self.get_title(), self.get_visible_text()))
            if self.is_last_step():
                break
            self.click_next()
        log.info("Pasos del Onboarding: %s" % " | ".join(t for t, _ in pasos))
        return pasos

"""TermsAndConditionsPage: modal post-login, politicas y dialogo de Gigya."""
from ..base_page import ESPERA_PAGINA, BasePage
from ..core import reporte as log
from ..core.enums import WaitStrategy

CONTINUE_REQUEST_BUTTON = ("//button[.//span[contains(@class, 'MuiTypography-root') "
                           "and text()='Continuar solicitud']]")
INCREASE_QUOTA_MODAL_TITLE = ("//p[contains(@class, 'MuiTypography-root') and "
                              "contains(normalize-space(.), 'aumenta tu Cupo de Crédito')]")
INCREASE_QUOTA_MODAL_SUBTITLE = ("//p[contains(normalize-space(.), "
                                 "'Ya tienes un cupo con Colsubsidio que puedes aumentar')]")
TERMS_CHECKBOX_WRAPPER = ".MuiCheckbox-root.PrivateSwitchBase-root"
TERMS_CHECKBOX = (".MuiCheckbox-root.PrivateSwitchBase-root "
                  "input.PrivateSwitchBase-input[type='checkbox']")
ARROW_RIGHT_BUTTON = "svg[orientation='right']"
# Por el texto visible, no por las clases css-* (hashes de emotion/MUI).
PRIVACY_NOTICE_LINK = "//a[contains(normalize-space(.), 'Aviso de privacidad')]"
GIGYA_DIALOG_CLOSE = ("//div[contains(@class, 'gigya-screen-dialog-close')]"
                      "//a[@aria-label='close window']")


class TermsAndConditionsPage(BasePage):

    def click_continue_request_if_present(self):
        """'Continuar solicitud' solo sale en algunos estados; si no esta, se omite."""
        boton = self.loc(CONTINUE_REQUEST_BUTTON).first
        try:
            boton.wait_for(state="visible", timeout=ESPERA_PAGINA * 1000)
            self.click(boton, WaitStrategy.CLICKABLE)
            log.pass_("'Continuar solicitud' button clicked")
        except Exception:
            log.info("'Continuar solicitud' button not displayed - step skipped")
        return self

    def click_privacy_notice_link(self):
        """Dispara el evento de Politicas (label=enlaces politicas). Abre el PDF
        en otra pestana; lo que interesa es el dataLayer.push del click."""
        enlace = self.loc(PRIVACY_NOTICE_LINK).first
        try:
            enlace.wait_for(state="visible", timeout=ESPERA_PAGINA * 1000)
            self.click(enlace, WaitStrategy.CLICKABLE)
            log.pass_("'Aviso de privacidad' link clicked")
        except Exception:
            log.info("'Aviso de privacidad' link not displayed - step skipped")
        return self

    def validate_increase_quota_modal_content(self):
        esperado_titulo = "aumenta tu Cupo de Crédito"
        esperado_subtitulo = ("Ya tienes un cupo con Colsubsidio que puedes aumentar. "
                              "Continúa y conoce el resultado de tu solicitud.")
        try:
            titulo_loc = self.loc(INCREASE_QUOTA_MODAL_TITLE).first
            titulo_loc.wait_for(state="visible", timeout=15000)
            titulo = titulo_loc.inner_text().strip()
            subtitulo = self.loc(INCREASE_QUOTA_MODAL_SUBTITLE).first.inner_text().strip()
            if esperado_titulo in titulo and subtitulo == esperado_subtitulo:
                log.pass_("Increase Quota modal content validated | Title: '%s' | Subtitle: '%s'"
                          % (titulo, subtitulo))
            else:
                log.fail("Increase Quota modal content mismatch | Title: '%s' (expected to "
                         "contain '%s') | Subtitle: '%s' (expected '%s')"
                         % (titulo, esperado_titulo, subtitulo, esperado_subtitulo))
        except Exception as e:
            log.fail("Increase Quota modal not displayed: %s" % str(e).split("\n")[0])
        return self

    def accept_terms_checkbox(self):
        caja = self.first_visible(TERMS_CHECKBOX_WRAPPER, 8) or self.loc(TERMS_CHECKBOX_WRAPPER).first
        try:
            caja.wait_for(state="visible", timeout=8000)
            self.click(caja, WaitStrategy.CLICKABLE)
            log.pass_("Terms checkbox marked")
        except Exception:
            log.info("Terms checkbox not displayed - step skipped")
        return self

    def click_arrow_right(self):
        flecha = self.loc(ARROW_RIGHT_BUTTON).first
        try:
            flecha.wait_for(state="visible", timeout=ESPERA_PAGINA * 1000)
            self.click(flecha, WaitStrategy.CLICKABLE)
            log.pass_("Arrow right button clicked")
        except Exception:
            log.info("Terms checkbox not displayed - step skipped")
        return self

    def close_gigya_dialog_if_present(self):
        """Cierra el dialogo 'Completa tu perfil' de Gigya si aparece (sale
        asincrono despues del login y solo a algunos usuarios)."""
        cerrar = self.loc(GIGYA_DIALOG_CLOSE).first
        try:
            cerrar.wait_for(state="visible", timeout=15000)
            try:
                cerrar.click(timeout=5000)
            except Exception:
                cerrar.evaluate("el => el.click()")
            log.pass_("Gigya dialog closed")
        except Exception:
            log.info("Gigya dialog not displayed - step skipped")
        return self

    def is_terms_page_displayed(self):
        try:
            return self.loc(CONTINUE_REQUEST_BUTTON).first.is_visible()
        except Exception:
            return False

    def is_terms_section_present(self):
        """True solo si el checkbox de politicas se ve. Sale despues de las
        validaciones de backend (SAP, listas, ASCARD, SIIF): 10-20 s."""
        if self.first_visible(TERMS_CHECKBOX_WRAPPER, 25):
            log.info("Terms-and-conditions section present")
            return True
        log.info("Terms-and-conditions section not present - terms steps will be skipped")
        return False

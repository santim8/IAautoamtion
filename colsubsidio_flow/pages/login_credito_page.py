"""LoginCreditoPage: formulario CIAM (screen-set de Gigya) de la solicitud."""
import base64
import json
import time
from datetime import datetime

from ..base_page import ESPERA_PAGINA, BasePage
from ..core import reporte as log
from ..core.enums import WaitStrategy

ESPERA_MS = ESPERA_PAGINA * 1000

CONTINUE_REQUEST_BUTTON = "//button[.//span[normalize-space(text())='Continuar solicitud']]"
# Gigya pinta varias pantallas del screen-set y deja ocultas las que no usa:
# ':visible' toma la que se ve (el @FindBy de Java tomaba la primera del DOM).
DROPDOWN_DOCUMENT_TYPE = "select[name='data.tpIdentificacion'][data-screenset-roles='instance']"
INPUT_IDENTIFICATION = "input[name='data.numeroDocumento'][data-screenset-roles='instance']:visible"
INPUT_PASSWORD = "#custom-login--password"
SUBMIT_BUTTON = "input[type='submit'][value='Iniciar sesión']:visible"
TERMS_CHECKBOX = ".MuiCheckbox-root input[type='checkbox']"
TERMS_CHECKBOX_WRAPPER = ".MuiCheckbox-root"
ARROW_RIGHT_BUTTON = "//button[.//svg[@orientation='right']] | //svg[@orientation='right']"
GIGYA_ERROR = ".gigya-error-msg-active"
# customer.documentType del JWT (jwtTypes.ts del front): 2 = CC, 3 = CE.
TIPO_DOC_JWT = {"CC": 2, "CE": 3}
# /api/auth/session fija la cookie con maxAge ONE_HOUR.
VIDA_COOKIE_S = 3600


def decode_jwt(token):
    """Payload del JWT sin verificar firma, igual que jwt.decode() del front."""
    parte = token.split(".")[1]
    parte += "=" * (-len(parte) % 4)
    return json.loads(base64.urlsafe_b64decode(parte))


class LoginCreditoPage(BasePage):

    def wait_form_visible(self, segundos=45):
        """El screen-set de Gigya carga asincrono despues del SDK."""
        self.await_visible(self.loc(INPUT_IDENTIFICATION).first, segundos)
        log.pass_("Formulario CIAM visible")
        return self

    def select_document_type(self, tipo):
        log.info("-> selectDocumentType: %s" % tipo)
        if not tipo or tipo.upper() == "CC":
            log.info("selectDocumentType skipped -- default CC")
            return self
        dropdown = self.loc(DROPDOWN_DOCUMENT_TYPE).first
        dropdown.wait_for(state="visible", timeout=ESPERA_MS)
        dropdown.select_option(value=tipo.upper())
        log.pass_("Document type selected: %s" % tipo)
        return self

    def enter_identification(self, identificacion):
        campo = self.loc(INPUT_IDENTIFICATION).first
        campo.wait_for(state="visible", timeout=30000)
        campo.click()
        campo.fill("")
        campo.press_sequentially(identificacion)
        log.pass_("Identification entered: %s" % identificacion)
        return self

    def enter_password(self, clave):
        log.info("-> enterPassword")
        self.send_keys(INPUT_PASSWORD, WaitStrategy.VISIBLE, clave, ocultar=True)
        return self

    def click_submit(self):
        log.info("-> clickSubmit")
        self.click(self.loc(SUBMIT_BUTTON).first, WaitStrategy.CLICKABLE)
        log.pass_("Login form submitted")
        return self

    def click_arrow_right(self):
        self.click(self.loc(ARROW_RIGHT_BUTTON).first, WaitStrategy.CLICKABLE)
        log.pass_("Arrow right button clicked")
        return self

    def get_login_errors(self):
        return [t.strip() for t in self.loc(GIGYA_ERROR).all_inner_texts() if t.strip()]

    def get_user_token_cookie(self, segundos=15):
        """Espera la cookie userToken, que el front fija al terminar el login."""
        fin = time.time() + segundos
        while time.time() < fin:
            valor = self.driver.cookies().get("userToken")
            if valor:
                log.pass_("userToken cookie captured (length: %d)" % len(valor))
                log.info_token("userToken", valor)
                return valor
            time.sleep(0.5)
        errores = self.get_login_errors()
        log.fail("userToken cookie not found after login"
                 + (" -- Gigya: %s" % "; ".join(errores) if errores else ""))
        return None

    def validate_user_token(self, tipo, numero):
        """Revisa la cookie userToken y el JWT que lleva adentro. El front no
        verifica la firma (solo decodifica y mira exp); la firma la valida el
        backend en cada llamada. Nunca imprime el token ni datos personales."""
        cookie = next((c for c in self.driver.context.cookies() if c["name"] == "userToken"), None)
        if not cookie:
            log.fail("Token: no hay cookie userToken")
            return self
        ahora = time.time()

        def check(ok, texto):
            (log.pass_ if ok else log.fail)("Token: " + texto)

        check(cookie.get("httpOnly"), "cookie HttpOnly=%s" % cookie.get("httpOnly"))
        check(cookie.get("secure"), "cookie Secure=%s" % cookie.get("secure"))
        log.info("Token: cookie SameSite=%s Path=%s" % (cookie.get("sameSite"), cookie.get("path")))
        vida = cookie.get("expires", -1) - ahora
        check(0 < vida <= VIDA_COOKIE_S + 60,
              "cookie vence en %d min (esperado <= 60)" % (vida // 60))

        try:
            payload = decode_jwt(cookie["value"])
        except Exception as e:
            log.fail("Token: no es un JWT decodificable (%s)" % e)
            return self
        cliente = payload.get("customer") or {}
        exp, iat = payload.get("exp"), payload.get("iat")
        log.info("Token: claims=%s | customer=%s" % (sorted(payload), sorted(cliente)))
        if exp and iat:
            log.info("Token: iat=%s exp=%s (dura %d min)" % (
                datetime.fromtimestamp(iat).isoformat(" ", "seconds"),
                datetime.fromtimestamp(exp).isoformat(" ", "seconds"), (exp - iat) // 60))
        check(bool(exp) and exp > ahora, "JWT vigente (exp en el futuro)")
        check(str(cliente.get("documentNumber")) == numero,
              "customer.documentNumber es el del usuario logueado (%s)" % numero)
        esperado = TIPO_DOC_JWT.get(tipo.upper())
        check(cliente.get("documentType") == esperado,
              "customer.documentType=%s (esperado %s para %s)"
              % (cliente.get("documentType"), esperado, tipo))
        return self

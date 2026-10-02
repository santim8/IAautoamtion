"""RequestCreditStep1: formulario de solicitud de Cupo, de contacto a la
Thank You Page (/cupo-de-credito/fin)."""
import time

from ..base_page import ESPERA_PAGINA, BasePage, xpath_literal
from ..core import reporte as log
from ..core.enums import WaitStrategy

# OJO: los ids :rN: los genera React y cambian entre renders/versiones (ver
# feedback_mui_locators). Se dejan como en Java hasta poder ver el DOM logueado
# y cambiarlos por label/aria-labelledby.
NUMERO_TELEFONO_LABEL = "[id=':r0:-label']"
INPUT_NUMERO_TELEFONO = "[id=':r0:']"
INPUT_CONFIRMAR_TELEFONO = "[id=':r1:']"
CORREO_LABEL = "[id=':r3:-label']"
INPUT_CORREO = "[id=':r3:']"
CONFIRMAR_CORREO_LABEL = "[id=':r4:-label']"
INPUT_CONFIRMAR_CORREO = "[id=':r4:']"

BUTTON_CONTINUAR = "//button[.//span[.//p[text()='Continuar']]]"
BACK_BUTTON = "//button[.//span[normalize-space(.)='Volver']]"
ABANDON_REQUEST_BUTTON = "#exitButton button"
PAGO_ARRIENDO_RADIO = "[id='Pago arriendo']"
OPTION_OBRA_LABOR = "//p[text()='Por obra o labor']"
INPUT_AMOUNT_MONTH = "//input[@type='currencyCOPCustom']"
DROPDOWN_ESTADO_CIVIL = "//label[@id='civilStatus']/following-sibling::div//div[@role='combobox']"
DROPDOWN_NIVEL_ESTUDIO = "//label[@id='educationLevel']/following-sibling::div//div[@role='combobox']"
OPTIONS_LISTBOX = "//ul[@role='listbox']/li"
SOY_PROPIETARIO_RADIO = "//p[text() = 'Pago arriendo']"
TIPO_VIVIENDA_LABEL = "//p[text() = '¿Cuál es tu tipo de vivienda?']"
AJUSTAR_CUPO_OPTION = "//button[.//p[normalize-space(.)='Ajustar cupo']]"
CLOSE_MODAL_BUTTON = "//img[@alt='close-circle']"
ACEPTAR_CUPO_BUTTON = "//button[.//span[normalize-space(.)='Aceptar el Cupo de Crédito']]"
CUOTA_MANEJO_BUTTON = "//button[.//p[normalize-space(.)='Cuota de manejo mensual']]"
ENTENDIDO_BUTTON = "//button[.//span[normalize-space(.)='Entendido']]"
TASA_NMV_LABEL = "//p[normalize-space(.)='Tasa N.M.V.']"
SALIR_SIN_AJUSTAR_BUTTON = "//p[normalize-space(.)='Salir sin ajustar']"
SEGUROS_MENSUALES_LABEL = "//p[normalize-space(.)='Seguros mensuales']"
QUE_ES_FECHA_CORTE_BUTTON = "//span[normalize-space(.)='¿Qué es la fecha de corte?']"
AUTORIZACION_RETENCION_BUTTON = "//span[normalize-space(.)='Autorización de retención del subsidio']"
# Case-insensitive: el CMS a veces lo manda como "Continuar Solicitud".
CONTINUAR_SOLICITUD_BUTTON = (
    "//button[.//span[contains(@class,'MuiTypography-root') and "
    "translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', "
    "'abcdefghijklmnopqrstuvwxyz')='continuar solicitud']]")

# Thank You Page
CONOCE_SERVICIOS_EN_LINEA_BUTTON = "//button[.//p[normalize-space(.)='Conoce servicios en línea']]"
CONOCE_COMERCIOS_ALIADOS_LINK = "//span[normalize-space(.)='Conoce comercios aliados']"
IR_A_CENTRO_DE_AYUDA_LINK = "//span[normalize-space(.)='Ir a centro de ayuda']"

CONTINUE_BUTTON = "//button[.//span[normalize-space(.)='Continuar']]"
FIXED_FEE_RADIO = "//input[@id='Paga una cuota fija']"
# css-zqsopu es un hash de emotion: inestable, igual que en Java.
FINAL_TERMS_CHECKBOX = "//div[contains(@class,'css-zqsopu')]//input[@type='checkbox']"
LISTBOX = "//ul[@role='listbox']"
IDENTITY_VERIFICATION_TITLE = "//p[normalize-space(.)='Verifica tu identidad desde el celular']"

ESPERA_MS = ESPERA_PAGINA * 1000


class RequestCreditStep1(BasePage):

    # ------------------------------------------------------------ contacto

    def enter_phone_number(self, texto):
        log.info("-> enterPhoneNumber: %s" % texto)
        self.loc(INPUT_NUMERO_TELEFONO).wait_for(state="visible", timeout=50000)
        self.send_keys(INPUT_NUMERO_TELEFONO, WaitStrategy.VISIBLE, texto)
        self.loc(INPUT_NUMERO_TELEFONO).press("Tab")
        return self

    def enter_confirm_phone_number(self, texto):
        """El campo de confirmacion se habilita con el blur del primario y no
        responde a un type normal: native setter (feedback_react_selenium)."""
        log.info("-> enterConfirmPhoneNumber: %s" % texto)
        try:
            self._esperar_habilitado(INPUT_CONFIRMAR_TELEFONO)
            self.set_native_value(INPUT_CONFIRMAR_TELEFONO, texto)
            log.pass_("Confirmar telefono ingresado via JS")
        except Exception as e:
            log.fail("enterConfirmPhoneNumber failed on locator {%s}: %s"
                     % (INPUT_CONFIRMAR_TELEFONO, str(e).split("\n")[0]))
        return self

    def get_number_phone_label_text(self):
        return self.loc(NUMERO_TELEFONO_LABEL).inner_text()

    def enter_confirmation_email(self, texto):
        self.send_keys(INPUT_CONFIRMAR_CORREO, WaitStrategy.VISIBLE, texto)
        return self

    def enter_email(self, texto):
        log.info("-> enterEmail: %s" % texto)
        self.send_keys(INPUT_CORREO, WaitStrategy.VISIBLE, texto)
        self.loc(INPUT_CORREO).press("Tab")
        return self

    def enter_confirm_email(self, texto):
        log.info("-> enterConfirmEmail: %s" % texto)
        try:
            self._esperar_habilitado(INPUT_CONFIRMAR_CORREO)
            self.set_native_value(INPUT_CONFIRMAR_CORREO, texto)
            log.pass_("Confirmar correo ingresado via JS")
        except Exception as e:
            log.fail("enterConfirmEmail failed on locator {%s}: %s"
                     % (INPUT_CONFIRMAR_CORREO, str(e).split("\n")[0]))
        return self

    def get_email_label_text(self):
        return self.loc(CORREO_LABEL).inner_text()

    def get_confirm_email_label_text(self):
        return self.loc(CONFIRMAR_CORREO_LABEL).inner_text()

    # ---------------------------------------------------------- navegacion

    def click_next_button(self):
        log.info("-> clickNextButton")
        self.click(self.loc(BUTTON_CONTINUAR).first, WaitStrategy.CLICKABLE)
        return self

    def click_back_button(self):
        log.info("-> clickBackButton (Volver)")
        self._esperar_habilitado(BACK_BUTTON)
        self.click_with_fallback(self.loc(BACK_BUTTON).first)
        log.pass_("Boton 'Volver' clickeado")
        return self

    def click_abandon_request(self):
        log.info("-> clickAbandonRequest (Abandonar solicitud)")
        self._esperar_habilitado(ABANDON_REQUEST_BUTTON)
        self.click_with_fallback(self.loc(ABANDON_REQUEST_BUTTON).first)
        log.pass_("Boton 'Abandonar solicitud' clickeado")
        return self

    def close_initial_modal_if_present(self):
        """Cierra la X (close-circle) del modal inicial si hay una visible."""
        visible = self.first_visible(CLOSE_MODAL_BUTTON, 20)
        if visible is None:
            log.info("Modal inicial no presente - paso omitido")
            return self
        self.click_with_fallback(visible)
        log.pass_("Modal inicial del formulario cerrado")
        return self

    def click_continue(self):
        self._esperar_habilitado(CONTINUE_BUTTON)
        self.click_with_fallback(self.loc(CONTINUE_BUTTON).first)
        log.pass_("Boton Continuar clickeado")
        return self

    def click_continue_after_wait(self, segundos):
        self._esperar_habilitado(CONTINUE_BUTTON, segundos + 30)
        self.click_with_fallback(self.loc(CONTINUE_BUTTON).first)
        log.pass_("Boton Continuar clickeado tras espera de %ss" % segundos)
        return self

    # ---------------------------------------------------------------- cupo

    def click_ajustar_cupo(self):
        self._esperar_habilitado(AJUSTAR_CUPO_OPTION, 60)
        self.click(self.loc(AJUSTAR_CUPO_OPTION).first, WaitStrategy.CLICKABLE)
        return self

    def close_adjust_quota_modal(self):
        cerrar = self.loc(CLOSE_MODAL_BUTTON).first
        cerrar.wait_for(state="visible", timeout=60000)
        cerrar.scroll_into_view_if_needed()
        try:
            cerrar.click(timeout=5000)
        except Exception:
            boton = cerrar.locator("xpath=./ancestor::button[1]")
            objetivo = boton if boton.count() else cerrar
            objetivo.evaluate("el => el.click()")
        log.pass_("Modal de ajuste de cupo cerrado")
        return self

    def select_fixed_fee_payment(self):
        radio = self.loc(FIXED_FEE_RADIO).first
        radio.wait_for(state="attached", timeout=ESPERA_MS)
        self.click_with_fallback(radio)
        log.pass_("Opcion de pago 'Paga una cuota fija' seleccionada")
        return self

    def click_accept_quota(self):
        self._esperar_habilitado(ACEPTAR_CUPO_BUTTON, 60)
        self.click_with_fallback(self.loc(ACEPTAR_CUPO_BUTTON).first)
        log.pass_("Cupo de Credito aceptado")
        return self

    def get_tasa_nmv_text(self):
        try:
            etiqueta = self.loc(TASA_NMV_LABEL).first
            etiqueta.wait_for(state="visible", timeout=ESPERA_MS)
            texto = etiqueta.inner_text().strip()
            log.info("Tasa N.M.V. text: %s" % texto)
            return texto
        except Exception as e:
            log.warning("Tasa N.M.V. label not visible: %s" % str(e).split("\n")[0])
            return ""

    # Botones opcionales: si no aparecen en 8 s se omiten sin fallar.

    def click_cuota_manejo(self):
        return self._click_opcional(CUOTA_MANEJO_BUTTON, "Cuota de manejo mensual")

    def click_entendido(self):
        return self._click_opcional(ENTENDIDO_BUTTON, "Entendido")

    def click_salir_sin_ajustar(self):
        return self._click_opcional(SALIR_SIN_AJUSTAR_BUTTON, "Salir sin ajustar")

    def click_seguros_mensuales(self):
        return self._click_opcional(SEGUROS_MENSUALES_LABEL, "Seguros mensuales")

    def click_que_es_la_fecha_de_corte(self):
        return self._click_opcional(QUE_ES_FECHA_CORTE_BUTTON, "¿Qué es la fecha de corte?")

    def click_autorizacion_retencion_subsidio(self):
        return self._click_opcional(AUTORIZACION_RETENCION_BUTTON,
                                    "Autorización de retención del subsidio")

    def click_continuar_solicitud(self):
        return self._click_opcional(CONTINUAR_SOLICITUD_BUTTON, "Continuar solicitud")

    # ----------------------------------------------------------- PEP y fin

    def select_pep_answer(self, data_name, respuesta):
        opcion = ("//button[@data-name=%s and .//p[normalize-space(.)=%s]]"
                  % (xpath_literal(data_name), xpath_literal(respuesta)))
        self._esperar_habilitado(opcion)
        self.click_with_fallback(self.loc(opcion).first)
        log.pass_("Pregunta PEP '%s' respondida: %s" % (data_name, respuesta))
        return self

    def mark_final_terms_checkbox(self):
        caja = self.loc(FINAL_TERMS_CHECKBOX).first
        caja.wait_for(state="attached", timeout=ESPERA_MS)
        self.click_with_fallback(caja)
        log.pass_("Checkbox de terminos finales marcado")
        return self

    def validate_identity_verification_title(self):
        esperado = "Verifica tu identidad desde el celular"
        titulo = self.loc(IDENTITY_VERIFICATION_TITLE).first
        try:
            titulo.wait_for(state="visible", timeout=40000)
        except Exception as e:
            log.fail("Identity verification title not displayed: '%s'" % esperado)
            raise AssertionError("Identity verification title not displayed: '%s'"
                                 % esperado) from e
        actual = titulo.inner_text().strip()
        if actual != esperado:
            log.fail("Identity verification title mismatch | expected '%s' but got '%s'"
                     % (esperado, actual))
            raise AssertionError("Identity verification title mismatch: expected '%s' "
                                 "but got '%s'" % (esperado, actual))
        log.pass_("Identity verification title displayed: '%s'" % actual)
        return self

    def click_conoce_servicios_en_linea(self):
        return self._click_obligatorio(CONOCE_SERVICIOS_EN_LINEA_BUTTON,
                                       "Conoce servicios en línea")

    def click_conoce_comercios_aliados(self):
        return self._click_obligatorio(CONOCE_COMERCIOS_ALIADOS_LINK, "Conoce comercios aliados")

    def click_ir_a_centro_de_ayuda(self):
        return self._click_obligatorio(IR_A_CENTRO_DE_AYUDA_LINK, "Ir a centro de ayuda")

    # ------------------------------------------------------ datos personales

    def validate_housing_type_label(self):
        self.get_text(TIPO_VIVIENDA_LABEL, WaitStrategy.VISIBLE, "Label_Tipo_Vivienda")
        self.click(SOY_PROPIETARIO_RADIO, WaitStrategy.CLICKABLE)
        return self

    def select_option_housing_type_label(self):
        self.click(SOY_PROPIETARIO_RADIO, WaitStrategy.CLICKABLE)
        return self

    def select_option_obra_labor(self):
        self.click(OPTION_OBRA_LABOR, WaitStrategy.CLICKABLE)
        return self

    def enter_monthly_income(self, texto):
        log.info("-> enterMonthlyIncome: %s" % texto)
        self.send_keys(INPUT_AMOUNT_MONTH, WaitStrategy.VISIBLE, texto)
        return self

    def enter_monthly_income_salary(self, texto):
        log.info("-> enterMonthlyIncomeSalary: %s" % texto)
        try:
            self.loc(INPUT_AMOUNT_MONTH).wait_for(state="visible", timeout=ESPERA_MS)
            self.set_native_value(INPUT_AMOUNT_MONTH, texto)
            self.loc(INPUT_AMOUNT_MONTH).press("Tab")
            log.pass_("Ingreso mensual ingresado via JS: %s" % texto)
        except Exception as e:
            log.fail("enterMonthlyIncomeSalary failed on locator {%s}: %s"
                     % (INPUT_AMOUNT_MONTH, str(e).split("\n")[0]))
        return self

    def open_marital_status_dropdown(self):
        log.info("-> openMaritalStatusDropdown")
        self.click(DROPDOWN_ESTADO_CIVIL, WaitStrategy.CLICKABLE)
        log.pass_("Dropdown estado civil abierto")
        return self

    def open_education_level_dropdown(self):
        log.info("-> openEducationLevelDropdown")
        self.click(DROPDOWN_NIVEL_ESTUDIO, WaitStrategy.CLICKABLE)
        log.pass_("Dropdown nivel de estudio abierto")
        return self

    def select_option_marital_status(self, opcion):
        self._select_listbox_option_by_text(opcion, "Estado Civil")
        return self

    def select_option_education_level(self, opcion):
        self._select_listbox_option_by_text(opcion, "Nivel de Estudio")
        return self

    # ------------------------------------------------------------- privados

    def _select_listbox_option_by_text(self, texto, dropdown):
        opcion = "//ul[@role='listbox']/li[normalize-space(.)=%s]" % xpath_literal(texto)
        try:
            self.loc(LISTBOX).wait_for(state="visible", timeout=ESPERA_MS)
            objetivo = self.loc(opcion).first
            objetivo.wait_for(state="visible", timeout=ESPERA_MS)
            try:
                objetivo.click(timeout=5000)
            except Exception:
                objetivo.evaluate("el => el.click()")
            self.loc(LISTBOX).wait_for(state="hidden", timeout=ESPERA_MS)
            log.pass_("%s - opcion seleccionada: %s" % (dropdown, texto))
        except Exception as e:
            mensaje = ("No se pudo seleccionar la opcion '%s' en el dropdown %s: %s"
                       % (texto, dropdown, str(e).split("\n")[0]))
            log.fail(mensaje)
            raise RuntimeError(mensaje) from e

    def _esperar_habilitado(self, selector, segundos=ESPERA_PAGINA):
        """elementToBeClickable: visible y habilitado."""
        locator = self.loc(selector).first
        locator.wait_for(state="visible", timeout=segundos * 1000)
        fin = time.time() + segundos
        while not locator.is_enabled():
            if time.time() >= fin:
                raise TimeoutError("%s visible pero deshabilitado" % selector)
            self.page.wait_for_timeout(250)
        return locator

    def _click_opcional(self, selector, nombre):
        try:
            self._esperar_habilitado(selector, 8)
            self.click_with_fallback(self.loc(selector).first)
            log.pass_("Boton '%s' clickeado" % nombre)
        except Exception:
            log.info("Boton '%s' no presente - paso omitido" % nombre)
        return self

    def _click_obligatorio(self, selector, nombre):
        log.info("-> click %s" % nombre)
        self._esperar_habilitado(selector)
        self.click_with_fallback(self.loc(selector).first)
        log.pass_("'%s' clickeado" % nombre)
        return self

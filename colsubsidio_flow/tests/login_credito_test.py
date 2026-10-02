"""LoginCreditoTest (testID 10024): login + solicitud de Cupo completa hasta
la verificacion de identidad, y biometria por API con el idCaso real."""
from .. import _rutas  # noqa: F401
from ..core import reporte as log
from ..core.enums import EnumsDropdowns, TipoSolicitud
from ..pages import LoginCreditoPage, RequestCreditStep1, TermsAndConditionsPage
from ..preconditions import TestPreconditions

NOMBRE = "LoginCredito"
TEST_ID = "10024"
AUTORES = "Santiago Correa"
CATEGORIAS = ("SMOKE", "REGRESSION")
DATA_PROVIDER = "login_credito"
URL = "https://d2b80yrnend1dj.cloudfront.net/loans-dev-solicitud/login"


def run(driver, usuario, opciones):
    login = LoginCreditoPage(driver)
    terms = TermsAndConditionsPage(driver)
    solicitud = RequestCreditStep1(driver)

    # Solo AUMENTO (2) / REACTIVACION (3) ven "Continuar solicitud" y el modal
    # "aumenta tu Cupo de Credito"; el tipo sale de card-validations v2.
    pre = TestPreconditions.for_user(usuario.tipo, usuario.numero)
    aumento_o_reactivacion = pre.is_tipo_solicitud(TipoSolicitud.AUMENTO,
                                                   TipoSolicitud.REACTIVACION)

    (login
     .action_message("Opening Credito login page - %s" % usuario.documento)
     .select_document_type(usuario.tipo)
     .enter_identification(usuario.numero)
     .enter_password(usuario.clave)
     .take_screenshot_report("Login form filled - %s" % usuario.documento)
     .click_submit()
     .action_message("Login submitted"))

    (terms
     .close_gigya_dialog_if_present()
     .take_screenshot_report("Modal is opened")
     .run_if(aumento_o_reactivacion, TermsAndConditionsPage.click_continue_request_if_present)
     .run_if(aumento_o_reactivacion, TermsAndConditionsPage.validate_increase_quota_modal_content))

    # Solo se acepta y se pulsa la flecha si la seccion de politicas se pinto;
    # si no, la flecha deshabilitada da "click intercepted".
    terminos = terms.is_terms_section_present()
    (terms
     .run_if(terminos, TermsAndConditionsPage.accept_terms_checkbox)
     .run_if(terminos, TermsAndConditionsPage.click_arrow_right))

    correo = "test%s@example.com" % usuario.numero[-4:]
    (solicitud
     .action_message("The form is open")
     .enter_phone_number("3001234567")
     .enter_confirm_phone_number("3001234567")
     .enter_email(correo)
     .enter_confirm_email(correo)
     .take_screenshot_report("Request Credit Form 1")
     .click_next_button()
     .open_marital_status_dropdown()
     .select_option_marital_status(EnumsDropdowns.SOLTERO.value)
     .take_screenshot_report("Request Credit Form 2")
     .click_next_button()
     .enter_monthly_income("100000000")
     .take_screenshot_report("Request Credit Form 3")
     .click_next_button()
     .take_screenshot_report("Validation Modify Quota"))

    id_caso = solicitud.wait_for_offer_case_id("/request/offer/", 100)
    log.info("idCaso: %s" % id_caso)

    (solicitud
     .select_fixed_fee_payment()
     .click_accept_quota()
     .take_screenshot_report("Cupo aceptado")
     .click_continue()
     .select_pep_answer("managePublicResources", "No")
     .select_pep_answer("hasPoliticPower", "No")
     .select_pep_answer("hasPublicPresence", "No")
     .take_screenshot_report("Preguntas PEP respondidas")
     .click_continue()
     .mark_final_terms_checkbox()
     .take_screenshot_report("Terminos finales")
     .click_continue()
     .click_continue_after_wait(5)
     .action_message("Flujo de solicitud completado")
     .validate_identity_verification_title()
     .take_screenshot_and_save_it_local("take the last screenshot"))

    # Biometria/firma por API con el idCaso real (BiometryFlow.run en Java).
    if id_caso and not opciones.get("sin_biometria"):
        import biometria_api
        biometria_api.biometry_flow(id_caso, usuario.numero)

    (solicitud
     .action_message("Screen final")
     .delay(3000)
     .save_current_url()
     .take_screenshot_report("Screen Final"))

    # Limpieza en Bizagi: en Java estaba comentada (BizagiCancelCaseFlow).
    # Equivalente en el repo: python bizagi_cancel_case.py

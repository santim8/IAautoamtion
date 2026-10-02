"""LoginCreditoLightTest (testID 10025): el flujo UI completo de Cupo sin
validar servicios (ni card-validations, ni validate-request, ni biometria).
Con --capturas DIR deja un pantallazo por pantalla para revisarlas despues."""
from ..core.enums import EnumsDropdowns
from ..pages import LoginCreditoPage, RequestCreditStep1, TermsAndConditionsPage

NOMBRE = "LoginCreditoLight"
TEST_ID = "10025"
AUTORES = "Santiago Correa"
CATEGORIAS = ("SMOKE",)
DATA_PROVIDER = "login_credito"
URL = "https://dev.colsubsidio.com/creditos/solicitud/login"


def run(driver, usuario, opciones):
    login = LoginCreditoPage(driver)
    terms = TermsAndConditionsPage(driver)
    solicitud = RequestCreditStep1(driver)
    tag = usuario.numero

    # 01. Login
    (login
     .action_message("Opening Credito login page - " + tag)
     .take_screenshot_and_save_it_local("01_login_empty_" + tag)
     .select_document_type(usuario.tipo)
     .enter_identification(usuario.numero)
     .enter_password(usuario.clave)
     .take_screenshot_and_save_it_local("02_login_filled_" + tag)
     .click_submit())

    # 02. Politicas / modal
    (terms
     .close_gigya_dialog_if_present()
     .take_screenshot_and_save_it_local("03_after_login_modal_" + tag))
    terminos = terms.is_terms_section_present()
    (terms
     .run_if(terminos, TermsAndConditionsPage.accept_terms_checkbox)
     .take_screenshot_and_save_it_local("04_terms_accepted_" + tag)
     .run_if(terminos, TermsAndConditionsPage.click_arrow_right))

    # 03. Contacto
    correo = "test%s@example.com" % tag[-4:]
    (solicitud
     .action_message("Form contacto - " + tag)
     .take_screenshot_and_save_it_local("05_form_contact_empty_" + tag)
     .enter_phone_number("3001234567")
     .enter_confirm_phone_number("3001234567")
     .enter_email(correo)
     .enter_confirm_email(correo)
     .take_screenshot_and_save_it_local("06_form_contact_filled_" + tag)
     .click_next_button())

    # 04. Estado civil
    (solicitud
     .open_marital_status_dropdown()
     .select_option_marital_status(EnumsDropdowns.SOLTERO.value)
     .take_screenshot_and_save_it_local("07_marital_status_" + tag)
     .click_next_button())

    # 05. Ingresos
    (solicitud
     .enter_monthly_income("100000000")
     .take_screenshot_and_save_it_local("08_monthly_income_" + tag)
     .click_next_button())

    # 06. Ajuste de cupo
    (solicitud
     .take_screenshot_and_save_it_local("09_quota_screen_" + tag)
     .select_fixed_fee_payment()
     .click_accept_quota()
     .take_screenshot_and_save_it_local("10_quota_accepted_" + tag)
     .click_continue())

    # 07. PEP
    (solicitud
     .select_pep_answer("managePublicResources", "No")
     .select_pep_answer("hasPoliticPower", "No")
     .select_pep_answer("hasPublicPresence", "No")
     .take_screenshot_and_save_it_local("11_pep_answered_" + tag)
     .click_continue())

    # 08. Terminos finales
    (solicitud
     .mark_final_terms_checkbox()
     .take_screenshot_and_save_it_local("12_final_terms_" + tag)
     .click_continue()
     .take_screenshot_and_save_it_local("13_after_final_terms_" + tag)
     .click_continue_after_wait(5))

    # 09. Verificacion de identidad (sin biometria por API)
    (solicitud
     .action_message("Identity verification screen - " + tag)
     .delay(3000)
     .take_screenshot_and_save_it_local("14_identity_verification_" + tag))

    # 10. Pantalla final
    (solicitud
     .delay(3000)
     .save_current_url()
     .take_screenshot_and_save_it_local("15_final_screen_" + tag))

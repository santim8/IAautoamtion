"""CiamLoginDataLayerTest (testID 10027): login en CIAM y evento 'login'
del dataLayer (label=exitoso, user_status=autenticado)."""
import json

from ..core import datalayer
from ..core import reporte as log
from ..pages import LoginCreditoPage

NOMBRE = "CiamLoginDataLayer"
TEST_ID = "10027"
AUTORES = "Santiago Correa"
CATEGORIAS = ("SMOKE", "REGRESSION")
DATA_PROVIDER = "login_credito"
URL = "https://dev.colsubsidio.com/creditos/solicitud/login"


def run(driver, usuario, opciones):
    # El monitor va ANTES del login para capturar el push posterior.
    datalayer.install(driver)
    log.info("dataLayer monitor instalado")

    (LoginCreditoPage(driver)
     .action_message("CIAM login - %s" % usuario.documento)
     .select_document_type(usuario.tipo)
     .enter_identification(usuario.numero)
     .enter_password(usuario.clave)
     .click_submit()
     .action_message("Login enviado - esperando evento dataLayer 'login'"))

    evento = datalayer.wait_for_event_named(driver, "login", 40)
    assert evento is not None, "No se capturo el evento 'login' del dataLayer tras el login en CIAM"
    log.info("Evento login capturado: %s" % json.dumps(evento, ensure_ascii=False))

    assert str(evento.get("label")) == "exitoso", \
        "El evento 'login' no reporta label='exitoso' (llego %r)" % evento.get("label")
    assert str(evento.get("user_status")) == "autenticado", \
        "El evento 'login' no reporta user_status='autenticado' (llego %r)" % evento.get("user_status")
    log.pass_("Evento 'login' del dataLayer validado correctamente")

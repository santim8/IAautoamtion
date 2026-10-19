"""Catalogo del observador: que se mira, como se trata y con que tiempos.

Todo lo que cambia cuando cambia el flujo vive aqui, no en el codigo de
captura: un endpoint nuevo, un disparador de pantallazo o un endpoint que
necesita trato especial se agregan en este archivo.
"""
import os

import rutas

# Nombre con el que se invoca al observador (mensajes de ayuda y el HAR).
SCRIPT = "observador_flujo.py"

# Hosts del backend que interesan (match por substring sobre la URL).
# Sacados de bruno/validate-request/.
HOSTS_DEFAULT = [
    "colsubsidio-test.apigee.net",
    "platform-test-external.colsubsidio.com",
    "platform-test-internal.colsubsidio.com",
    "dev.colsubsidio.com",
    "d2b80yrnend1dj.cloudfront.net",
]

# Rutas de la aplicacion, una por despliegue. Es lo que --solo-url usa por
# defecto para reconocer la pestana del flujo.
RUTAS_APP = ["creditos/solicitud", "loans-dev-solicitud"]

# Endpoints de negocio que interesan (match por substring sobre la URL).
# Login de Gigya (CIAM). Su respuesta trae el documento del afiliado, con el
# que --request-check consulta la retoma apenas se loguea.
LOGIN_GIGYA = "/accounts.login"

# Espejo de TRACKED_ENDPOINTS del framework Java, para poder comparar 1:1.
ENDPOINTS_RASTREADOS = [
    "/decision-engine",
    "validate-request",
    "/eligibility/external/v2/affiliation-validations",
    "/card-validations",
    "/eligibility/external/v1/product-validations",
    "/eligibility/external/v1/campaigns/",
    "/eligibility/internal/v1/campaigns/",
    "/request/validate-request",
    "/external/v1/product/2/request/offer-config",
    "/request/offer/",
    "/loans/req-mgr/external/v1/product/2/request/offer-config",
    "/loans/req-mgr/external/v1/product/2/request/request-data",
    "/request/request-data",
    "/request/cancel-request",
    "/request/decision-engine/start",
    "/loans/loan-util/external/modification-quota-amount",
    LOGIN_GIGYA,     # fuera del espejo Java, ver REGLAS_ENDPOINT
]

# Trato especial por endpoint (patron -> reglas). Un endpoint nuevo que lo
# necesite se agrega aqui; el codigo de captura solo pregunta por la regla
# (ver endpoints.tiene_regla).
#
#   sin_payload       su payload NUNCA se guarda, ni con --sin-redactar. Se
#                     queda la respuesta (redactada como cualquier otra).
#   cuerpo_inmediato  el front recarga la pagina apenas responde. Al recargar,
#                     Chrome descarta el cuerpo de la respuesta y leido desde
#                     el loop llegaba tarde ("body no disponible"): se lee
#                     dentro del handler.
REGLAS_ENDPOINT = {
    # el login de Gigya manda loginID y password en form-urlencoded, que la
    # redaccion por clave JSON no alcanza; despues el front recarga /login
    LOGIN_GIGYA: {"sin_payload", "cuerpo_inmediato"},
}

MAX_BODY = 200_000     # bytes; mas alla de esto se trunca
MAX_BODY_HTML = 8_000  # lo que se pinta en reporte.html (el resto, en requests.jsonl)

# Tipos de recurso cuyo cuerpo no aporta a una evidencia de QA. Los bundles JS
# solos pesaban decenas de MB. Se guardan igual el metodo, la URL y el status.
TIPOS_SIN_CUERPO = {"image", "font", "media", "stylesheet", "script", "manifest"}

# Margen para decidir a que pantalla pertenece un request que arranca justo
# antes de que la SPA cambie de ruta. La app suele disparar la peticion de datos
# de la pantalla nueva unas decenas de ms ANTES del pushState, asi que sin este
# margen ese trafico queda archivado en la pantalla anterior.
TOLERANCIA_CAMBIO_MS = 300

# Un request que el navegador corta (CORS, red caida) llega por dos vias: el
# requestfailed de Playwright y, por la sesion CDP propia, el status que el
# servidor si respondio. Se espera este margen antes de registrarlo para que
# las dos hayan hablado.
ESPERA_FALLO_MS = 400
# Requests que la sesion CDP recuerda mientras se sabe si fallan o no.
MAX_CDP_RED = 500
# Lo que CDP vio terminar y Playwright no reporto en este margen se registra
# desde CDP (ver red.CapturaRed.drenar_huerfanos). Holgado: Playwright lee el
# body en el loop.
ESPERA_HUERFANO_S = 2.0
# Lo que quedo sin respuesta al cerrar el observador.
SIN_RESPUESTA = "sin respuesta"

# Contrato observado de cada servicio. Vive en el repo (no en evidences/) porque
# es lo que se compara entre corridas y lo que se revisa en un PR. Se ESCRIBE
# con --generar-esquemas, asi que va a BASE: dentro del .exe seria una carpeta
# temporal que se borra al cerrar.
ESQUEMAS_DEFAULT = os.path.join(rutas.BASE, "esquemas_servicios.json")

# Servicios cuya respuesta pinta una pantalla que vale la pena dejar retratada
# en ese instante. Todos son OPCIONALES: si el flujo no pasa por esa pantalla
# el servicio no responde y simplemente no hay pantallazo, sin ruido. El orden
# es el del reporte: el primero que haya en un paso es la imagen principal.
SHOT_RESPUESTA_DEFAULT = ",".join([
    "request/offer",                 # personalizacion de oferta
    "parametros/estado_civil",       # datos personales; a veces se omite
    "modification-quota-amount",     # modificacion del cupo en personalizacion
    "creditos/solicitud/login",      # pantalla de login (documento)
    "accounts.login",                # login de Gigya (CIAM)
])

# Disparadores tras los que la app recarga la pagina (patron -> metodo que
# dispara): despues del login de Gigya el front recarga /login, y retratarla
# dentro del handler colgaba el screenshot hasta el timeout. Se retratan desde
# el loop cuando la pantalla se asienta, reintentando sin limite de tiempo (ver
# pantallazos.Pantallazos.tomar_tarde). Solo cuenta la respuesta del POST: es
# la del login.
SHOT_TRAS_RECARGA = {"accounts.login": "POST"}
# Tope del intervalo entre reintentos de un pantallazo que no sale: cada
# intento fallido bloquea el loop hasta el timeout del screenshot.
MAX_REINTENTO_SHOT_MS = 10_000

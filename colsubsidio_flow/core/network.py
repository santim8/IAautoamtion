"""NetworkInterceptorManager: esperar a que un servicio responda 200.

En Java se leia el performance log de Chrome (que se consume al leerlo); aqui
se mira la lista de respuestas que el Driver registra desde que abrio.
"""
import time
from enum import Enum

# Hosts de backend que cuentan como "servicio" (isTrackedEndpoint).
HOSTS_BACKEND = ("platform-test-external.colsubsidio.com",
                 "platform-test-internal.colsubsidio.com",
                 "colsubsidio-test.apigee.net")


class OkOutcome(Enum):
    ALREADY_RESPONDED = "ALREADY_RESPONDED"
    RESPONDED_AFTER_WAIT = "RESPONDED_AFTER_WAIT"
    TIMEOUT = "TIMEOUT"


def _url_ok(driver, fragmento):
    for r in driver.respuestas:
        if fragmento in r["url"] and r["status"] == 200:
            return r["url"]
    return None


def await_service_ok(driver, fragmento, timeout_s):
    if _url_ok(driver, fragmento):
        return OkOutcome.ALREADY_RESPONDED
    fin = time.time() + timeout_s
    while time.time() < fin:
        driver.page.wait_for_timeout(500)
        if _url_ok(driver, fragmento):
            return OkOutcome.RESPONDED_AFTER_WAIT
    return OkOutcome.TIMEOUT


def await_service_ok_get_url(driver, fragmento, timeout_s):
    fin = time.time() + timeout_s
    while True:
        url = _url_ok(driver, fragmento)
        if url or time.time() >= fin:
            return url
        driver.page.wait_for_timeout(500)


def extract_failed_requests(driver):
    """Respuestas de backend con status >= 400 (FailedRequest en Java)."""
    return [r for r in driver.respuestas
            if any(h in r["url"] for h in HOSTS_BACKEND) and r["status"] >= 400]

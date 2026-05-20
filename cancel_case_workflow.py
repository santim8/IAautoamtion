"""
Workflow: consulta caso en Bizagi (headless) y luego lo cancela via API.

Uso:
    python cancel_case_workflow.py <document_number> <token>
    python cancel_case_workflow.py CE <document_number> <token>

El token se vence cada 2 horas; proporcionarlo como argumento cada vez.
"""

import sys
import logging
import json
import urllib.request
import urllib.error

from bizagi_automator import BizagiAutomator

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

CANCEL_URL = (
    "https://platform-test-external.colsubsidio.com"
    "/loans/req-mgr/external/v1/product/2/request/cancel-request"
)


def cancelar_caso(id_caso: str, token: str) -> bool:
    payload = json.dumps({"idCaso": id_caso}).encode("utf-8")
    headers = {
        "authorization": token,
        "content-type": "application/json",
    }
    req = urllib.request.Request(CANCEL_URL, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode("utf-8")
            log.info("Respuesta HTTP %s: %s", resp.status, body)
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        log.error("HTTP %s al cancelar caso %s: %s", e.code, id_caso, body)
        return False
    except urllib.error.URLError as e:
        log.error("Error de red al cancelar caso %s: %s", id_caso, e.reason)
        return False


def main() -> None:
    args = sys.argv[1:]

    if len(args) == 2:
        document_type = "CC"
        document_number, token = args
    elif len(args) == 3 and args[0].upper() == "CE":
        document_type = "CE"
        _, document_number, token = args
    else:
        print("Uso: python cancel_case_workflow.py [CE] <document_number> <token>")
        sys.exit(1)

    log.info("=== PASO 1: Consultando caso en Bizagi (headless) ===")
    automator = BizagiAutomator(document_number, document_type)
    id_caso = automator.abrir_pagina(headless=True)

    if not id_caso:
        log.error("No se obtuvo idCaso desde Bizagi. Abortando cancelación.")
        sys.exit(1)

    log.info("=== PASO 2: Cancelando caso %s via API ===", id_caso)
    ok = cancelar_caso(id_caso, token)

    if ok:
        print(f"\n[OK] Caso {id_caso} cancelado correctamente.")
    else:
        print(f"\n[FAIL] Fallo la cancelacion del caso {id_caso}.")
        sys.exit(1)


if __name__ == "__main__":
    main()

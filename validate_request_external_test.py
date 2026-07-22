"""
Test del servicio validate-request EXTERNAL v1.
JWT leido desde token.txt -> campo jwt_validate_request_external (expira ~5min segun exp del JWT).

Endpoint:
    POST /loans/req-mgr/external/v1/product/2/request/validate-request

Uso:
    python validate_request_external_test.py
"""

import json
import subprocess
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

URL = "https://platform-test-external.colsubsidio.com/loans/req-mgr/external/v1/product/2/request/validate-request"


def _load_token() -> str:
    token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.txt")
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("jwt_validate_request_external="):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    raise RuntimeError(
        "Falta 'jwt_validate_request_external' en token.txt. "
        "El JWT del entorno external tiene un exp corto; actualizarlo si devuelve 401/403."
    )


JWT = _load_token()


# Cedulas autorizadas (ver feedback_solo_datos_autorizados.md).
# tipoSolicitud asignada segun codigo ASCARD del documento:
#   1 = Originacion (cupo nuevo)
#   2 = Aumento     (codigos ASCARD 1, N, S)
#   3 = Reactivacion (codigos ASCARD O, V, I, W)
TEST_CASES = [
    {"tipo": "CO1C", "numero": "41336668",   "canalOrigen": "WEB", "tipoSolicitud": "3",
     "descripcion": "Reactivacion V - Devolucion Voluntaria",          "status_esperado": 202},
    {"tipo": "CO1C", "numero": "51760693",   "canalOrigen": "WEB", "tipoSolicitud": "3",
     "descripcion": "Reactivacion V - Devolucion Voluntaria",          "status_esperado": 202},
    {"tipo": "CO1C", "numero": "1140814422", "canalOrigen": "WEB", "tipoSolicitud": "2",
     "descripcion": "Aumento codigo 1 - Normal",                       "status_esperado": 202},
    {"tipo": "CO1C", "numero": "1095915781", "canalOrigen": "WEB", "tipoSolicitud": "3",
     "descripcion": "Reactivacion I + tarjetaAmparada (bloqueado)",    "status_esperado": 200},
    {"tipo": "CO1C", "numero": "1097397286", "canalOrigen": "WEB", "tipoSolicitud": "2",
     "descripcion": "Aumento codigo 1 - tarjeta estado S",             "status_esperado": 202},
    {"tipo": "CO1C", "numero": "52634111",   "canalOrigen": "WEB", "tipoSolicitud": "3",
     "descripcion": "Reactivacion I + tarjetaAmparada (bloqueado)",    "status_esperado": 200},
    {"tipo": "CO1C", "numero": "52966724",   "canalOrigen": "WEB", "tipoSolicitud": "2",
     "descripcion": "Aumento codigo 1 - tarjeta estado 0",             "status_esperado": 202},
    {"tipo": "CO1C", "numero": "79528108",   "canalOrigen": "WEB", "tipoSolicitud": "3",
     "descripcion": "Reactivacion I - Inactivo",                       "status_esperado": 202},
]


def _curl(payload: dict) -> tuple[int, dict | str]:
    cmd = [
        "curl", "-sS", "-o", "-", "-w", "\n__STATUS__:%{http_code}",
        "--request", "POST",
        "--url", URL,
        "--header", f"authorization: {JWT}",
        "--header", "content-type: application/json",
        "--header", "cookie: AWSALBAPP-0=_remove_; AWSALBAPP-1=_remove_; AWSALBAPP-2=_remove_; AWSALBAPP-3=_remove_",
        "--data", json.dumps(payload),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    raw = result.stdout
    status = 0
    body = raw
    if "__STATUS__:" in raw:
        body, status_part = raw.rsplit("__STATUS__:", 1)
        body = body.rstrip("\n")
        try:
            status = int(status_part.strip())
        except ValueError:
            status = 0
    try:
        return status, json.loads(body) if body else {}
    except json.JSONDecodeError:
        return status, body


def _run_case(tc: dict) -> bool:
    payload = {
        "documento": {"tipo": tc["tipo"], "numero": tc["numero"]},
        "canalOrigen": tc["canalOrigen"],
        "tipoSolicitud": tc["tipoSolicitud"],
    }
    log.info("=" * 70)
    log.info("TC: %s", tc["descripcion"])
    log.info("Request: %s", json.dumps(payload, ensure_ascii=False))

    status, body = _curl(payload)
    log.info("HTTP %s", status)
    log.info("Response: %s", json.dumps(body, ensure_ascii=False, indent=2) if isinstance(body, dict) else body)

    ok = status == tc["status_esperado"]
    log.info("Resultado: %s (esperado HTTP %s)", "PASS" if ok else "FAIL", tc["status_esperado"])
    return ok


def main() -> None:
    results = [(tc["descripcion"], _run_case(tc)) for tc in TEST_CASES]
    log.info("=" * 70)
    log.info("RESUMEN")
    for desc, ok in results:
        log.info("  %s  %s", "PASS" if ok else "FAIL", desc)
    total = len(results)
    passed = sum(1 for _, ok in results if ok)
    log.info("Total: %d  PASS: %d  FAIL: %d", total, passed, total - passed)


if __name__ == "__main__":
    main()

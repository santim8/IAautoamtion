"""
Test del servicio card-validations (app-cre-product-eligibility-api).
Poblar TEST_CASES con los datos de prueba antes de ejecutar.

Uso:
    python card_validations_test.py
"""

import json
import subprocess
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

URL = "https://platform-test-internal.colsubsidio.com/loans/eligibility/internal/v1/card-validations"


def _load_api_key() -> str:
    token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.txt")
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("api_key_card_validations="):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    raise RuntimeError(
        "Falta 'api_key_card_validations' en token.txt. "
        "Agregar la linea: api_key_card_validations=<API_KEY>"
    )


API_KEY = _load_api_key()

DOC_TYPE_MAP = {
    "CC": "CO1C",
    "CE": "CO1E",
}

# ---------------------------------------------------------------------------
# Poblar con los datos de prueba:
# {
#   "tipo": "CC" o "CE",
#   "numero": "12345678",
#   "descripcion": "descripción del escenario",
#   "esperado": {                        <- opcional, para validación automática
#       "tipoSolicitud": 3,              <- valor esperado en la respuesta
#       "estado": "OK"                   <- "OK" o "VALIDATION_ERROR"
#   }
# }
# ---------------------------------------------------------------------------
TEST_CASES = [
    {"tipo": "CC", "numero": "19184974",   "descripcion": "CC 19184974"},
    {"tipo": "CC", "numero": "20156603",   "descripcion": "CC 20156603"},
    {"tipo": "CC", "numero": "52526685",   "descripcion": "CC 52526685"},
    {"tipo": "CC", "numero": "80833648",   "descripcion": "CC 80833648"},
    {"tipo": "CE", "numero": "382429",     "descripcion": "CE 382429"},
    {"tipo": "CC", "numero": "382429",     "descripcion": "CC 382429"},
    {"tipo": "CC", "numero": "1023944601", "descripcion": "CC 1023944601"},
    {"tipo": "CC", "numero": "19246507",   "descripcion": "CC 19246507"},
    {"tipo": "CC", "numero": "1024539415", "descripcion": "CC 1024539415"},
    {"tipo": "CC", "numero": "1013595547", "descripcion": "CC 1013595547"},
    {"tipo": "CC", "numero": "52634111",   "descripcion": "CC 52634111"},
    {"tipo": "CC", "numero": "547911",     "descripcion": "CC 547911"},
    {"tipo": "CC", "numero": "79584194",   "descripcion": "CC 79584194"},
    {"tipo": "CC", "numero": "11259747",   "descripcion": "CC 11259747"},
    {"tipo": "CC", "numero": "51760693",   "descripcion": "CC 51760693"},
    {"tipo": "CC", "numero": "1095915781", "descripcion": "CC 1095915781"},
    {"tipo": "CC", "numero": "79528108",   "descripcion": "CC 79528108"},
    {"tipo": "CC", "numero": "1140814422", "descripcion": "CC 1140814422"},
    {"tipo": "CC", "numero": "80810798",   "descripcion": "CC 80810798"},
    {"tipo": "CC", "numero": "41336668",   "descripcion": "CC 41336668"},
]


def call_service(tipo: str, numero: str) -> dict:
    doc_tipo = DOC_TYPE_MAP.get(tipo.upper(), tipo)
    payload = json.dumps({"documento": {"tipo": doc_tipo, "numero": numero}})
    cmd = [
        "curl", "--silent", "--write-out", "\n%{http_code}",
        "--request", "POST",
        "--url", URL,
        "--header", "content-type: application/json",
        "--header", f"x-api-key: {API_KEY}",
        "--header", "user-agent: insomnia/11.2.0",
        "--data", payload,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        output = result.stdout.strip().rsplit("\n", 1)
        body_raw = output[0] if len(output) > 1 else ""
        status_code = int(output[-1]) if output[-1].isdigit() else None
        try:
            body = json.loads(body_raw)
        except Exception:
            body = body_raw
        return {"status_code": status_code, "body": body}
    except Exception as e:
        return {"status_code": None, "body": str(e)}


def validate(response: dict, esperado: dict) -> tuple[bool, str]:
    if not esperado:
        return True, "sin validacion automatica"

    body = response.get("body", {})
    errores = []

    if "estado" in esperado:
        estado_real = body.get("estado") or body.get("status")
        if estado_real != esperado["estado"]:
            errores.append(f"estado: esperado={esperado['estado']} real={estado_real}")

    if "tipoSolicitud" in esperado:
        tipo_real = body.get("tipoSolicitud")
        if tipo_real != esperado["tipoSolicitud"]:
            errores.append(f"tipoSolicitud: esperado={esperado['tipoSolicitud']} real={tipo_real}")

    if errores:
        return False, " | ".join(errores)
    return True, "ok"


def run():
    if not TEST_CASES:
        print("TEST_CASES esta vacio. Agrega los datos de prueba antes de ejecutar.")
        return

    passed = 0
    failed = 0

    print(f"\n{'='*70}")
    print(f"  card-validations — {len(TEST_CASES)} casos")
    print(f"{'='*70}\n")

    for i, case in enumerate(TEST_CASES, 1):
        tipo = case["tipo"]
        numero = case["numero"]
        descripcion = case.get("descripcion", f"caso {i}")
        esperado = case.get("esperado", {})

        log.info("[%d/%d] %s | %s %s", i, len(TEST_CASES), descripcion, tipo, numero)
        response = call_service(tipo, numero)
        ok, detalle = validate(response, esperado)

        status_icon = "[OK]" if ok else "[FAIL]"
        if ok:
            passed += 1
        else:
            failed += 1

        print(f"{status_icon} [{i}] {descripcion}")
        print(f"      {tipo} {numero} | HTTP {response['status_code']}")
        print(f"      Respuesta: {json.dumps(response['body'], ensure_ascii=False)}")
        if esperado:
            print(f"      Validacion: {detalle}")
        print()

    print(f"{'='*70}")
    print(f"  RESULTADO: {passed} pasaron | {failed} fallaron | {len(TEST_CASES)} total")
    print(f"{'='*70}\n")


if __name__ == "__main__":
    run()

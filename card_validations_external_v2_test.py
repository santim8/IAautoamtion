"""
Test del servicio card-validations EXTERNAL v2.
JWT leido desde token.txt -> campo jwt_card_validations_external_v2 (expira ~2h).

Flags actuales (verificadas 2026-05-25 via endpoints publicos):
    featureFlagIncrement: true
    featureFlagReactivation: true
    GET /loans-cert-admin-solicitud/api_creditos/parametros/feature_flag_increment
    GET /loans-cert-admin-solicitud/api_creditos/parametros/feature_flag_reactivation

Esperados con estas flags:
    - Reactivacion (O, V, I) -> estado: OK, tipoSolicitud: 3
    - Incremento (codigo 1)  -> estado: OK, tipoSolicitud: 2
    - tarjetaAmparada=true   -> estado: VALIDATION_ERROR (siempre)
    - Mora (R, K, J, B, Y, A)-> estado: VALIDATION_ERROR (siempre)
    - Sin tarjeta            -> estado: VALIDATION_ERROR (CARD_STATUS)

Uso:
    python card_validations_external_v2_test.py
"""

import json
import subprocess
import logging
import os

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

URL = "https://platform-test-external.colsubsidio.com/loans/eligibility/external/v2/card-validations"

DOC_TYPE_MAP = {
    "CC": "CO1C",
    "CE": "CO1E",
}


def _load_token() -> str:
    token_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.txt")
    try:
        with open(token_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("jwt_card_validations_external_v2="):
                    return line.split("=", 1)[1].strip()
    except FileNotFoundError:
        pass
    raise RuntimeError(
        "Falta 'jwt_card_validations_external_v2' en token.txt. "
        "El JWT expira cada ~2h; actualizarlo cuando devuelva 401/403."
    )


JWT = _load_token()


_OK_REACT = {"estado": "OK", "tipoSolicitud": 3}
_OK_INCR = {"estado": "OK", "tipoSolicitud": 2}
_BLOQUEADO = {"estado": "VALIDATION_ERROR"}

TEST_CASES = [
    {"tipo": "CC", "numero": "52526685",   "descripcion": "Reactivacion O - CUPO CONGELADO",                "esperado": _OK_REACT},
    {"tipo": "CC", "numero": "51760693",   "descripcion": "Reactivacion V - DEVOLUCION VOLUNTARIA",         "esperado": _OK_REACT},
    {"tipo": "CC", "numero": "41336668",   "descripcion": "Reactivacion V - DEVOLUCION VOLUNTARIA",         "esperado": _OK_REACT},
    {"tipo": "CC", "numero": "79528108",   "descripcion": "Reactivacion I - INACTIVO",                      "esperado": _OK_REACT},
    {"tipo": "CC", "numero": "80810798",   "descripcion": "Incremento 1 - NORMAL",                          "esperado": _OK_INCR},
    {"tipo": "CC", "numero": "1140814422", "descripcion": "Incremento 1 - tarjeta estado 7",                "esperado": _OK_INCR},
    {"tipo": "CC", "numero": "1097397286", "descripcion": "Incremento 1 - tarjeta estado S",                "esperado": _OK_INCR},
    {"tipo": "CC", "numero": "52966724",   "descripcion": "Incremento 1 - tarjeta estado 0",                "esperado": _OK_INCR},
    {"tipo": "CC", "numero": "1023876310", "descripcion": "Incremento 1 - NORMAL",                          "esperado": _OK_INCR},
    {"tipo": "CC", "numero": "52634111",   "descripcion": "tarjetaAmparada=true",                           "esperado": _BLOQUEADO},
    {"tipo": "CC", "numero": "1095915781", "descripcion": "tarjetaAmparada=true",                           "esperado": _BLOQUEADO},
    {"tipo": "CC", "numero": "1013595547", "descripcion": "tarjetaAmparada=true",                           "esperado": _BLOQUEADO},
    {"tipo": "CC", "numero": "20156603",   "descripcion": "tarjetaAmparada=true",                           "esperado": _BLOQUEADO},
    {"tipo": "CC", "numero": "79584194",   "descripcion": "Mora R - REFINANCIADA",                          "esperado": _BLOQUEADO},
    {"tipo": "CC", "numero": "19184974",   "descripcion": "Mora K - CASTIGADA",                             "esperado": _BLOQUEADO},
    {"tipo": "CC", "numero": "19246507",   "descripcion": "Mora J - COBRO PRE JURIDICO",                    "esperado": _BLOQUEADO},
    {"tipo": "CC", "numero": "11259747",   "descripcion": "Mora J - COBRO PRE JURIDICO",                    "esperado": _BLOQUEADO},
    {"tipo": "CC", "numero": "547911",     "descripcion": "Mora B - CANCELADA POR BANCO",                   "esperado": _BLOQUEADO},
    {"tipo": "CC", "numero": "1023944601", "descripcion": "Mora Y - COBRO JURIDICO",                        "esperado": _BLOQUEADO},
    {"tipo": "CC", "numero": "13617086",   "descripcion": "Mora A - POR MORA EN SUS PRODUCTOS",             "esperado": _BLOQUEADO},
    {"tipo": "CC", "numero": "80833648",   "descripcion": "Sin tarjeta (CARD_STATUS)",                      "esperado": _BLOQUEADO},
    {"tipo": "CC", "numero": "1024539415", "descripcion": "Sin tarjeta (CARD_STATUS)",                      "esperado": _BLOQUEADO},
    {"tipo": "CE", "numero": "382429",     "descripcion": "CE sin tarjeta (CARD_STATUS)",                   "esperado": _BLOQUEADO},
]


def call_service(tipo: str, numero: str) -> dict:
    doc_tipo = DOC_TYPE_MAP.get(tipo.upper(), tipo)
    payload = json.dumps({"documento": {"tipo": doc_tipo, "numero": numero}})
    cmd = [
        "curl", "--silent", "--write-out", "\n%{http_code}",
        "--request", "POST",
        "--url", URL,
        "--header", "content-type: application/json",
        "--header", f"authorization: {JWT}",
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
    if not isinstance(body, dict):
        return False, f"body no es JSON: {body}"

    resultado_val = body.get("resultadoValidacion", {}) if isinstance(body.get("resultadoValidacion"), dict) else {}
    datos_error = resultado_val.get("datosError", {}) if isinstance(resultado_val.get("datosError"), dict) else {}

    estado_real = (
        resultado_val.get("estado")
        or body.get("estado")
        or body.get("status")
    )
    tipo_real = (
        resultado_val.get("tipoSolicitud")
        if resultado_val.get("tipoSolicitud") is not None
        else body.get("tipoSolicitud")
    )
    codigo_real = datos_error.get("codigoErrorValidacion") or body.get("codigoErrorValidacion")

    errores = []
    if "estado" in esperado and estado_real != esperado["estado"]:
        errores.append(f"estado: esperado={esperado['estado']} real={estado_real}")
    if "tipoSolicitud" in esperado and tipo_real != esperado["tipoSolicitud"]:
        errores.append(f"tipoSolicitud: esperado={esperado['tipoSolicitud']} real={tipo_real}")
    if "codigoErrorValidacion" in esperado and codigo_real != esperado["codigoErrorValidacion"]:
        errores.append(f"codigoErrorValidacion: esperado={esperado['codigoErrorValidacion']} real={codigo_real}")

    if errores:
        return False, " | ".join(errores)
    return True, f"ok (estado={estado_real}, tipoSolicitud={tipo_real})"


def run():
    if not TEST_CASES:
        print("TEST_CASES esta vacio. Agrega los datos de prueba antes de ejecutar.")
        return

    passed = 0
    failed = 0

    print(f"\n{'='*70}")
    print(f"  card-validations EXTERNAL v2 - {len(TEST_CASES)} casos")
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

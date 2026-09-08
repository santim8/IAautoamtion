#!/usr/bin/env python3
"""Valida un documento contra los servicios de elegibilidad de credito, en
Python puro, sin pasar por colsubsidioFramework/Maven.

Puerto de ApiTest.testValidationServices (colsubsidioFramework): pega
directo a los mismos endpoints REST que corria Maven/TestNG. Igual que
card_validations_test.py, usa `curl` via subprocess (no requests/urllib)
porque el WAF de AWS bloquea esos clientes con 403, y el header
`user-agent: insomnia/11.2.0` si pasa.

Imprime `[EXCEL_UPDATE] Thread:N doc - servicio - estado` por cada
resultado, el mismo formato que ya lee panel_observador.py (clase
Validaciones) via RE_EXCEL -- asi la tabla, los colores y el export a Excel
del panel no necesitan cambios.

Uso:
    python validaciones_api.py [--hilos N] TIPO:NUMERO [TIPO:NUMERO ...]
    python validaciones_api.py CC:52526685 CE:382429
"""
import argparse
import base64
import json
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode

BASE_APIGEE = "https://colsubsidio-test.apigee.net"
BASE_INT = "https://platform-test-internal.colsubsidio.com"
BASE_EXT = "https://platform-test-external.colsubsidio.com"

TOKEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.txt")

# Los 4 mapeos de tipo de documento del framework Java (cada servicio usa el
# suyo). El repo solo trae usuarios CC/CE hoy, asi que alcanza con esos dos
# por mapeo; un tipo no soportado se salta con SKIP en vez de reventar.
DOC_TYPE_SERVICES = {"CC": "CO1C", "CE": "CO1E"}           # la mayoria de servicios
DOC_TYPE_LOGIN = {"CC": "2", "CE": "3"}                    # solo login SSO
DOC_TYPE_VALIDATE_REQUEST = {"CC": "CO1C", "CE": "CO1E"}   # solo Validate Request
DOC_TYPE_PREAPPROVED = {"CC": "1", "CE": "2"}              # solo Preapproved


def _cargar_token_txt():
    valores = {}
    try:
        with open(TOKEN_PATH, encoding="utf-8") as f:
            for linea in f:
                if "=" in linea:
                    clave, _, valor = linea.strip().partition("=")
                    valores[clave.strip()] = valor.strip()
    except OSError:
        pass
    return valores


_SECRETOS = _cargar_token_txt()


def _secreto(clave):
    valor = _SECRETOS.get(clave)
    if not valor:
        raise RuntimeError(
            "Falta '%s' en token.txt. Agregar la linea: %s=<valor>" % (clave, clave))
    return valor


API_KEY_ELIGIBILITY = None   # se resuelve en main(), no al importar


# El panel arranca este script sin consola propia (viene de una app de
# ventana): cada curl.exe que se lanza sin este flag se abre SU PROPIA
# consola nueva porque no hay ninguna que heredar. Con --hilos 5 y ~9
# llamadas por documento eso es un fogonazo de consolas por corrida.
_SIN_VENTANA = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


# --- HTTP: curl via subprocess, igual que card_validations_test.py --------
def _curl(metodo, url, headers=None, body=None, params=None, timeout=20):
    """Pega el WAF de AWS sin el header insomnia/11.2.0; con el, pasa.
    Devuelve (status_code, cuerpo_parseado_o_texto)."""
    if params:
        url = url + ("&" if "?" in url else "?") + urlencode(params)
    cmd = ["curl", "--silent", "--show-error", "--write-out", "\n%{http_code}",
           "--request", metodo, "--url", url,
           "--header", "accept: application/json",
           "--header", "user-agent: insomnia/11.2.0"]
    for k, v in (headers or {}).items():
        cmd += ["--header", "%s: %s" % (k, v)]
    if body is not None:
        # content-type solo cuando hay JSON de verdad: el token de Apigee
        # (POST sin cuerpo) espera form-urlencoded -- el default de curl
        # cuando se manda --data sin content-type explicito -- y forzar
        # aqui application/json lo hacia fallar con 500 ExtractVariables.
        cmd += ["--header", "content-type: application/json", "--data", json.dumps(body)]
    elif metodo == "POST":
        # Apigee exige Content-Length incluso en un POST sin cuerpo; sin
        # --data curl no lo manda y responde 411.
        cmd += ["--data", ""]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           creationflags=_SIN_VENTANA)
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e)
    salida = r.stdout.strip().rsplit("\n", 1)
    crudo = salida[0] if len(salida) > 1 else ""
    status = int(salida[-1]) if salida[-1].isdigit() else None
    try:
        cuerpo = json.loads(crudo) if crudo else {}
    except json.JSONDecodeError:
        cuerpo = crudo
    return status, cuerpo


def _interpretar_validacion(status, cuerpo, codigo_ok=200):
    """PASS/FAIL/PARTIAL segun resultadoValidacion.estado, igual que
    ReportUtils.getValidationStatusFromResponse/...DetailsFromResponse en
    Java. Sirve para Validation Bizagi, Card Validation, Siif Validation,
    Restrictive List y Validate Request."""
    resultado = cuerpo.get("resultadoValidacion") if isinstance(cuerpo, dict) else None
    if not isinstance(resultado, dict):
        return ("PASS" if status == codigo_ok else "FAIL"), "HTTP %s" % status
    estado = resultado.get("estado")
    if estado == "OK":
        return "PASS", "HTTP %s estado OK" % status
    if estado == "VALIDATION_ERROR":
        validacion = resultado.get("validacion")
        detalle = "HTTP %s estado: VALIDATION_ERROR" % status
        if validacion:
            detalle += " - %s" % validacion
        return "FAIL", detalle
    if estado:
        return "PARTIAL", "HTTP %s estado: %s" % (status, estado)
    return ("PASS" if status == codigo_ok else "FAIL"), "HTTP %s" % status


# --- tokens ------------------------------------------------------------
_lock_apigee = threading.Lock()
_token_apigee = {"valor": None, "vence": 0.0}


def token_apigee():
    """client_credentials contra Apigee. Se cachea en memoria con
    expiracion -- el TokenManager.java original no expira nunca el suyo, y
    ese es justo el tipo de bug que no queremos heredar aqui."""
    with _lock_apigee:
        if _token_apigee["valor"] and time.time() < _token_apigee["vence"]:
            return _token_apigee["valor"]
        cid = _secreto("apigee_client_id")
        secreto = _secreto("apigee_client_secret")
        basic = base64.b64encode(("%s:%s" % (cid, secreto)).encode()).decode()
        status, cuerpo = _curl(
            "POST",
            BASE_APIGEE + "/oauth/client_credential/accesstoken?grant_type=client_credentials",
            headers={"Authorization": "Basic %s" % basic})
        if status != 200 or not isinstance(cuerpo, dict) or "access_token" not in cuerpo:
            raise RuntimeError("No se pudo obtener el token Apigee: HTTP %s %r" % (status, cuerpo))
        _token_apigee["valor"] = cuerpo["access_token"]
        expira_en = int(cuerpo.get("expires_in", 3600) or 3600)
        _token_apigee["vence"] = time.time() + max(expira_en - 60, 30)
        return _token_apigee["valor"]


_lock_ciam = threading.Lock()
_token_ciam = {"valor": None, "vence": 0.0}

# Identidad dummy fija con la que el propio framework Java pide el token
# CIAM -- no es la del usuario bajo prueba, es siempre la misma.
CIAM_BODY_BASE = {
    "uid": "bb99d52a895d4fa9a60d8a7128120c50",
    "cliente": {
        "nombres": "Diego", "apellidos": "Buitrago",
        "telefono": "+573043760558", "correo": "correo@ejemplo.com",
        "documento": {"tipo": "2", "numero": "878787878"},
    },
    "empresa": {"documento": {"tipo": "", "numero": ""}},
    "sesion": {"tiempoSegundos": 7200},
    "tipoMarketing": "B2C",
}


def token_ciam():
    """Solo lo necesita Card Validation V2. Se cachea global (no por
    usuario, la identidad del body es siempre la dummy de arriba)."""
    with _lock_ciam:
        if _token_ciam["valor"] and time.time() < _token_ciam["vence"]:
            return _token_ciam["valor"]
        body = dict(CIAM_BODY_BASE, credenciales={"gigyaApiKey": _secreto("ciam_gigya_api_key")})
        status, cuerpo = _curl(
            "POST", BASE_APIGEE + "/api/v3/afiliacion/validador/token/ciam",
            headers={"Authorization": "Bearer %s" % token_apigee(),
                     "x-api-key": _secreto("ciam_token_api_key")},
            body=body)
        if status != 200 or not isinstance(cuerpo, dict) or "access_token" not in cuerpo:
            raise RuntimeError("No se pudo obtener el token CIAM: HTTP %s %r" % (status, cuerpo))
        _token_ciam["valor"] = cuerpo["access_token"]
        expira_en = int(cuerpo.get("expires_in", 3600) or 3600)
        _token_ciam["vence"] = time.time() + max(expira_en - 60, 30)
        return _token_ciam["valor"]


_lock_sso = threading.Lock()
_tokens_sso = {}   # (tipo, numero) -> token crudo | None


def token_sso(tipo, numero):
    """Login por persona; None si el usuario no tiene credenciales SSO (no
    es un error, es lo normal para la mayoria de los usuarios de prueba).
    Se cachea por documento con un Lock (aqui los hilos son un pool, no
    1:1 con el documento como el ThreadLocal de Java)."""
    clave = (tipo.upper(), numero)
    with _lock_sso:
        if clave in _tokens_sso:
            return _tokens_sso[clave]
    doc_tipo = DOC_TYPE_LOGIN.get(tipo.upper())
    token = None
    if doc_tipo is not None:
        status, cuerpo = _curl(
            "POST", BASE_APIGEE + "/api/v2/autenticacion/usuarios/login/personas",
            headers={"Authorization": "Bearer %s" % token_apigee()},
            body={"contrasenha": _secreto("sso_password"),
                  "documento": {"tipo": doc_tipo, "numero": numero}})
        if status == 200 and isinstance(cuerpo, dict):
            obtener = cuerpo.get("obtenerToken") or []
            if obtener and isinstance(obtener[0], dict):
                token = obtener[0].get("token") or None
    with _lock_sso:
        _tokens_sso[clave] = token
    return token


# --- los servicios, uno por uno -----------------------------------------
def _emitir(numero, servicio, estado_completo):
    print("[EXCEL_UPDATE] Thread:%d %s - %s - %s"
          % (threading.get_ident() % 100000, numero, servicio, estado_completo),
          flush=True)


def validar_documento(tipo, numero):
    doc_servicios = DOC_TYPE_SERVICES.get(tipo.upper())
    if doc_servicios is None:
        _emitir(numero, "SSO Credentials", "SKIP - Tipo de documento no soportado (%s)" % tipo)
        return

    # 1) SSO Credentials -- se pide una sola vez, Validate Request la reusa
    sso = token_sso(tipo, numero)
    _emitir(numero, "SSO Credentials",
            "PASS - Has SSO credentials" if sso else "FAIL - No SSO credentials")

    # 2) Validation Bizagi
    status, cuerpo = _curl(
        "POST", BASE_INT + "/loans/eligibility/internal/v1/affiliation-validations",
        headers={"x-api-key": API_KEY_ELIGIBILITY},
        body={"idCaso": "564789", "documento": {"tipo": doc_servicios, "numero": numero}})
    estado, detalle = _interpretar_validacion(status, cuerpo)
    _emitir(numero, "Validation Bizagi", "%s - %s" % (estado, detalle))

    # 3) Validator Rights -> Card Number / Card Status / Salary
    status, cuerpo = _curl(
        "GET", BASE_APIGEE + "/api/v2/afiliacion/validador",
        headers={"Authorization": "Bearer %s" % token_apigee()},
        params={"numeroId": numero, "tipoId": doc_servicios})
    _emitir(numero, "Validator Rights",
            ("PASS" if status == 200 else "FAIL") + " - HTTP %s" % status)
    datos = cuerpo.get("data") if isinstance(cuerpo, dict) else None
    primero = datos[0] if isinstance(datos, list) and datos else {}
    afiliado = primero.get("afiliado") if isinstance(primero, dict) else None
    if isinstance(afiliado, dict):
        tarjeta = afiliado.get("tarjetaMultiservicios") or {}
        numero_tarjeta = tarjeta.get("numeroTarjeta")
        _emitir(numero, "Card Number",
                "PASS - %s" % numero_tarjeta if numero_tarjeta else "FAIL - No card found")
        estado_tarjeta = tarjeta.get("estado")
        if estado_tarjeta is None:
            _emitir(numero, "Card Status", "FAIL - Card is not active")
        elif str(estado_tarjeta).upper() == "ACTIVA":
            _emitir(numero, "Card Status", "PASS - Card is active")
        else:
            _emitir(numero, "Card Status", "FAIL - Card status: %s" % estado_tarjeta)
        empleadores = primero.get("empleadores") if isinstance(primero, dict) else None
        companias = empleadores.get("companias") if isinstance(empleadores, dict) else None
        salario = companias[0].get("salario") if isinstance(companias, list) and companias else None
        _emitir(numero, "Salary", "PASS - %s" % salario if salario else "FAIL - No salary found")

    # 4) Card Validation (ASCARD v1) + Card Validation Error
    status, cuerpo = _curl(
        "POST", BASE_INT + "/loans/eligibility/internal/v1/card-validations",
        headers={"x-api-key": API_KEY_ELIGIBILITY},
        body={"documento": {"tipo": doc_servicios, "numero": numero}})
    estado, detalle = _interpretar_validacion(status, cuerpo)
    _emitir(numero, "Card Validation", "%s - %s" % (estado, detalle))
    resultado = cuerpo.get("resultadoValidacion") if isinstance(cuerpo, dict) else None
    datos_error = resultado.get("datosError") if isinstance(resultado, dict) else None
    if isinstance(datos_error, dict) and datos_error.get("codigoErrorValidacion") == "INVALID_REQUIREMENTS":
        descripcion = datos_error.get("descripcionErrorValidacion") or ""
        regla = datos_error.get("reglaErrorValidacion") or ""
        _emitir(numero, "Card Validation Error", "%s | %s" % (descripcion, regla))

    # 5) Card Validation V2 (CIAM) -> Card Validation Error V2 + Novedad Estado
    try:
        ciam = token_ciam()
    except RuntimeError as e:
        ciam = None
        print("! token CIAM no disponible, se salta Card Validation V2: %s" % e)
    if ciam:
        status, cuerpo = _curl(
            "POST", BASE_EXT + "/loans/eligibility/external/v2/card-validations",
            headers={"Authorization": ciam},
            body={"documento": {"tipo": doc_servicios, "numero": numero}})
        if status == 200 and isinstance(cuerpo, dict):
            resultado_v2 = cuerpo.get("resultadoValidacion") or {}
            estado_v2 = resultado_v2.get("estado")
            if estado_v2:
                _emitir(numero, "Card Validation Error V2", estado_v2)
            tipo_solicitud = resultado_v2.get("tipoSolicitud")
            if tipo_solicitud is not None:
                novedad = {1: "ORIGINACIÓN", 2: "AUMENTO", 3: "REACTIVACIÓN"}.get(tipo_solicitud)
                _emitir(numero, "Novedad Estado", novedad or "DESCONOCIDO (%s)" % tipo_solicitud)

    # 6) Restrictive List
    status, cuerpo = _curl(
        "POST", BASE_APIGEE + "/api/v2/credito/elegibilidad/listasrestrictivas",
        headers={"Authorization": "Bearer %s" % token_apigee()},
        body={"numeroDocumento": numero, "tipoDocumento": doc_servicios})
    estado, detalle = _interpretar_validacion(status, cuerpo)
    _emitir(numero, "Restrictive List", "%s - %s" % (estado, detalle))

    # 7) Siif Validation
    status, cuerpo = _curl(
        "POST", BASE_APIGEE + "/api/v2/credito/elegibilidad/productos",
        headers={"Authorization": "Bearer %s" % token_apigee()},
        body={"idCaso": "a6d876f9c98d90", "documento": {"tipo": doc_servicios, "numero": numero}})
    estado, detalle = _interpretar_validacion(status, cuerpo)
    _emitir(numero, "Siif Validation", "%s - %s" % (estado, detalle))

    # 8) Validate Request -- solo si el usuario tiene credenciales SSO
    doc_validate = DOC_TYPE_VALIDATE_REQUEST.get(tipo.upper())
    if not sso:
        _emitir(numero, "Validate Request", "SKIP - Sin credenciales SSO")
    elif doc_validate is None:
        _emitir(numero, "Validate Request", "SKIP - Tipo de documento no soportado (%s)" % tipo)
    else:
        status, cuerpo = _curl(
            "POST", BASE_EXT + "/loans/req-mgr/external/v1/product/2/request/validate-request",
            headers={"Authorization": sso},
            body={"documento": {"tipo": doc_validate, "numero": numero}, "canalOrigen": "WEB"})
        estado, detalle = _interpretar_validacion(status, cuerpo, codigo_ok=202)
        _emitir(numero, "Validate Request", "%s - %s" % (estado, detalle))

    # 9) Preapproved
    doc_pre = DOC_TYPE_PREAPPROVED.get(tipo.upper())
    if doc_pre is None:
        _emitir(numero, "Preapproved", "SKIP - Tipo de documento no soportado (%s)" % tipo)
    else:
        status, _cuerpo = _curl(
            "GET", BASE_INT + "/loans/eligibility/internal/v1/campaigns/%s/%s" % (doc_pre, numero),
            headers={"x-api-key": API_KEY_ELIGIBILITY})
        _emitir(numero, "Preapproved", ("PASS" if status == 200 else "FAIL") + " - HTTP %s" % status)


def _parse_doc(s):
    if ":" not in s:
        raise argparse.ArgumentTypeError(
            "formato esperado TIPO:NUMERO (ej. CC:12345678), recibido %r" % s)
    tipo, numero = s.split(":", 1)
    return tipo.upper(), numero


def main(argv=None):
    global API_KEY_ELIGIBILITY
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hilos", type=int, default=5, help="documentos en paralelo (default 5)")
    ap.add_argument("documentos", nargs="+", type=_parse_doc,
                    help="TIPO:NUMERO, uno o mas (ej. CC:52526685)")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    try:
        API_KEY_ELIGIBILITY = _secreto("api_key_card_validations")
        token_apigee()   # falla rapido y una sola vez si token.txt esta mal
    except RuntimeError as e:
        print("! %s" % e)
        return 2

    print("> validando %d documento(s) con %d hilo(s)..."
          % (len(args.documentos), args.hilos))
    fallos = 0
    with ThreadPoolExecutor(max_workers=max(1, args.hilos)) as pool:
        futuros = {pool.submit(validar_documento, tipo, numero): (tipo, numero)
                   for tipo, numero in args.documentos}
        for futuro in futuros:
            tipo, numero = futuros[futuro]
            try:
                futuro.result()
            except Exception as e:
                fallos += 1
                print("! %s %s: %s" % (tipo, numero, e))
    print("Tests run: %d, Failures: %d" % (len(args.documentos), fallos))
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())

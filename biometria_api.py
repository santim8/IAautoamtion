#!/usr/bin/env python3
"""Flujo de biometria (autenticacion + firma de documentos), en Python puro,
sin pasar por colsubsidioFramework/Maven.

Puerto de BiometryFlow.run() (colsubsidioFramework): son 3 llamadas REST
secuenciales contra el ambiente interno -- NO hay Selenium, NO hay foto ni
SDK de biometria facial de por medio. En ambiente de test, el proceso
biometrico real se bypasea asi: el paso 1 es el equivalente a "simular OK"
(mensaje "14", fijo) a nivel de API.

Uso:
    python biometria_api.py --caso ID --doc NUMERO [--tipo TIPO]
"""
import argparse
import json
import os
import subprocess
import sys

BASE_INT = "https://platform-test-internal.colsubsidio.com"
TOKEN_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "token.txt")

# Constantes fijas del paso 3, copiadas tal cual del framework Java (no
# derivan de idCaso/identification).
ADOTECH_TRANSACTION = "2895"
MATRICULA_ID = "61700"
NOMBRES_DOCUMENTOS = ["INFORME_SOL_ONLINE_CERT", "PAGARE_ONLINE_CERT"]


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


def _api_key():
    valor = _cargar_token_txt().get("api_key_card_validations")
    if not valor:
        raise RuntimeError(
            "Falta 'api_key_card_validations' en token.txt. "
            "Agregar la linea: api_key_card_validations=<API_KEY>")
    return valor


# El panel arranca este script sin consola propia: cada curl.exe que se
# lanza sin este flag se abre su propia consola nueva, al no tener ninguna
# que heredar (ver el mismo fix en validaciones_api.py).
_SIN_VENTANA = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def _curl(metodo, url, headers, body=None, timeout=30):
    cmd = ["curl", "--silent", "--show-error", "--write-out", "\n%{http_code}",
           "--request", metodo, "--url", url,
           "--header", "content-type: application/json",
           "--header", "accept: application/json",
           "--header", "user-agent: insomnia/11.2.0"]
    for k, v in headers.items():
        cmd += ["--header", "%s: %s" % (k, v)]
    if body is not None:
        cmd += ["--data", json.dumps(body)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       creationflags=_SIN_VENTANA)
    salida = r.stdout.strip().rsplit("\n", 1)
    crudo = salida[0] if len(salida) > 1 else ""
    status = int(salida[-1]) if salida[-1].isdigit() else None
    try:
        cuerpo = json.loads(crudo) if crudo else None
    except json.JSONDecodeError:
        cuerpo = crudo
    return status, cuerpo


def biometry_flow(id_caso, identification):
    """Devuelve (ok, paso_que_fallo_o_None, detalle_o_None)."""
    headers = {"x-api-key": _api_key()}

    # Paso 1: notifica el resultado biometrico (mensaje "14" = OK)
    body1 = {"notificacion": [{"proceso": {"codigo": id_caso},
                                "documento": {"numero": identification},
                                "version": "01", "mensaje": "14"}]}
    status1, _cuerpo1 = _curl(
        "POST", BASE_INT + "/loans/identity/internal/v1/validator/authentication-result",
        headers, body1)
    print("  Paso 1/3 autenticacion biometrica: HTTP %s" % status1)
    if status1 != 200:
        return False, 1, "HTTP %s" % status1

    # Paso 2: documentos a firmar
    status2, docs = _curl(
        "GET", BASE_INT + "/loans/identity/internal/v1/validator/documents-to-sign/%s" % id_caso,
        headers)
    n_docs = len(docs) if isinstance(docs, list) else 0
    print("  Paso 2/3 documentos a firmar: HTTP %s (%d documento(s))" % (status2, n_docs))
    if status2 != 200 or n_docs == 0:
        return False, 2, "HTTP %s, %d documento(s)" % (status2, n_docs)

    # Paso 3: firma -- reenvia el generatedDocument (base64) de cada uno
    firmados = []
    for i, doc in enumerate(docs[:2]):
        nombre = NOMBRES_DOCUMENTOS[i] if i < len(NOMBRES_DOCUMENTOS) else doc.get("name", "DOC_%d" % i)
        firmados.append({
            "documentoBase64": doc.get("generatedDocument", ""),
            "nombre": nombre,
            "tipoDocumento": 1,
        })
    body3 = {
        "tipoDocumento": "4",
        "adotechTransaction": ADOTECH_TRANSACTION,
        "matriculaId": MATRICULA_ID,
        "idProceso": id_caso,
        "nroDocumento": identification,
        "documentosFirmadosResponsable": firmados,
    }
    status3, _cuerpo3 = _curl(
        "POST", BASE_INT + "/loans/identity/internal/v1/validator/documents-signed/%s" % id_caso,
        headers, body3)
    print("  Paso 3/3 documentos firmados: HTTP %s" % status3)
    if status3 != 200:
        return False, 3, "HTTP %s" % status3

    return True, None, None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--caso", required=True, help="Id del caso")
    ap.add_argument("--doc", required=True, help="Numero de documento")
    ap.add_argument("--tipo", default="CO1C",
                    help="Tipo de documento (informativo; el backend no lo usa en este flujo)")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    print("> biometria: caso %s, %s %s" % (args.caso, args.tipo, args.doc))
    try:
        ok, paso, detalle = biometry_flow(args.caso, args.doc)
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        print("! Error de biometria: %s" % e)
        return 1
    if ok:
        print("BIOMETRIA OK para caso %s" % args.caso)
        return 0
    print("BIOMETRIA FALLO en paso %s: %s" % (paso, detalle))
    return 1


if __name__ == "__main__":
    sys.exit(main())

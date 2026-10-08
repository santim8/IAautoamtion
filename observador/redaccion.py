"""Credenciales fuera de la evidencia."""
import json
import re

HEADERS_SENSIBLES = {
    "authorization", "cookie", "set-cookie", "x-api-key", "apikey",
    "x-auth-token", "proxy-authorization",
}
CLAVES_SENSIBLES = re.compile(
    r"(token|password|passwd|secret|authorization|cookie|clientsecret|client_secret|signature|uidsig)",
    re.I,
)
RE_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9\-_\.=]{20,}", re.I)
RE_JWT = re.compile(r"\beyJ[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]{10,}\.[A-Za-z0-9\-_]*")

REDACTADO = "<REDACTED>"


def redactar_texto(txt):
    if not isinstance(txt, str):
        return txt
    txt = RE_BEARER.sub(r"\1" + REDACTADO, txt)
    txt = RE_JWT.sub(REDACTADO, txt)
    return txt


def redactar_headers(headers):
    return {
        k: (REDACTADO if k.lower() in HEADERS_SENSIBLES else redactar_texto(v))
        for k, v in headers.items()
    }


def redactar_json(obj):
    """Recorre un JSON y redacta valores cuya clave parezca sensible."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if CLAVES_SENSIBLES.search(str(k)):
                out[k] = REDACTADO
            else:
                out[k] = redactar_json(v)
        return out
    if isinstance(obj, list):
        return [redactar_json(v) for v in obj]
    return redactar_texto(obj)


def redactar_body(texto):
    """Intenta como JSON (redaccion por clave); si no, redaccion por regex."""
    if not texto:
        return texto
    try:
        return json.dumps(redactar_json(json.loads(texto)), ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return redactar_texto(texto)


def redactar_registro(reg):
    """Redacta en su lugar las cabeceras y los cuerpos de un registro."""
    reg["request_headers"] = redactar_headers(reg["request_headers"])
    reg["response_headers"] = redactar_headers(reg["response_headers"])
    reg["request_body"] = redactar_body(reg["request_body"])
    reg["response_body"] = redactar_body(reg["response_body"])
    return reg

"""Utilidades sin estado."""
import json
import re
from datetime import datetime, timezone


def slug_de_url(url):
    """Nombre corto y legible para la carpeta del paso, sacado del path."""
    try:
        sin_query = url.split("?")[0].split("#")[0]
        partes = [p for p in sin_query.split("/")[3:] if p]
    except (IndexError, AttributeError):
        partes = []
    base = "-".join(partes[-2:]) if partes else "home"
    base = re.sub(r"[^A-Za-z0-9._-]+", "-", base).strip("-").lower()
    return (base or "home")[:48]


def ahora_iso():
    return datetime.now(timezone.utc).isoformat()


def ruta_de(url):
    """La URL sin query ni fragmento: esquema, host y path.

    El patron de --solo-url tiene que casar contra la ruta real. Las paginas
    auxiliares de SSO llevan la URL de la app dentro del fragmento
    (#origin=https://.../creditos/solicitud/login) y se hacian pasar por la
    pestana buena: el observador se fijaba a una de ellas y la app quedaba
    ignorada, con la corrida entera vacia.
    """
    return (url or "").split("#")[0].split("?")[0]


def cabeceras_request(request, completas=True):
    """Cabeceras del request; las completas solo con el request ya terminado.

    completas=False no toca Playwright (las provisionales ya estan cargadas):
    es lo que se puede usar al cerrar o desde el hilo vigilante.
    """
    if request is None:
        return {}
    if completas:
        try:
            return request.all_headers()
        except Exception:
            pass
    try:
        return dict(request.headers)
    except Exception:
        return {}


def es_url_real(url):
    """about:blank y chrome:// no son pantallas del flujo, son ruido de arranque."""
    return bool(url) and url.startswith(("http://", "https://"))


def anexar_jsonl(ruta, obj):
    """Una linea mas en un .jsonl. Append inmediato: si matan el proceso, la
    evidencia ya esta en disco."""
    with open(ruta, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def leer_jsonl(ruta):
    """Las lineas de un .jsonl, saltando las que quedaron a medias por un
    cierre abrupto."""
    filas = []
    with open(ruta, encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                filas.append(json.loads(ln))
            except json.JSONDecodeError:
                continue
    return filas

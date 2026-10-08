"""Como casa una URL con los endpoints del catalogo."""
import re
from urllib.parse import urlsplit

from observador.config import REGLAS_ENDPOINT

# La version del path es un comodin: los servicios pasan de v1 a v2 segun se
# activen las novedades, y con la version fija ese trafico dejaria de
# reconocerse justo cuando mas interesa mirarlo. Se guarda la version que
# realmente llego para poder avisar del cambio.
RE_VERSION = re.compile(r"/v(\d+)/")


def patron_endpoint(endpoint):
    """Compila un endpoint rastreado dejando /vN/ como comodin."""
    partes = [re.escape(t) for t in RE_VERSION.split(endpoint)[::2]]
    return re.compile(r"/v\d+/".join(partes))


def version_declarada(endpoint):
    m = RE_VERSION.search(endpoint)
    return m.group(1) if m else None


def version_de(url):
    m = RE_VERSION.search(url)
    return m.group(1) if m else None


def casan(endpoints, url):
    """Patrones rastreados que casan con esta URL, con la version al vuelo."""
    return [e for e in endpoints if patron_endpoint(e).search(url)]


def va_a_hosts(url, hosts):
    """El request va a uno de esos hosts. Se mira solo el host: los beacons de
    Google y Gigya llevan la URL de la app en la query (url=, pageURL=) y con
    un match sobre la URL entera pasaban por trafico del backend."""
    try:
        host = urlsplit(url).netloc
    except ValueError:
        return False
    return any(h in host for h in hosts)


def tiene_regla(url, regla):
    """La URL casa con un endpoint que lleva esa regla (ver REGLAS_ENDPOINT)."""
    return bool(casan([e for e, reglas in REGLAS_ENDPOINT.items() if regla in reglas],
                      url or ""))


def sin_payload(url):
    return tiene_regla(url, "sin_payload")


def cuerpo_inmediato(url):
    return tiene_regla(url, "cuerpo_inmediato")

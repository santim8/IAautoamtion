"""Que se captura: de que pestana sale y a donde va cada request.

Son dos filtros independientes:
  - por destino: los hosts del backend, o solo los endpoints rastreados
  - por origen: con --solo-url se fija una pestana (la primera cuya ruta case)
    y se ignora lo que pase en las demas
"""
from observador.endpoints import patron_endpoint, va_a_hosts
from observador.util import ruta_de


def pagina_de(request):
    """Pagina que origino el request (los de service worker no tienen frame)."""
    try:
        return request.frame.page
    except Exception:
        return None


class Alcance:
    def __init__(self, hosts, endpoints=None, solo_endpoints=False,
                 patrones=None, seguir_popups=False):
        self.hosts = hosts           # [] = capturar todo
        self.endpoints = endpoints or []   # endpoints de negocio a marcar
        self.endpoints_rx = [(e, patron_endpoint(e)) for e in self.endpoints]
        self.solo_endpoints = solo_endpoints
        # lista de rutas aceptadas; vacia = todas las pestanas
        if isinstance(patrones, str):
            patrones = [x.strip() for x in patrones.split(",") if x.strip()]
        self.patrones = list(patrones or [])
        self.seguir_popups = seguir_popups
        self.lock = None             # la pestana elegida, una vez encontrada
        self.hijas = set()           # pestanas abiertas POR la elegida
        self.sin_pestana = 0         # requests sin frame (service worker), para avisar

    # -- endpoints de negocio
    def casar_endpoints(self, url):
        """Todos los patrones rastreados que casan con esta URL (pueden ser varios)."""
        return [e for e, rx in self.endpoints_rx if rx.search(url)]

    # -- filtro por destino (a que host va el request)
    def api_fuera_catalogo(self, url, tipo):
        """fetch/xhr a los hosts de la app que no esta en el catalogo.

        En modo endpoints solo se guarda el catalogo; pero si el front cambia
        la ruta de un servicio (otra version, un BFF propio en cloudfront) su
        fallo desaparecia sin rastro. Estos se siguen y se guardan SOLO si
        fallan (status >= 400, CORS o red cortada).
        """
        if not self.solo_endpoints or (tipo or "").lower() not in ("fetch", "xhr"):
            return False
        if not url.startswith("http"):
            return False
        return not self.hosts or va_a_hosts(url, self.hosts)

    def interesa(self, url):
        if not url.startswith("http"):
            return False
        if self.solo_endpoints:
            return bool(self.casar_endpoints(url))
        if not self.hosts:
            return True
        return va_a_hosts(url, self.hosts)

    # -- filtro por origen (de que pestana viene)
    def intentar_lock(self, page, url):
        """Engancha el candado a la primera pestana cuya URL case con el patron."""
        if self.lock is not None or not self.patrones:
            return False
        ruta = ruta_de(url)
        if not any(p in ruta for p in self.patrones):
            return False
        self.lock = page
        print("\n>> Pestana fijada: %s" % url)
        print(">> Se ignora todo lo que pase en las demas pestanas.\n")
        return True

    def pagina_permitida(self, page):
        if not self.patrones:
            return True              # sin --solo-url: todas las pestanas
        if self.lock is None:
            return False             # aun no encontramos la pestana objetivo
        return page is self.lock or (self.seguir_popups and page in self.hijas)

    def descartar(self, request):
        """True si el request no pertenece a la pestana bajo observacion."""
        if not self.patrones:
            return False
        pagina = pagina_de(request)
        if pagina is None:
            # sin frame (service worker): no podemos saber de que pestana salio.
            # No lo inventamos: lo descartamos y lo contamos para avisarte al final.
            self.sin_pestana += 1
            return True
        return not self.pagina_permitida(pagina)

    def registrar_hija(self, madre, hija):
        """La pestana observada abrio otra. Solo la seguimos si lo pediste."""
        if self.lock is not None and madre is self.lock:
            self.hijas.add(hija)
            if self.seguir_popups:
                print(">> La pestana observada abrio otra; la sigo tambien.")
            else:
                print(">> La pestana observada abrio otra; la IGNORO "
                      "(usa --seguir-popups si la necesitas).")

    def describir(self):
        """Las lineas del banner de arranque: alcance y que se guarda."""
        lineas = ["Alcance: %s"
                  % ("SOLO la pestana con "
                     + " o ".join('"%s"' % p for p in self.patrones)
                     if self.patrones else "todas las pestanas")]
        if self.solo_endpoints:
            lineas.append("Se guardan: solo los %d endpoints rastreados"
                          % len(self.endpoints))
        elif self.hosts:
            lineas.append("Se guardan: todo lo que vaya a: " + ", ".join(self.hosts))
        else:
            lineas.append("Se guardan: TODOS los requests (incluye analytics y CDN)")
        return lineas

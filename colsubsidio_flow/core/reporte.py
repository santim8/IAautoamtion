"""Equivalente de ExtentLogger: todo va a la consola.

Como en Java, fail() no corta el test: marca el reporte como fallido y el flujo
sigue. El runner revisa reporte.actual().fallas al terminar cada usuario.

Ademas cada linea queda en reporte.actual().lineas con la seccion en que se
dijo (seccion("politicas")): es lo que el validador e2e pinta por pantalla en
reporte.html.
"""
import time
from datetime import datetime


class Reporte:
    def __init__(self, nombre):
        self.nombre = nombre
        self.fallas = []
        self.inicio = time.time()
        self.fin = None
        self.lineas = []        # [{marca, mensaje, seccion, ts}]
        self.seccion = ""

    @property
    def ok(self):
        return not self.fallas

    def terminar(self):
        self.fin = time.time()

    def duracion(self):
        return (self.fin or time.time()) - self.inicio


_actual = Reporte("sin test")


def iniciar(nombre):
    global _actual
    _actual = Reporte(nombre)
    return _actual


def actual():
    return _actual


def seccion(nombre):
    """Las lineas que siguen son de esta seccion (una pantalla del flujo)."""
    _actual.seccion = nombre


def _linea(marca, mensaje):
    _actual.lineas.append({"marca": marca, "mensaje": mensaje, "seccion": _actual.seccion,
                           "ts": datetime.now().astimezone().isoformat(timespec="seconds")})
    print("  [%s] %s" % (marca, mensaje), flush=True)


def info(mensaje):
    _linea("INFO", mensaje)


def pass_(mensaje):
    _linea("PASS", mensaje)


def warning(mensaje):
    _linea("WARN", mensaje)


def fail(mensaje):
    _actual.fallas.append(mensaje)
    _linea("FAIL", mensaje)


def info_token(etiqueta, token):
    # ExtentLogger.infoToken imprime el token entero; aqui solo el largo.
    _linea("INFO", "%s: <%d caracteres>" % (etiqueta, len(token or "")))

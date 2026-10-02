"""Equivalente de ExtentLogger: todo va a la consola.

Como en Java, fail() no corta el test: marca el reporte como fallido y el flujo
sigue. El runner revisa reporte.actual().fallas al terminar cada usuario.
"""
import time


class Reporte:
    def __init__(self, nombre):
        self.nombre = nombre
        self.fallas = []
        self.inicio = time.time()

    @property
    def ok(self):
        return not self.fallas

    def duracion(self):
        return time.time() - self.inicio


_actual = Reporte("sin test")


def iniciar(nombre):
    global _actual
    _actual = Reporte(nombre)
    return _actual


def actual():
    return _actual


def _linea(marca, mensaje):
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

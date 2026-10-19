"""Lo que se escribe al cerrar una corrida.

Cada archivo de salida es una funcion en SALIDAS, en orden. Todas reciben un
Cierre (el observador mas lo que comparten) y escriben en su carpeta. Un
archivo nuevo es una funcion mas en la lista; no hay que tocar el resto.
"""
import json
import os
import threading

import esquemas as esq
import sonda_check
from observador.analisis import (cobertura_endpoints, es_fallo, frames_socket,
                                 imprimir_cobertura, linea_check, quizas_json,
                                 total_fallos, total_requests)
from observador.har import escribir_har
from observador.reporte_html import escribir_reporte
from observador.util import ahora_iso

_CERRANDO = threading.Lock()
_CERRADO = [False]


def ya_cerrado():
    return _CERRADO[0]


def cerrar(obs, flujo, ruta_esquemas=None, generar=False):
    """Escribe las salidas una sola vez, aunque lo pidan el loop y el hilo
    vigilante a la vez."""
    with _CERRANDO:
        if _CERRADO[0]:
            return
        _CERRADO[0] = True
    return _cerrar(obs, flujo, ruta_esquemas, generar)


class Cierre:
    """El observador (en vivo o reconstruido desde disco) y lo que las salidas
    comparten."""

    def __init__(self, obs, flujo, ruta_esquemas=None, generar=False):
        self.obs = obs
        self.flujo = flujo
        self.ruta_esquemas = ruta_esquemas
        self.generar = generar
        self.checks = linea_check(obs.pasos)
        self.cob = cobertura_endpoints(obs.pasos, obs.endpoints)
        self.frames = frames_socket(obs.pasos)

    def ruta(self, nombre):
        return os.path.join(self.obs.dir, nombre)

    def escribir_json(self, nombre, datos, **kw):
        with open(self.ruta(nombre), "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=2, **kw)


def _cerrar(obs, flujo, ruta_esquemas=None, generar=False):
    obs.rescatar_al_cerrar()
    c = Cierre(obs, flujo, ruta_esquemas, generar)
    for salida in SALIDAS:
        salida(c)
    imprimir_cierre(c)


# --- salidas ----------------------------------------------------------------
def salida_request_check(c):
    """request_check.json: lo que respondio /request/check, en orden."""
    if c.checks:
        c.escribir_json("request_check.json", c.checks)


def salida_resumen(c):
    """resumen.json (los pasos) y endpoints.json (la cobertura)."""
    resumen = {
        "flujo": c.flujo,
        "generado": ahora_iso(),
        "pasos": [{"idx": p["idx"], "url": p["url"], "titulo": p["titulo"], "ts": p["ts"],
                   "pestana": p.get("pestana", 0), "requests": len(p["requests"]),
                   "websocket": len(p.get("sockets") or []),
                   "fallos": sum(1 for r in p["requests"] if es_fallo(r))}
                  for p in c.obs.pasos],
    }
    if c.checks:
        resumen["request_check"] = c.checks
    resumen["endpoints"] = c.cob
    c.escribir_json("resumen.json", resumen)
    c.escribir_json("endpoints.json", c.cob)


def salida_servicios(c):
    """servicios.json: la llamada a llamada de los endpoints de negocio, en
    orden, con payload y respuesta. Es el archivo que se lee para verificar el
    flujo."""
    servicios = []
    for paso in c.obs.pasos:
        for r in paso["requests"]:
            if not r.get("rastreados"):
                continue
            llamada = {"method": r["metodo"], "status": r["status"],
                       "duracion_ms": r["duracion_ms"]}
            if r.get("fallo"):
                llamada["fallo"] = r["fallo"]
                if r.get("cors"):
                    llamada["cors"] = r["cors"]
            servicios.append({
                "url": r["url"],
                "request": llamada,
                "payload": quizas_json(r.get("request_body")),
                "contexto": {
                    "paso": paso["idx"],
                    "pantalla": paso["url"],
                    "endpoint": r["rastreados"][0],
                    "timestamp": r["ts"],
                }
            })
    c.escribir_json("servicios.json", servicios)


def salida_esquemas(c):
    """El contrato que se observo en ESTA corrida queda siempre en la
    evidencia; el soft assert solo corre si ya hay un baseline con que
    comparar. Deja el resultado en obs.validacion para el reporte."""
    obs = c.obs
    c.escribir_json("esquemas_observados.json", esq.esquemas_de_corrida(obs.pasos),
                    sort_keys=True)
    obs.ruta_esquemas = c.ruta_esquemas
    obs.validacion = []
    if c.generar:
        esq.escribir_baseline(obs.pasos, c.ruta_esquemas)
        print("\nBaseline de esquemas actualizado: %s" % os.path.abspath(c.ruta_esquemas))
        return
    baseline = esq.leer_baseline(c.ruta_esquemas)
    if baseline is None:
        print("\nNo hay baseline de esquemas todavia (%s)."
              % (c.ruta_esquemas or "-"))
        print("Genera uno desde una corrida buena:  --generar-esquemas")
        return
    obs.validacion = esq.validar(obs.pasos, baseline)
    c.escribir_json("validacion_esquemas.json",
                    {"generado": ahora_iso(),
                     "baseline": os.path.abspath(c.ruta_esquemas),
                     "resumen": esq.resumir(obs.validacion),
                     "resultados": obs.validacion})


def salida_websockets(c):
    """websockets.json: todos los frames en orden, con el paso en que cayeron."""
    if c.frames:
        c.escribir_json("websockets.json", c.frames)


def salida_har(c):
    escribir_har(c.obs, c.ruta("captura.har"))


def salida_reporte(c):
    escribir_reporte(c.obs, c.flujo, c.ruta("reporte.html"))


# En orden: el reporte va al final porque lee obs.validacion (salida_esquemas).
SALIDAS = [
    salida_request_check,
    salida_resumen,
    salida_servicios,
    salida_esquemas,
    salida_websockets,
    salida_har,
    salida_reporte,
]


def imprimir_cierre(c):
    obs = c.obs
    print("\n%d pasos, %d requests, %d con error (status >= 400, CORS o sin respuesta)"
          % (len(obs.pasos), total_requests(obs.pasos), total_fallos(obs.pasos)))
    if c.checks:
        print("\n--- /request/check ---")
        for chk in c.checks:
            print("  paso %02d  %-20s %s" % (chk["paso"], chk["motivo"], sonda_check.linea(chk)))
    if c.frames:
        malos = [fr for fr in c.frames
                 if '"stepStatus":"FAIL"' in fr["payload"].replace(" ", "")]
        print("%d mensaje(s) de websocket%s"
              % (len(c.frames), (", %d con stepStatus FAIL" % len(malos)) if malos else ""))
    if obs.sin_pestana:
        print("Aviso: %d request(s) sin pestana identificable (service worker) "
              "quedaron fuera." % obs.sin_pestana)
    imprimir_cobertura(c.cob)
    esq.imprimir(getattr(obs, "validacion", []), c.ruta_esquemas)
    print("")
    print("Evidencia: " + os.path.abspath(obs.dir))
    print("Reporte:   " + os.path.abspath(c.ruta("reporte.html")))

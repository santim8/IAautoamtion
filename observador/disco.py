"""Regenerar el reporte desde una carpeta de evidencia ya capturada."""
import json
import os
import re

import sonda_check
from observador.cierre import cerrar
from observador.endpoints import casan
from observador.util import leer_jsonl


class ObsDesdeDisco:
    """Un Observador de mentira, reconstruido leyendo una carpeta de evidencia.

    Sirve para regenerar el reporte cuando la corrida murio antes de escribirlo:
    los requests.jsonl se escriben incrementalmente, asi que el dato crudo esta.
    Tiene lo que el cierre lee de un observador: dir, endpoints, pasos,
    sin_pestana y rescatar_al_cerrar.
    """

    def __init__(self, dir_evidencia, endpoints):
        self.dir = dir_evidencia
        self.endpoints = endpoints
        self.sin_pestana = 0
        self.validacion = []
        self.ruta_esquemas = None
        self.pasos = []
        for nombre in sorted(os.listdir(dir_evidencia)):
            d = os.path.join(dir_evidencia, nombre)
            if not os.path.isdir(d) or not re.match(r"^\d+_", nombre):
                continue
            idx, slug = nombre.split("_", 1)
            reqs = []
            jsonl = os.path.join(d, "requests.jsonl")
            if os.path.exists(jsonl):
                for r in leer_jsonl(jsonl):
                    sonda_check.sin_caso_vigente(r)   # evidencia de antes del cambio
                    # re-marcar contra la lista de endpoints vigente
                    marcados = casan(endpoints, r.get("url", ""))
                    if marcados:
                        r["rastreados"] = marcados
                    reqs.append(r)
            jsonlws = os.path.join(d, "websocket.jsonl")
            frames = leer_jsonl(jsonlws) if os.path.exists(jsonlws) else []
            self.pasos.append({
                "idx": int(idx), "url": (reqs[0]["url"] if reqs else ""), "slug": slug,
                "dir": d, "ts": (reqs[0]["ts"] if reqs else ""), "requests": reqs,
                "sockets": frames, "titulo": "", "pestana": 0,
            })

    def rescatar_al_cerrar(self):
        """Nada en memoria: todo salio de disco."""


def rehacer_reporte(dir_evidencia, endpoints, ruta_esquemas=None, generar=False):
    """Regenera resumen/har/reporte desde una carpeta de evidencia existente."""
    if not os.path.isdir(dir_evidencia):
        print("No existe la carpeta: %s" % dir_evidencia)
        return 1
    obs = ObsDesdeDisco(dir_evidencia, endpoints)
    if not obs.pasos:
        print("No encontre carpetas de paso (NN_algo) en %s" % dir_evidencia)
        return 1
    # la URL del paso sale del resumen de la corrida (la pantalla real); si no
    # lo hay, del documento principal, y si tampoco, del slug. Sin el resumen
    # quedaba la URL del primer request, que capturando endpoints es una API.
    try:
        with open(os.path.join(dir_evidencia, "resumen.json"), encoding="utf-8") as f:
            previos = {p["idx"]: p for p in json.load(f).get("pasos", [])}
    except (OSError, ValueError, KeyError, TypeError):
        previos = {}
    for paso in obs.pasos:
        previo = previos.get(paso["idx"]) or {}
        if previo.get("url"):
            for k in ("url", "titulo", "ts", "pestana"):
                if previo.get(k) not in (None, ""):
                    paso[k] = previo[k]
            continue
        doc = next((r for r in paso["requests"] if r.get("tipo") == "document"), None)
        if doc:
            paso["url"] = doc["url"]
        elif not paso["url"]:
            paso["url"] = paso["slug"]
    print("Reconstruyendo desde %s" % os.path.abspath(dir_evidencia))
    print("%d pasos, %d requests"
          % (len(obs.pasos), sum(len(p["requests"]) for p in obs.pasos)))
    cerrar(obs, os.path.basename(dir_evidencia.rstrip("/\\")),
           ruta_esquemas=ruta_esquemas, generar=generar)
    return 0

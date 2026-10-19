"""Frames del WebSocket del flujo."""
import json
import os

from observador.config import MAX_BODY
from observador.redaccion import redactar_body
from observador.util import ahora_iso, anexar_jsonl


class CapturaSocket:
    def __init__(self, obs):
        self.obs = obs

    def enganchar(self, pagina, ws):
        """Los frames del socket son evidencia de primera: llevan el avance del
        flujo (step / stepStatus), que no viaja por HTTP.

        No se les aplica el filtro de hosts ni el de endpoints: son pocos, van
        a un dominio distinto al del backend (API Gateway) y perderlos deja el
        reporte sin la mitad de la historia.
        """
        if not self.obs.alcance.pagina_permitida(pagina):
            return
        print("   [ws] abierto %s" % ws.url)
        ws.on("framesent",
              lambda datos: self.guardar_frame(pagina, ws, "enviado", datos))
        ws.on("framereceived",
              lambda datos: self.guardar_frame(pagina, ws, "recibido", datos))
        ws.on("close", lambda _ws=ws: print("   [ws] cerrado %s" % _ws.url))

    def guardar_frame(self, pagina, ws, direccion, datos):
        """Un frame cae en el paso que estuviera abierto en esa pestana."""
        if isinstance(datos, (bytes, bytearray)):
            texto = datos.decode("utf-8", "replace")
        else:
            texto = str(datos)
        if len(texto) > MAX_BODY:
            texto = texto[:MAX_BODY]
        if self.obs.redactar:
            texto = redactar_body(texto)
        frame = {"ts": ahora_iso(), "direccion": direccion, "url": ws.url,
                 "payload": texto}
        paso = self.obs.paso_por_pagina.get(pagina) or self.obs.paso_actual()
        if paso is None:
            return
        paso.setdefault("sockets", []).append(frame)
        anexar_jsonl(os.path.join(paso["dir"], "websocket.jsonl"), frame)
        flecha = "->" if direccion == "enviado" else "<-"
        # el payload cortado a lo bruto tapaba justo step/stepStatus, que es lo
        # unico que se mira en vivo; el JSON completo queda en el .jsonl
        resumen = None
        try:
            d = json.loads(texto)
            if isinstance(d, dict) and d.get("step"):
                resumen = "%-14s %s" % (d["step"], d.get("stepStatus", ""))
                if d.get("idCase"):
                    resumen += "  (caso %s)" % d["idCase"]
        except (json.JSONDecodeError, TypeError):
            pass
        print("   [ws %s] %s" % (flecha, resumen or texto[:120]))

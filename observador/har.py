"""captura.har: HAR 1.2 derivado de lo capturado."""
import json

from observador.config import SCRIPT


def escribir_har(obs, ruta):
    """HAR 1.2 derivado de lo capturado (no es el HAR nativo de Chrome)."""
    entradas = []
    for paso in obs.pasos:
        for r in paso["requests"]:
            entrada = {
                "startedDateTime": r["ts"],
                "time": r["duracion_ms"],
                "_paso": paso["idx"],
                "request": {
                    "method": r["metodo"],
                    "url": r["url"],
                    "httpVersion": "HTTP/1.1",
                    "headers": [{"name": k, "value": v}
                                for k, v in r["request_headers"].items()],
                    "queryString": [],
                    "cookies": [],
                    "headersSize": -1,
                    "bodySize": len(r["request_body"] or ""),
                },
                "response": {
                    "status": r["status"],
                    "statusText": "",
                    "httpVersion": "HTTP/1.1",
                    "headers": [{"name": k, "value": v}
                                for k, v in r["response_headers"].items()],
                    "cookies": [],
                    "redirectURL": "",
                    "headersSize": -1,
                    "bodySize": len(r["response_body"] or ""),
                    "content": {
                        "size": len(r["response_body"] or ""),
                        "mimeType": r["response_headers"].get("content-type", ""),
                        "text": r["response_body"],
                    },
                },
                "cache": {},
                "timings": {"send": 0, "wait": r["duracion_ms"], "receive": 0},
            }
            if r["request_body"]:
                entrada["request"]["postData"] = {
                    "mimeType": r["request_headers"].get("content-type", ""),
                    "text": r["request_body"],
                }
            if r.get("fallo"):
                entrada["_error"] = r["fallo"]   # el mismo campo que usa el HAR de Chrome
            entradas.append(entrada)
    har = {"log": {"version": "1.2",
                   "creator": {"name": SCRIPT, "version": "1.0"},
                   "entries": entradas}}
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(har, f, ensure_ascii=False, indent=2)

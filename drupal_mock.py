"""Drupal falso para simular fallas del contenido del Onboarding.

Escucha en localhost:4010 y, en modo normal, reenvia cada GET a Drupal CERT
(platform-test-external.colsubsidio.com) tal cual. El modo se cambia con
GET /__modo?m=<modo>&solo=<texto opcional en la ruta>:

  normal   reenvia a CERT
  caido    corta la conexion sin responder (como Drupal apagado)
  error500 responde 500
  html404  responde 404 con la pagina HTML de error de CloudFront/S3
  lento    espera 'seg' segundos (default 40) y luego reenvia
  vacio    responde 200 con []
  invalido responde 200 con un JSON roto

'solo' limita la falla a las rutas que contengan ese texto (ej. solo=/03 o
solo=onboarding); el resto sigue en normal.
"""
import json
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DESTINO = "https://platform-test-external.colsubsidio.com"
ESTADO = {"m": "normal", "solo": "", "seg": 40}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stdout.write("[mock] %s\n" % (fmt % args))
        sys.stdout.flush()

    def _responder(self, status, cuerpo, tipo="application/json"):
        datos = cuerpo.encode("utf-8") if isinstance(cuerpo, str) else cuerpo
        self.send_response(status)
        self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(datos)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(datos)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/__modo":
            q = urllib.parse.parse_qs(url.query)
            if "m" in q:
                ESTADO["m"] = q["m"][0]
                ESTADO["solo"] = q.get("solo", [""])[0]
                ESTADO["seg"] = int(q.get("seg", ["40"])[0])
            return self._responder(200, json.dumps(ESTADO))

        afectada = ESTADO["m"] != "normal" and (not ESTADO["solo"] or ESTADO["solo"] in self.path)
        modo = ESTADO["m"] if afectada else "normal"
        sys.stdout.write("[mock] %s -> modo %s\n" % (self.path, modo))
        sys.stdout.flush()

        if modo == "caido":
            # Cierra el socket sin mandar nada: el fetch del front falla.
            self.connection.shutdown(socket.SHUT_RDWR)
            self.close_connection = True
            return
        if modo == "error500":
            return self._responder(500, '{"message":"Internal Server Error"}')
        if modo == "html404":
            return self._responder(404, "<html><body><h1>Error 404 - Pagina No Encontrada</h1></body></html>",
                                   "text/html")
        if modo == "vacio":
            return self._responder(200, "[]")
        if modo == "invalido":
            return self._responder(200, '[{"titulo": "roto", ')
        if modo == "lento":
            time.sleep(ESTADO["seg"])
        self._reenviar()

    def _reenviar(self):
        try:
            req = urllib.request.Request(DESTINO + self.path, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return self._responder(r.status, r.read(), r.headers.get("Content-Type", "application/json"))
        except urllib.error.HTTPError as e:
            return self._responder(e.code, e.read(), e.headers.get("Content-Type", "text/plain"))
        except Exception as e:
            return self._responder(502, json.dumps({"mock_error": str(e)}))


if __name__ == "__main__":
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 4010
    print("[mock] Drupal falso en http://localhost:%d (destino %s)" % (puerto, DESTINO), flush=True)
    ThreadingHTTPServer(("127.0.0.1", puerto), Handler).serve_forever()

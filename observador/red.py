"""Trafico HTTP de la pestana observada.

Llega por dos vias que se complementan:
  - Playwright (request/response/requestfailed): la principal, con cuerpos.
  - Una sesion CDP propia: ve lo que Playwright no reporta (el status real de
    lo que Chrome bloquea por CORS, los preflight, los huerfanos).

Los handlers solo anotan; los cuerpos se leen y se guardan desde el loop
(ver drenar), porque leerlos dentro del handler lo bloquea.
"""
import time

from observador.alcance import pagina_de
from observador.config import (ESPERA_FALLO_MS, ESPERA_HUERFANO_S, MAX_BODY,
                               MAX_CDP_RED, SIN_RESPUESTA, TIPOS_SIN_CUERPO)
from observador.endpoints import cuerpo_inmediato, sin_payload
from observador.redaccion import redactar_registro
from observador.util import ahora_iso, cabeceras_request, ruta_de


class CapturaRed:
    def __init__(self, obs):
        self.obs = obs
        self.alcance = obs.alcance
        self.pend_req = {}           # request -> metadata, para casar con su response
        self.cola_resp = []          # respuestas pendientes de leer body
        self.cuerpos = {}            # response -> body ya leido en el handler
        self.cola_fallos = []        # [(request, cuando_ms)] cortados por el navegador
        self.cdp_red = {}            # requestId CDP -> {url, metodo, status, headers, error}
        # (metodo, url) que Playwright SI emitio como 'request'. Lo que CDP vio
        # y no esta aqui es un huerfano: se registra desde CDP (drenar_huerfanos)
        self.pw_vistos = {}

    def enganchar(self, page):
        page.on("request", self.on_request)
        page.on("response", self.on_response)
        page.on("requestfailed", self.on_request_failed)
        self.enganchar_cdp(page)

    # -- Playwright
    def on_request(self, request):
        fuera = False
        if not self.alcance.interesa(request.url):
            if not self.alcance.api_fuera_catalogo(request.url, request.resource_type):
                return
            fuera = True
        # antes de descartar: lo que Playwright tira por ser de otra pestana
        # tampoco debe volver a entrar como huerfano de CDP
        clave = (request.method, request.url)
        self.pw_vistos[clave] = self.pw_vistos.get(clave, 0) + 1
        if self.alcance.descartar(request):
            return
        omitir = sin_payload(request.url)
        try:
            post = None if omitir else request.post_data
        except Exception:
            post = None
        self.pend_req[request] = {
            "ts": ahora_iso(),
            "t0": time.time(),
            "metodo": request.method,
            "url": request.url,
            "tipo": request.resource_type,
            # all_headers() aqui bloqueaba el handler hasta que el request
            # terminaba: lo que nunca respondia no llegaba a registrarse, y un
            # fallo CORS se avisaba antes de quedar en pend_req. Se piden al
            # registrar, desde el loop (ver registro).
            "request_headers": None,
            "request_body": post,
        }
        if fuera:
            self.pend_req[request]["fuera_catalogo"] = True

    def on_response(self, response):
        pagina = pagina_de(response.request)
        if not self.alcance.pagina_permitida(pagina):
            return
        # Antes del filtro de captura a proposito: hay disparadores que no son
        # endpoints rastreados (estado_civil), y en modo "endpoints" interesa()
        # los descartaria y el pantallazo no se tomaria nunca.
        self.obs.pantallazos.disparar(response, pagina)
        if not self.alcance.interesa(response.url):
            meta = self.pend_req.get(response.request)
            if meta is None or not meta.get("fuera_catalogo"):
                return
            if response.status < 400:
                self.pend_req.pop(response.request, None)   # fuera del catalogo y OK
                return
        if cuerpo_inmediato(response.url):
            try:
                self.cuerpos[response] = response.body()
            except Exception:
                pass             # drenar_respuestas lo intenta otra vez y lo anota
        self.cola_resp.append(response)

    def on_request_failed(self, request):
        """El navegador corto el request: CORS, red caida, abortado.

        Playwright no emite 'response' para estos, asi que sin este handler
        desaparecian sin rastro. El caso tipico: un 404/500 que CloudFront
        contesta con su pagina de error HTML, sin Access-Control-Allow-Origin.
        El servidor SI respondio, pero Chrome no deja que el front la lea.
        """
        if request in self.pend_req:
            self.cola_fallos.append((request, time.time() * 1000))

    # -- CDP
    def enganchar_cdp(self, page):
        """Sesion CDP propia para saber que status tenia lo que se bloqueo.

        Un request bloqueado por CORS no tiene Response en Playwright, pero
        Chrome informa el status y las cabeceras reales en
        Network.responseReceivedExtraInfo: es lo que DevTools pinta como
        "404 Not Found" en una fila marcada "CORS error".
        """
        try:
            cdp = page.context.new_cdp_session(page)
            cdp.on("Network.requestWillBeSent",
                   lambda ev, _p=page, _s=cdp: self.cdp_request(ev, _p, _s))
            cdp.on("Network.responseReceived", self.cdp_respuesta)
            cdp.on("Network.responseReceivedExtraInfo", self.cdp_extra)
            cdp.on("Network.loadingFinished", self.cdp_fin)
            cdp.on("Network.loadingFailed", self.cdp_fallo)
            cdp.send("Network.enable")
        except Exception:
            pass   # sin CDP el fallo se registra igual, solo que sin status

    def cdp_request(self, ev, page=None, sesion=None):
        req = ev.get("request") or {}
        fuera = False
        if not self.alcance.interesa(req.get("url", "")):
            if not self.alcance.api_fuera_catalogo(req.get("url", ""), ev.get("type")):
                return
            fuera = True
        self.cdp_red[ev.get("requestId")] = {
            "fuera_catalogo": fuera,
            "url": req["url"], "metodo": req.get("method"),
            # lo que hace falta para registrarlo solo, si Playwright no lo ve
            "pagina": page, "sesion": sesion, "ts": ahora_iso(), "t0": time.time(),
            "tipo": (ev.get("type") or "").lower() or None,
            "req_headers": dict(req.get("headers") or {}),
            "post": None if sin_payload(req["url"]) else req.get("postData"),
        }
        while len(self.cdp_red) > MAX_CDP_RED:
            self.cdp_red.pop(next(iter(self.cdp_red)))

    def cdp_respuesta(self, ev):
        info = self.cdp_red.get(ev.get("requestId"))
        resp = ev.get("response") or {}
        if info is not None:
            info.setdefault("status", resp.get("status"))
            info.setdefault("headers", {k.lower(): v for k, v
                                        in (resp.get("headers") or {}).items()})

    def cdp_extra(self, ev):
        info = self.cdp_red.get(ev.get("requestId"))
        if info is not None:
            info["status"] = ev.get("statusCode")
            info["headers"] = {k.lower(): v for k, v in (ev.get("headers") or {}).items()}

    def cdp_fin(self, ev):
        info = self.cdp_red.get(ev.get("requestId"))
        if info is not None:
            info["fin"] = time.time()

    def cdp_fallo(self, ev):
        info = self.cdp_red.get(ev.get("requestId"))
        if info is not None:
            info["error"] = ev.get("errorText") or "fallo"
            info["cors"] = (ev.get("corsErrorStatus") or {}).get("corsError")
            info["fin"] = time.time()

    def _consumir_visto(self, info):
        """True si Playwright ya emitio este request (y lo descuenta)."""
        clave = (info.get("metodo"), info["url"])
        n = self.pw_vistos.get(clave, 0)
        if n <= 0:
            return False
        if n == 1:
            self.pw_vistos.pop(clave)
        else:
            self.pw_vistos[clave] = n - 1
        return True

    def info_cdp(self, metodo, url):
        """Lo que CDP vio del fallo de este metodo+URL (el mas viejo; se consume)."""
        for rid, info in self.cdp_red.items():
            if info["url"] == url and info.get("metodo") == metodo and "error" in info:
                self._consumir_visto(info)
                return self.cdp_red.pop(rid)
        return {}

    # -- registro
    def registro(self, meta, status, resp_headers, cuerpo, nota=None, fin=None,
                 request=None, al_cerrar=False):
        """La linea de evidencia de un request, ya marcada y redactada."""
        req_headers = meta["request_headers"]
        if req_headers is None:
            req_headers = cabeceras_request(request, completas=not al_cerrar)
        reg = {
            "ts": meta["ts"],
            "metodo": meta["metodo"],
            "url": meta["url"],
            "tipo": meta["tipo"],
            "status": status,
            "duracion_ms": round(((fin or time.time()) - meta["t0"]) * 1000),
            "request_headers": req_headers,
            "request_body": meta["request_body"],
            "response_headers": resp_headers,
            "response_body": cuerpo,
        }
        if sin_payload(meta["url"]):
            nota = ("payload omitido: lleva credenciales. " + (nota or "")).strip()
        if nota:
            reg["nota"] = nota
        if meta.get("fuera_catalogo"):
            reg["fuera_catalogo"] = True
            reg["nota"] = ("Fuera del catalogo de endpoints rastreados: se guarda "
                           "porque fallo. " + (nota or "")).strip()
        rastreados = self.alcance.casar_endpoints(meta["url"])
        if rastreados:
            reg["rastreados"] = rastreados
        if self.obs.redactar:
            redactar_registro(reg)
        return reg

    # -- desde el loop
    def drenar(self):
        self.drenar_respuestas()
        self.drenar_fallos()
        self.drenar_huerfanos()

    def drenar_respuestas(self):
        """Lee los bodies en el loop principal, no dentro del handler."""
        # de a una: si un Ctrl+C corta a mitad, lo que falta sigue en la cola
        # y rescatar_en_vuelo lo registra con su status
        while self.cola_resp:
            response = self.cola_resp.pop(0)
            meta = self.pend_req.pop(response.request, None) or {
                "ts": ahora_iso(), "t0": time.time(), "metodo": response.request.method,
                "url": response.url, "tipo": response.request.resource_type,
                "request_headers": None, "request_body": None,
            }
            cuerpo, nota = None, None
            # un endpoint rastreado siempre conserva su cuerpo, sea del tipo que sea
            es_rastreado = bool(self.alcance.casar_endpoints(meta["url"]))
            if meta["tipo"] in TIPOS_SIN_CUERPO and not es_rastreado:
                nota = "cuerpo omitido (%s)" % meta["tipo"]
            else:
                try:
                    raw = self.cuerpos.pop(response, None)
                    if raw is None:
                        raw = response.body()
                    if len(raw) > MAX_BODY:
                        cuerpo = raw[:MAX_BODY].decode("utf-8", "replace")
                        nota = f"truncado en {MAX_BODY} bytes (real: {len(raw)})"
                    else:
                        cuerpo = raw.decode("utf-8", "replace")
                except Exception as e:
                    nota = f"body no disponible: {type(e).__name__}"
            try:
                resp_headers = response.all_headers()
            except Exception:
                resp_headers = {}

            reg = self.registro(meta, response.status, resp_headers, cuerpo, nota,
                                request=response.request)
            # los complementos leen meta y cuerpo crudos, antes de redactar
            self.obs.avisar("respuesta_leida", meta, cuerpo)
            paso = self.obs.guardar(reg, pagina_de(response.request),
                                    t0_ms=meta["t0"] * 1000)
            self.obs.avisar("respuesta_guardada", paso)

    def drenar_huerfanos(self, forzar=False, al_cerrar=False):
        """Registra lo que Chrome vio y Playwright nunca reporto.

        Un POST con JSON lleva preflight OPTIONS; si el preflight falla (500 o
        sin Access-Control-Allow-Origin), Chrome corta el POST y DevTools lo
        pinta como "CORS error", pero Playwright puede no emitir ni 'request'
        ni 'requestfailed' para el: el request-data que fallaba desaparecia de
        la evidencia. La sesion CDP si lo ve, asi que se registra desde ahi.
        """
        ahora = time.time()
        for rid, info in list(self.cdp_red.items()):
            fin = info.get("fin")
            if fin is None and not forzar:
                continue                      # sigue en vuelo
            if fin is not None and not forzar and ahora - fin < ESPERA_HUERFANO_S:
                continue                      # da tiempo a que Playwright hable
            self.cdp_red.pop(rid, None)
            if self._consumir_visto(info):
                continue                      # Playwright ya lo registro
            pagina = info.get("pagina")
            if not self.alcance.pagina_permitida(pagina):
                continue
            status = info.get("status") or 0
            error = info.get("error")
            # Playwright nunca ve los preflight, y lo de fuera del catalogo
            # solo se guarda si fallo
            if (info.get("metodo") == "OPTIONS" or info.get("tipo") == "preflight"
                    or info.get("fuera_catalogo")) and not error and status < 400:
                continue
            headers = info.get("headers") or {}
            cuerpo = None
            if fin is not None and not error and not al_cerrar and info.get("sesion"):
                try:
                    r = info["sesion"].send("Network.getResponseBody", {"requestId": rid})
                    cuerpo = r.get("body")
                except Exception:
                    pass
            partes = ["Playwright no reporto este request; se registro desde la "
                      "sesion CDP de Chrome."]
            if info.get("metodo") == "OPTIONS":
                partes.append("Es el preflight CORS del request real: con este "
                              "status Chrome no llega a enviarlo.")
            if info.get("cors"):
                partes.append("Chrome lo bloqueo por CORS (%s): el servidor respondio "
                              "%s sin un Access-Control-Allow-Origin valido."
                              % (info["cors"], status or "?"))
            elif error:
                partes.append("El navegador corto el request (%s)%s."
                              % (error, ", status %s" % status if status else ""))
            elif fin is None:
                partes.append("Seguia en vuelo cuando se cerro el observador.")
            pistas = ["%s: %s" % (k, headers[k]) for k in ("x-cache", "content-type")
                      if headers.get(k)]
            if pistas:
                partes.append(" | ".join(pistas))
            meta = {"ts": info["ts"], "t0": info["t0"], "metodo": info.get("metodo"),
                    "url": info["url"], "tipo": info.get("tipo") or "fetch",
                    "request_headers": info.get("req_headers") or {},
                    "request_body": info.get("post"),
                    "fuera_catalogo": info.get("fuera_catalogo")}
            reg = self.registro(meta, status, headers, cuerpo, " ".join(partes),
                                fin=fin, al_cerrar=al_cerrar)
            reg["origen"] = "cdp"
            if error or fin is None:
                reg["fallo"] = error or SIN_RESPUESTA
            if info.get("cors"):
                reg["cors"] = info["cors"]
            self.obs.guardar(reg, pagina, t0_ms=info["t0"] * 1000, al_cerrar=al_cerrar)
            print("   [x] %s %s -> %s %s (visto solo por CDP)"
                  % (meta["metodo"], meta["url"], status or "-",
                     "bloqueado por CORS" if info.get("cors") else (error or "")))

    def drenar_fallos(self, forzar=False, al_cerrar=False):
        """Registra los requests que el navegador corto, con el status real si
        el servidor alcanzo a responder."""
        ahora = time.time() * 1000
        quedan = []
        for request, cuando in self.cola_fallos:
            if not forzar and ahora - cuando < ESPERA_FALLO_MS:
                quedan.append((request, cuando))
                continue
            meta = self.pend_req.pop(request, None)
            if meta is None:
                continue
            info = self.info_cdp(meta["metodo"], meta["url"])
            status = info.get("status") or 0
            headers = info.get("headers") or {}
            error = request.failure or info.get("error") or "fallo"
            if info.get("cors"):
                nota = ("Chrome bloqueo la respuesta por CORS (%s): el servidor "
                        "respondio %s sin Access-Control-Allow-Origin valido, asi "
                        "que el front nunca la pudo leer." % (info["cors"], status or "?"))
            elif status:
                nota = "El servidor respondio %s, pero el navegador corto el request (%s)." % (status, error)
            else:
                nota = "El navegador corto el request sin respuesta del servidor (%s)." % error
            pistas = ["%s: %s" % (k, headers[k]) for k in ("x-cache", "content-type")
                      if headers.get(k)]
            if pistas:
                nota += " " + " | ".join(pistas)
            reg = self.registro(meta, status, headers, None, nota, fin=cuando / 1000,
                                request=request, al_cerrar=al_cerrar)
            reg["fallo"] = error
            if info.get("cors"):
                reg["cors"] = info["cors"]
            self.obs.guardar(reg, pagina_de(request), t0_ms=meta["t0"] * 1000,
                             al_cerrar=al_cerrar)
            print("   [x] %s %s -> %s %s" % (meta["metodo"], meta["url"], status or "-",
                                            "bloqueado por CORS" if info.get("cors") else error))
        self.cola_fallos = quedan

    # -- al parar
    def esperar_en_vuelo(self, pagina, segundos):
        """Al parar, da tiempo a que respondan los requests que siguen en vuelo.

        Un request-data que tarda 12 s y se para la captura a los 5 quedaba
        fuera de la evidencia, aunque luego DevTools mostrara su 500.
        """
        limite = time.time() + segundos
        if self.pend_req and segundos > 0:
            print("Esperando %d request(s) en vuelo (max %d s):"
                  % (len(self.pend_req), segundos))
            for m in self.pend_req.values():
                print("   %s %s" % (m["metodo"], ruta_de(m["url"])))
        while (self.pend_req or self.huerfanos_en_vuelo()) and time.time() < limite:
            pagina.wait_for_timeout(200)
            self.drenar()
        self.drenar_huerfanos(forzar=True)

    def huerfanos_en_vuelo(self):
        """Requests que solo CDP vio salir y que todavia no terminan."""
        return [i for i in self.cdp_red.values()
                if i.get("fin") is None and not i.get("fuera_catalogo")
                and not self.pw_vistos.get((i.get("metodo"), i["url"]))
                and i.get("metodo") != "OPTIONS"]

    def rescatar_en_vuelo(self):
        """Lo que no se pudo leer al cerrar igual queda en la evidencia, marcado.

        No toca Playwright (solo atributos ya cargados en Python): tambien lo
        llama el hilo vigilante cuando el loop se colgo.
        """
        pendientes, self.cola_resp = self.cola_resp, []
        for response in pendientes:
            meta = self.pend_req.pop(response.request, None)
            if meta is None:
                continue
            raw = self.cuerpos.pop(response, None)
            reg = self.registro(meta, response.status, {},
                                raw[:MAX_BODY].decode("utf-8", "replace") if raw else None,
                                None if raw else
                                "Respondio, pero el observador cerro antes de leer el cuerpo.",
                                request=response.request, al_cerrar=True)
            self.obs.guardar(reg, pagina_de(response.request), al_cerrar=True)
        self.drenar_fallos(forzar=True, al_cerrar=True)
        self.drenar_huerfanos(forzar=True, al_cerrar=True)
        for request, meta in list(self.pend_req.items()):
            self.pend_req.pop(request, None)
            reg = self.registro(meta, 0, {}, None,
                                "Seguia en vuelo cuando se cerro el observador: no se "
                                "alcanzo a ver su respuesta.",
                                request=request, al_cerrar=True)
            reg["fallo"] = SIN_RESPUESTA
            self.obs.guardar(reg, pagina_de(request), al_cerrar=True)
            print("   [x] %s %s -> sin respuesta al cerrar" % (meta["metodo"], meta["url"]))

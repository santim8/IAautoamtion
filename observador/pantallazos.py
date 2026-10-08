"""Todos los screenshots de la corrida.

  screenshot.png                     al entrar a la pantalla (o diferido, si el
                                     paso se abrio antes de que pintara)
  screenshot_2.png                   pantallazo extra, mas tarde (--pantallazo-extra)
  screenshot_on_response_<slug>.png  cuando responde un servicio clave
                                     (--screenshot-on-response)

Los handlers de Playwright solo capturan o agendan; lo que toca disco o espera
a que la pagina pinte corre desde el loop (ver tick).
"""
import os
import re
import time

from observador.config import (MAX_REINTENTO_SHOT_MS, SHOT_RESPUESTA_DEFAULT,
                               SHOT_TRAS_RECARGA)

PREFIJO_RESPUESTA = "screenshot_on_response_"


def slug_disparador(patron):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", patron).strip("-")


def etiqueta_shot(nombre):
    """screenshot_on_response_request-offer.png -> request-offer"""
    return nombre[len(PREFIJO_RESPUESTA):-len(".png")]


class Pantallazos:
    def __init__(self, obs, settle_ms, disparadores=None, pantallazo_extra=None,
                 extra_ms=3000):
        self.obs = obs
        self.settle_ms = settle_ms
        # tomar pantallazo cuando responda ciertos endpoints clave
        # (hardcodeado: request/offer para capturar estado de personalización)
        patrones = disparadores or SHOT_RESPUESTA_DEFAULT
        if isinstance(patrones, str):
            patrones = [x.strip() for x in patrones.split(",") if x.strip()]
        self.disparadores = patrones
        # pantallas que ademas merecen un segundo pantallazo mas tarde
        # (pantalla final / thank-you page: suele pintar contenido async)
        self.pantallazo_extra = pantallazo_extra or []
        self.extra_ms = extra_ms
        self.extras = []             # [(paso, pagina, cuando_ms)] pantallazos extra
        self.diferidos = []          # [(paso, pagina, cuando_ms)] shot de paso adelantado
        self.listos = []             # [(pagina, nombre, bytes)] shots por responder
        self.tarde = []              # [(pagina, nombre, cuando_ms, intentos)] esperan render
        self.disparados = set()      # (paso, patron) ya disparados, para no repetir

    # -- al abrir un paso
    def retratar_paso(self, paso, page, shot_en=None):
        if shot_en is None:
            try:
                page.screenshot(path=os.path.join(paso["dir"], "screenshot.png"),
                                full_page=True)
            except Exception as e:
                print(f"  ! no pude capturar pantalla del paso {paso['idx']}: {e}")
        else:
            # el paso se abrio antes de tiempo para no perder trafico; el
            # screenshot igual espera a que la pantalla termine de pintar
            self.diferidos.append((paso, page, shot_en))

    def agendar_extra(self, paso, page):
        if any(pat in paso["url"] for pat in self.pantallazo_extra):
            self.extras.append((paso, page, time.time() * 1000 + self.extra_ms))
            print(f"         -> pantallazo extra en {self.extra_ms} ms")

    # -- por respuesta de un servicio
    def disparar(self, response, pagina):
        """Retrata la pantalla en el instante en que responde un servicio clave.

        Se dispara una sola vez por paso y por patron: el preflight OPTIONS y el
        POST de un mismo endpoint casan igual, y no hace falta el mismo
        pantallazo dos veces.
        """
        if not self.disparadores or pagina is None:
            return
        paso = self.obs.paso_por_pagina.get(pagina)
        idx = paso["idx"] if paso else -1
        for patron in self.disparadores:
            if patron not in response.url:
                continue
            metodo = SHOT_TRAS_RECARGA.get(patron)
            if metodo and response.request.method != metodo:
                continue
            if (idx, patron) in self.disparados:
                continue
            self.disparados.add((idx, patron))
            nombre = PREFIJO_RESPUESTA + slug_disparador(patron) + ".png"
            # Un documento acaba de llegar: la pagina todavia no pinto nada y
            # retratarla ahora daria una hoja en blanco. Los XHR si valen en el
            # instante, que es de lo que se trata: ver la pantalla con el dato
            # que acaba de responder.
            try:
                es_documento = response.request.resource_type == "document"
            except Exception:
                es_documento = False
            if es_documento or metodo:
                self.tarde.append(
                    (pagina, nombre, time.time() * 1000 + self.settle_ms, 0))
                print("   [shot] %s %s; retrato cuando la pantalla se asiente"
                      % (patron, "cargo" if es_documento
                         else "respondio al " + metodo))
                continue
            try:
                self.listos.append((pagina, nombre,
                                    pagina.screenshot(full_page=True, timeout=5000)))
                print("   [shot] %s respondio; pantalla capturada" % patron)
            except Exception as e:
                # no se pierde: lo reintenta el loop (ver tomar_tarde)
                self.tarde.append(
                    (pagina, nombre, time.time() * 1000 + self.settle_ms, 1))
                print("! pantallazo al responder %s fallo (%s); reintento cuando "
                      "la pantalla se asiente" % (patron, type(e).__name__))

    # -- desde el loop
    def tick(self):
        self.tomar_tarde()
        self.volcar()
        self.tomar_extras()
        self.tomar_diferidos()

    def tomar_tarde(self, forzar=False):
        """Retrata lo que espero a que la pagina pintara.

        Mientras la pestana tenga un cambio sin asentar (recarga, ruta nueva) se
        sigue esperando: un screenshot a mitad de navegacion se cuelga hasta el
        timeout. Si aun asi falla, se reintenta sin limite de tiempo hasta que
        salga o se cierre la pestana; al parar (forzar) va un ultimo intento.
        """
        ahora = time.time() * 1000
        quedan = []
        for pagina, nombre, cuando, intentos in self.tarde:
            if not forzar and (ahora < cuando or pagina in self.obs.pendientes):
                quedan.append((pagina, nombre, cuando, intentos))
                continue
            etiqueta = etiqueta_shot(nombre)
            try:
                self.listos.append(
                    (pagina, nombre, pagina.screenshot(full_page=True, timeout=5000)))
                if intentos:
                    print("   [shot] %s capturado al intento %d"
                          % (etiqueta, intentos + 1))
            except Exception as e:
                if forzar or pagina.is_closed():
                    print("! pantallazo de %s fallo: %s" % (etiqueta, e))
                    continue
                intentos += 1
                if intentos == 1:
                    print("   [shot] %s: la pantalla sigue cargando; reintento"
                          % etiqueta)
                espera = min(self.settle_ms * intentos, MAX_REINTENTO_SHOT_MS)
                quedan.append((pagina, nombre, time.time() * 1000 + espera,
                               intentos))
        self.tarde = quedan

    def volcar(self):
        """Escribe los pantallazos ya con el paso resuelto.

        Se hace desde el loop y despues de drenar respuestas, para que un
        request que adelanta de paso deje su pantallazo en el paso correcto.
        No toca Playwright: se puede llamar al cerrar o desde el hilo vigilante.
        """
        if not self.listos:
            return
        pendientes, self.listos = self.listos, []
        for pagina, nombre, datos in pendientes:
            paso = self.obs.paso_por_pagina.get(pagina) or self.obs.paso_actual()
            if paso is None:
                continue
            try:
                with open(os.path.join(paso["dir"], nombre), "wb") as f:
                    f.write(datos)
                print("[paso %02d] pantallazo al responder %s"
                      % (paso["idx"], etiqueta_shot(nombre)))
            except OSError as e:
                print("! no pude guardar %s: %s" % (nombre, e))

    def tomar_extras(self, forzar=False):
        """Segundo pantallazo de las pantallas marcadas, ya con el contenido pintado."""
        ahora = time.time() * 1000
        quedan = []
        for paso, page, cuando in self.extras:
            if not forzar and ahora < cuando:
                quedan.append((paso, page, cuando))
                continue
            try:
                page.screenshot(path=os.path.join(paso["dir"], "screenshot_2.png"),
                                full_page=True)
                print(f"[paso {paso['idx']:02d}] pantallazo extra guardado")
            except Exception as e:
                print(f"  ! pantallazo extra del paso {paso['idx']} fallo: {e}")
        self.extras = quedan

    def tomar_diferidos(self, forzar=False):
        """Screenshot de los pasos que se abrieron antes de cumplirse el settle."""
        ahora = time.time() * 1000
        quedan = []
        for paso, page, cuando in self.diferidos:
            if not forzar and ahora < cuando:
                quedan.append((paso, page, cuando))
                continue
            try:
                page.screenshot(path=os.path.join(paso["dir"], "screenshot.png"),
                                full_page=True)
            except Exception as e:
                print(f"  ! no pude capturar pantalla del paso {paso['idx']}: {e}")
        self.diferidos = quedan

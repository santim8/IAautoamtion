"""El nucleo: pasos y orquestacion de las piezas.

La unidad de evidencia es el PASO (una pantalla). Se abre un paso nuevo cuando
cambia la URL -- por navegacion real o por ruta de SPA (history.pushState) -- y
todos los requests que ocurren hasta el siguiente cambio quedan agrupados ahi.

El Observador no captura nada por si mismo: engancha cada pestana a sus piezas
(red, pantallazos, sockets), decide en que paso cae cada cosa y avisa a los
complementos.
"""
import os
import time

from observador.config import TOLERANCIA_CAMBIO_MS
from observador.pantallazos import Pantallazos
from observador.red import CapturaRed
from observador.sockets import CapturaSocket
from observador.util import ahora_iso, anexar_jsonl, es_url_real, slug_de_url

JS_HOOK_RUTA = """
(() => {
  if (window.__obsHooked) return;
  window.__obsHooked = true;
  const avisar = () => { try { window.__obsRuta(location.href); } catch (e) {} };
  for (const m of ['pushState', 'replaceState']) {
    const orig = history[m];
    history[m] = function () { const r = orig.apply(this, arguments); avisar(); return r; };
  }
  window.addEventListener('popstate', avisar);
  window.addEventListener('hashchange', avisar);
})();
"""


class Observador:
    def __init__(self, dir_salida, alcance, redactar, settle_ms,
                 pantallazo_extra=None, extra_ms=3000,
                 screenshot_on_response=None, complementos=()):
        self.dir = dir_salida
        self.alcance = alcance       # que pestana y que requests (alcance.Alcance)
        self.redactar = redactar
        self.settle_ms = settle_ms
        self.complementos = list(complementos)
        self.pasos = []              # [{idx, url, slug, dir, ts, pestana, requests: [...]}]
        self.pendientes = {}         # pagina -> (url, timestamp_ms) cambio en espera
        self.paso_por_pagina = {}    # pagina -> su paso actual (soporte multi-pestana)
        self.ids_pagina = {}         # pagina -> numero de pestana, para el reporte
        self.pagina_actual = None
        self.sin_reporte = False     # se paro pidiendo NO generar el reporte
        self.validacion = []         # resultado del soft assert de esquemas (al cerrar)
        self.ruta_esquemas = None
        self.pantallazos = Pantallazos(self, settle_ms, screenshot_on_response,
                                       pantallazo_extra, extra_ms)
        self.red = CapturaRed(self)
        self.sockets = CapturaSocket(self)

    # lo que el cierre lee de cualquier observador (ver disco.ObsDesdeDisco)
    @property
    def endpoints(self):
        return self.alcance.endpoints

    @property
    def sin_pestana(self):
        return self.alcance.sin_pestana

    def avisar(self, gancho, *args):
        """Llama ese gancho en cada complemento (ver complementos.Complemento)."""
        for c in self.complementos:
            getattr(c, gancho)(self, *args)

    # -- pasos
    def paso_actual(self):
        return self.pasos[-1] if self.pasos else None

    def id_pestana(self, page):
        if page not in self.ids_pagina:
            self.ids_pagina[page] = len(self.ids_pagina)
        return self.ids_pagina[page]

    def marcar_cambio(self, page, url, forzar=False):
        """Handler ligero: solo agenda. El screenshot lo toma el loop principal.

        Se agenda POR PAGINA: si hay varias pestanas abiertas, cada una lleva su
        propio hilo de pantallas y no se pisan entre si.

        forzar=True abre paso nuevo aunque la URL sea la misma: es lo que hace
        que una recarga (F5) quede como su propia evidencia.
        """
        if not es_url_real(url):
            return
        self.alcance.intentar_lock(page, url)   # quiza esta pestana es la que esperabamos
        if not self.alcance.pagina_permitida(page):
            return
        actual = self.paso_por_pagina.get(page)
        if not forzar and actual and actual["url"] == url and page not in self.pendientes:
            return
        self.pendientes[page] = (url, time.time() * 1000)

    def detectar_recarga(self, page, request):
        """Recarga = documento pedido de nuevo para la MISMA url del paso actual.

        Es la senal que separa un F5 de un cambio de ruta de la SPA: el pushState
        no pide documento, la recarga si. Sin esto marcar_cambio deduplica la
        recarga por URL repetida y la pantalla nueva nunca se captura.
        """
        try:
            if request.resource_type != "document" or request.frame != page.main_frame:
                return
            url = request.url
        except Exception:
            return
        actual = self.paso_por_pagina.get(page)
        if actual and actual["url"] == url and page not in self.pendientes:
            print("   (recarga de %s)" % url)
            self.marcar_cambio(page, url, forzar=True)

    def abrir_paso(self, page, url, shot_en=None):
        idx = len(self.pasos)
        slug = slug_de_url(url)
        d = os.path.join(self.dir, f"{idx:02d}_{slug}")
        os.makedirs(d, exist_ok=True)
        paso = {"idx": idx, "url": url, "slug": slug, "dir": d,
                "ts": ahora_iso(), "requests": [], "sockets": [], "titulo": "",
                "pestana": self.id_pestana(page)}
        self.pasos.append(paso)
        self.paso_por_pagina[page] = paso
        try:
            paso["titulo"] = page.title()
        except Exception:
            pass
        self.pantallazos.retratar_paso(paso, page, shot_en)
        etiqueta = f" [pestana {paso['pestana']}]" if len(self.ids_pagina) > 1 else ""
        print(f"[paso {idx:02d}]{etiqueta} {url}")
        self.pantallazos.agendar_extra(paso, page)
        self.avisar("paso_abierto", paso)
        return paso

    def adelantar_paso(self, pagina):
        """Abre ya el paso que esperaba el settle, para que el request caiga ahi."""
        url_nueva, t_cambio = self.pendientes.pop(pagina)
        try:
            url_real = pagina.url or url_nueva
        except Exception:
            url_real = url_nueva
        actual = self.paso_por_pagina.get(pagina)
        if actual and actual["url"] == url_real:
            return
        try:
            self.abrir_paso(pagina, url_real, shot_en=t_cambio + self.settle_ms)
        except Exception:
            pass

    def asentar_cambios(self):
        """Cada pestana con un cambio ya "asentado" abre su propio paso."""
        ahora = time.time() * 1000
        for pagina, (url, t0) in list(self.pendientes.items()):
            if ahora - t0 < self.settle_ms:
                continue
            self.pendientes.pop(pagina, None)
            try:
                url_real = pagina.url
            except Exception:
                continue  # pestana cerrada mientras esperabamos
            actual = self.paso_por_pagina.get(pagina)
            if not actual or actual["url"] != url_real:
                self.abrir_paso(pagina, url_real)

    def vaciar_pendientes(self):
        """Al cerrar, abrir los pasos que quedaron esperando el settle.

        Sin esto se pierde la ultima pantalla del flujo, que es justo la que
        importa (pantalla final / thank-you page) si das Ctrl+C apenas llegas.
        """
        for pagina, (url, _t0) in list(self.pendientes.items()):
            self.pendientes.pop(pagina, None)
            try:
                url_real = pagina.url
                actual = self.paso_por_pagina.get(pagina)
                if not actual or actual["url"] != url_real:
                    self.abrir_paso(pagina, url_real)
            except Exception:
                continue

    # -- evidencia
    def guardar(self, reg, pagina=None, t0_ms=None, al_cerrar=False):
        # Si la ruta de esta pestana ya cambio y el paso nuevo sigue esperando el
        # settle, el request es de la pantalla NUEVA: el settle existe para que la
        # pantalla pinte antes del screenshot, no para agrupar el trafico.
        # al_cerrar=True no abre pasos: eso toca Playwright, y al cerrar puede
        # estar colgado (o hablarse desde el hilo vigilante).
        if not al_cerrar and pagina is not None and pagina in self.pendientes:
            _url, t_cambio = self.pendientes[pagina]
            if t0_ms is None or t0_ms >= t_cambio - TOLERANCIA_CAMBIO_MS:
                self.adelantar_paso(pagina)
        # el request va al paso de SU pestana, no al ultimo paso global
        paso = self.paso_por_pagina.get(pagina) if pagina is not None else None
        if paso is None:
            paso = self.paso_actual()
        if paso is None:
            # llego trafico antes de la primera pantalla: abrimos paso al vuelo
            # para no perderlo (se corre desde el loop principal, es seguro)
            pag = pagina or self.pagina_actual
            if pag is None or al_cerrar:
                return None
            try:
                paso = self.abrir_paso(pag, pag.url)
            except Exception:
                return None
        self.anotar(paso, reg)
        return paso

    def anotar(self, paso, reg):
        """Un registro mas en el paso, y en su requests.jsonl de una vez."""
        paso["requests"].append(reg)
        anexar_jsonl(os.path.join(paso["dir"], "requests.jsonl"), reg)

    # -- enganche a una pagina
    def enganchar(self, page):
        if page in self.ids_pagina:
            return  # ya enganchada
        self.id_pestana(page)
        self.red.enganchar(page)
        page.on("request", lambda req, _p=page: self.detectar_recarga(_p, req))
        page.on("framenavigated",
                lambda fr: self.marcar_cambio(page, fr.url) if fr == page.main_frame else None)
        page.on("close", lambda _p=page: self.pendientes.pop(_p, None))
        # una pestana abierta POR la observada (popup de biometria, OAuth, etc.)
        page.on("popup", lambda hija, _p=page: self.alcance.registrar_hija(_p, hija))
        page.on("websocket", lambda ws, _p=page: self.sockets.enganchar(_p, ws))
        try:
            # expose_binding (no expose_function) para saber DESDE QUE pestana llego
            page.expose_binding("__obsRuta",
                                lambda source, url: self.marcar_cambio(source["page"], url))
        except Exception:
            pass  # ya estaba expuesta en esta pagina
        try:
            page.add_init_script(JS_HOOK_RUTA)   # documentos futuros
            page.evaluate(JS_HOOK_RUTA)          # documento actual
        except Exception:
            pass
        self.pagina_actual = page

    # -- ciclo de vida
    def tick(self):
        """Una vuelta del loop principal, despues de bombear los eventos."""
        self.red.drenar()
        self.volcar_complementos()
        self.asentar_cambios()
        self.pantallazos.tick()

    def volcar_complementos(self):
        self.avisar("volcar")

    def parar(self, activa, espera_en_vuelo):
        """Al parar: lo del ultimo instante, lo que sigue en vuelo y el cierre
        de los complementos.

        Cada etapa va por separado: tras un Ctrl+C, Playwright ya esta
        cancelando sus tareas y leer los bodies pendientes puede reventar. Que
        eso NO impida el reporte.
        """
        try:
            self.pantallazos.tomar_tarde(forzar=True)
            self.pantallazos.volcar()           # no perder los del ultimo instante
            self.vaciar_pendientes()            # no perder la ultima pantalla
            self.pantallazos.tomar_diferidos(forzar=True)
            self.pantallazos.tomar_extras(forzar=True)
        except BaseException:
            pass
        try:
            self.red.drenar_respuestas()
            self.red.esperar_en_vuelo(activa, espera_en_vuelo)
            # lo que respondio mientras se esperaba (el login, p. ej.)
            # tambien deja su pantallazo
            self.pantallazos.tomar_tarde(forzar=True)
            self.pantallazos.volcar()
        except BaseException:
            pend = len(self.red.cola_resp)
            if pend:
                print("(%d respuesta(s) pendientes no se pudieron leer)" % pend)
        # lo que siga sin leer o sin respuesta queda marcado, no desaparece
        try:
            self.red.rescatar_en_vuelo()
        except BaseException:
            pass
        for c in self.complementos:
            try:
                c.cerrar(self)
                c.volcar(self)
            except BaseException:
                pass

    def rescatar_al_cerrar(self):
        """Lo que quedo en memoria pasa a disco antes de escribir las salidas.

        Los pantallazos por respuesta se capturan en el handler y se escriben
        desde el loop; si el loop se colgo siguen en memoria. Igual con los
        requests que no alcanzaron a leerse y lo que respondieron los
        complementos. Nada de esto toca Playwright, asi que es seguro incluso
        desde el hilo vigilante.
        """
        for etapa in (self.pantallazos.volcar, self.red.rescatar_en_vuelo,
                      self.volcar_complementos):
            try:
                etapa()
            except (AttributeError, OSError):
                pass

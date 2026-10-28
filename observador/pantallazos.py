"""Todos los screenshots de la corrida.

  screenshot.png                     al entrar a la pantalla (o diferido, si el
                                     paso se abrio antes de que pintara)
  screenshot_2.png                   pantallazo extra, mas tarde (--pantallazo-extra)
  screenshot_on_response_<slug>.png  cuando responde un servicio clave
                                     (--screenshot-on-response)
  screenshot_mensaje[_<sistema>].png cuando el front termina de pintar un
                                     mensaje de rechazo o error, con su ficha
                                     .json al lado (ver config.SELECTOR_MENSAJE)

Los handlers de Playwright solo capturan o agendan; lo que toca disco o espera
a que la pagina pinte corre desde el loop (ver tick).
"""
import json
import os
import re
import time

from observador.analisis import etiqueta_fallo
from observador.config import (ESPERA_ERROR_GIGYA_MS, MAX_ESPERA_MENSAJE_MS,
                               MAX_REINTENTO_SHOT_MS, MENSAJE_ESTABLE_MS,
                               MENSAJE_VACIO_MS,
                               PANTALLA_LISTA, SELECTOR_ERROR_GIGYA,
                               SELECTOR_MENSAJE, SHOT_RESPUESTA_DEFAULT,
                               SHOT_TRAS_RECARGA, VALIDACIONES_CON_MENSAJE)
from observador.endpoints import casan
from observador.util import ahora_iso, ruta_de

PREFIJO_RESPUESTA = "screenshot_on_response_"
PREFIJO_MENSAJE = "screenshot_mensaje"

# Vigila que aparezca el componente de mensaje del front y avisa (__obsMensaje)
# cuando su texto dejo de cambiar: monta vacio y el contenido llega de Drupal.
# Pasado el tope avisa igual, con completo=false.
JS_HOOK_MENSAJE = """
(() => {
  if (window.__obsMensajeHooked) return;
  window.__obsMensajeHooked = true;
  const SEL = %(selector)s, ESTABLE = %(estable)d, TOPE = %(tope)d, VACIO = %(vacio)d;
  const vistos = new WeakSet();
  // el titulo es el texto mas grande del mensaje
  const titulo = (el) => {
    let mejor = '', tam = 0;
    for (const n of el.querySelectorAll('h1,h2,h3,h4,p,span')) {
      const t = (n.innerText || '').trim();
      const px = parseFloat(getComputedStyle(n).fontSize) || 0;
      if (t && px > tam) { mejor = t; tam = px; }
    }
    return mejor;
  };
  const vigilar = (el) => {
    if (vistos.has(el)) return;
    vistos.add(el);
    const t0 = Date.now();
    let previo = null, desde = t0;
    const mirar = () => {
      if (!el.isConnected) return;   // se desmonto antes de pintar
      const texto = (el.innerText || '').trim();
      if (texto !== previo) { previo = texto; desde = Date.now(); }
      const caja = el.getBoundingClientRect();
      const imagenes = [...el.querySelectorAll('img')]
        .every((i) => i.complete || i.loading === 'lazy');
      // sin texto puede ser que Drupal aun no responde, o que no tiene
      // contenido para ese codigo: se espera mas antes de darlo por vacio
      const listo = imagenes && caja.width > 0 && caja.height > 0
        && Date.now() - desde >= (texto ? ESTABLE : VACIO);
      if (!listo && Date.now() - t0 < TOPE) { setTimeout(mirar, 150); return; }
      try {
        window.__obsMensaje({fuente: el.dataset.source || '', titulo: titulo(el),
                             texto, espera_ms: Date.now() - t0, completo: listo});
      } catch (e) {}
    };
    mirar();
  };
  const buscar = () => document.querySelectorAll(SEL).forEach(vigilar);
  new MutationObserver(buscar).observe(document, {childList: true, subtree: true});
  buscar();
})();
""" % {"selector": json.dumps(SELECTOR_MENSAJE), "estable": MENSAJE_ESTABLE_MS,
       "tope": MAX_ESPERA_MENSAJE_MS, "vacio": MENSAJE_VACIO_MS}


def slug_disparador(patron):
    return re.sub(r"[^A-Za-z0-9._-]+", "-", patron).strip("-")


def etiqueta_shot(nombre):
    """screenshot_on_response_request-offer.png -> request-offer"""
    return nombre[len(PREFIJO_RESPUESTA):-len(".png")]


def regla_pantalla(url):
    """(selector, tope_ms) si esa pantalla pinta su contenido despues de cargar."""
    ruta = ruta_de(url)
    for patron, regla in PANTALLA_LISTA.items():
        if re.search(patron, ruta):
            return regla
    return None


# Gigya deja en el DOM las pantallas que no usa, ocultas: cuenta solo lo que
# tiene caja en pantalla.
JS_VISIBLE = """(sel) => [...document.querySelectorAll(sel)].some(e =>
  e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden')"""


def esta_visible(pagina, selector):
    try:
        return bool(pagina.evaluate(JS_VISIBLE, selector))
    except Exception:
        return False            # navegando o cerrada: todavia no


def cambio_de_pantalla(pagina, url):
    """La pestana ya no esta en esa ruta (o se cerro)."""
    try:
        return pagina.is_closed() or ruta_de(pagina.url) != ruta_de(url)
    except Exception:
        return True


def error_gigya(cuerpo):
    """errorCode de la respuesta de Gigya (0 = ok), o None si no se pudo leer."""
    try:
        return json.loads(cuerpo).get("errorCode")
    except (TypeError, ValueError, AttributeError):
        return None


def sistema_de(url):
    """SAP, ASCARD o SIIF si la URL es de una validacion que pinta mensaje."""
    for patron in casan(list(VALIDACIONES_CON_MENSAJE), ruta_de(url)):
        return VALIDACIONES_CON_MENSAJE[patron]
    return None


def motivo_rechazo(reg):
    """Por que no paso una validacion, o None si paso.

    No pasa si el servicio fallo (status >= 400, CORS, sin respuesta) o si
    respondio con resultadoValidacion.estado distinto de OK.
    """
    if reg.get("fallo") or (reg.get("status") or 0) >= 400:
        return {"status": reg.get("status"),
                "codigo": etiqueta_fallo(reg) or "HTTP %s" % reg.get("status")}
    try:
        rv = json.loads(reg.get("response_body") or "")["resultadoValidacion"]
    except (ValueError, TypeError, KeyError):
        return None
    if not isinstance(rv, dict) or rv.get("estado") in (None, "OK"):
        return None
    err = rv.get("datosError") or {}
    return {"status": reg.get("status"), "estado": rv["estado"],
            "codigo": err.get("codigoErrorValidacion"),
            "regla": err.get("reglaErrorValidacion"),
            "descripcion": err.get("descripcionErrorValidacion")}


def linea_mensaje(ficha):
    """Una linea para la consola y el reporte con lo que dice la ficha."""
    val = ficha.get("validacion") or {}
    pantalla = ficha.get("pantalla") or {}
    motivo = ": ".join(str(x) for x in (val.get("codigo"), val.get("regla")) if x)
    partes = []
    if val:
        partes.append("tras rechazo de %s (%s)" % (val.get("sistema"), motivo or "-"))
    if pantalla and not (pantalla.get("titulo") or pantalla.get("texto")):
        partes.append("VACIO: el front pinto el mensaje sin texto (Drupal no tiene "
                      "contenido para ese codigo)")
    elif pantalla:
        partes.append('"%s"' % (pantalla.get("titulo") or pantalla.get("texto", "")[:80]))
        if not pantalla.get("completo"):
            partes.append("(seguia cambiando a los %d s)" % (MAX_ESPERA_MENSAJE_MS // 1000))
    elif ficha.get("salida"):
        partes.append("sin mensaje: el front llevo a %s" % ficha["salida"])
    else:
        partes.append("sin mensaje del front: pantalla como estaba")
    return "mensaje en pantalla " + " ".join(partes)


def leer_mensajes(paso):
    """[(png o None, ficha)] de los mensajes retratados en ese paso, en orden."""
    try:
        nombres = sorted(f for f in os.listdir(paso["dir"])
                         if f.startswith(PREFIJO_MENSAJE) and f.endswith(".json"))
    except OSError:
        return []
    mensajes = []
    for f in nombres:
        try:
            with open(os.path.join(paso["dir"], f), encoding="utf-8") as fh:
                ficha = json.load(fh)
        except (OSError, ValueError):
            continue
        png = f[:-len(".json")] + ".png"
        mensajes.append((png if os.path.exists(os.path.join(paso["dir"], png))
                         else None, ficha))
    return mensajes


def mensajes_en_pantalla(pasos):
    """Todos los mensajes de la corrida, en orden, con el paso donde salieron."""
    return [dict(ficha, paso=paso["idx"], pantallazo=png)
            for paso in pasos for png, ficha in leer_mensajes(paso)]


def _imprimir(linea):
    """El texto del mensaje viene de Drupal: en una consola cp1252 un caracter
    raro no puede tumbar el loop."""
    try:
        print(linea)
    except UnicodeEncodeError:
        print(linea.encode("ascii", "backslashreplace").decode("ascii"))


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
        # [(paso, pagina, cuando_ms, selector, limite_ms)] shot de entrada que
        # espera: el settle, o a que la pantalla este lista (PANTALLA_LISTA)
        self.diferidos = []
        self.listos = []             # [(pagina, nombre, bytes)] shots por responder
        # [(pagina, nombre, cuando_ms, intentos, url, espera)] esperan render;
        # espera = (selector, limite_ms) o None
        self.tarde = []
        self.disparados = set()      # (paso, patron) ya disparados, para no repetir
        self.mensajes = []           # [(pagina, datos)] mensajes ya pintados (hook JS)
        # pagina -> (motivo, limite_ms, url, paso) validacion caida
        self.rechazos = {}
        # [(pagina, ficha, png, paso o None)] mensajes por escribir
        self.retratos = []
        # pagina -> (idx del paso, ruta de la ficha) del ultimo mensaje que se
        # retrato sin saber que validacion lo causo
        self.sin_motivo = {}

    # -- al abrir un paso
    def retratar_paso(self, paso, page, shot_en=None):
        regla = regla_pantalla(paso["url"])
        if shot_en is None and regla is None:
            try:
                page.screenshot(path=os.path.join(paso["dir"], "screenshot.png"),
                                full_page=True)
            except Exception as e:
                print(f"  ! no pude capturar pantalla del paso {paso['idx']}: {e}")
            return
        # el paso se abrio antes de tiempo para no perder trafico, o la
        # pantalla pinta su contenido despues: el screenshot espera
        ahora = time.time() * 1000
        selector, tope = regla or (None, 0)
        self.diferidos.append((paso, page, shot_en if shot_en is not None else ahora,
                               selector, ahora + tope))

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
            ahora = time.time() * 1000
            url = pagina.url
            # Un documento acaba de llegar: la pagina todavia no pinto nada y
            # retratarla ahora daria una hoja en blanco. Los XHR si valen en el
            # instante, que es de lo que se trata: ver la pantalla con el dato
            # que acaba de responder.
            try:
                es_documento = response.request.resource_type == "document"
            except Exception:
                es_documento = False
            if metodo:
                error = error_gigya(self.obs.red.cuerpos.get(response))
                if error == 0:
                    print("   [shot] %s OK: la pantalla siguiente queda en su paso" % patron)
                    continue
                self.tarde.append((pagina, nombre, ahora + self.settle_ms, 0, url,
                                   (SELECTOR_ERROR_GIGYA, ahora + ESPERA_ERROR_GIGYA_MS)))
                print("   [shot] %s respondio con error %s; retrato cuando Gigya lo pinte"
                      % (patron, error if error is not None else "(sin leer)"))
                continue
            if es_documento:
                regla = regla_pantalla(response.url)
                self.tarde.append((pagina, nombre, ahora + self.settle_ms, 0, url,
                                   (regla[0], ahora + regla[1]) if regla else None))
                print("   [shot] %s cargo; retrato cuando la pantalla se asiente" % patron)
                continue
            try:
                self.listos.append((pagina, nombre,
                                    pagina.screenshot(full_page=True, timeout=5000)))
                print("   [shot] %s respondio; pantalla capturada" % patron)
            except Exception as e:
                # no se pierde: lo reintenta el loop (ver tomar_tarde)
                self.tarde.append((pagina, nombre, ahora + self.settle_ms, 1, url, None))
                print("! pantallazo al responder %s fallo (%s); reintento cuando "
                      "la pantalla se asiente" % (patron, type(e).__name__))

    # -- mensajes en pantalla
    def mensaje_pintado(self, pagina, datos):
        """Handler del hook JS: el front termino de pintar un mensaje. Se
        retrata desde el loop."""
        if self.obs.alcance.pagina_permitida(pagina):
            self.mensajes.append((pagina, datos or {}))

    def anotar_rechazo(self, reg, pagina):
        """Si el request es una validacion que no paso, el mensaje que pinte el
        front lleva su nombre; si no aparece a tiempo, se retrata igual."""
        sistema = sistema_de(reg["url"])
        if sistema is None or pagina is None:
            return
        motivo = motivo_rechazo(reg)
        if motivo is None:
            return
        motivo.update(sistema=sistema, endpoint=reg["url"], ts=reg["ts"])
        if self.completar_mensaje(pagina, motivo):
            return
        # la URL y el paso de ahora: si el front se va a otra pantalla en vez
        # de pintar el mensaje (retanqueo -> CFA), la salida queda en este paso
        try:
            url = pagina.url
        except Exception:
            url = ""
        self.rechazos[pagina] = (motivo, time.time() * 1000 + MAX_ESPERA_MENSAJE_MS,
                                 url, self.obs.paso_por_pagina.get(pagina))
        print("   [msg] %s no paso (%s); espero el mensaje en pantalla o la pantalla siguiente"
              % (sistema, motivo["codigo"]))

    def completar_mensaje(self, pagina, motivo):
        """El mensaje ya se retrato antes de saber que validacion lo causo (el
        cuerpo de un 500 puede tardar minutos en llegar): se le agrega el
        motivo a esa ficha en vez de tomar un segundo pantallazo."""
        previo = self.sin_motivo.get(pagina)
        paso = self.obs.paso_por_pagina.get(pagina)
        if not previo or not paso or previo[0] != paso["idx"]:
            return False
        self.sin_motivo.pop(pagina, None)
        try:
            with open(previo[1], encoding="utf-8") as f:
                ficha = json.load(f)
            ficha["validacion"] = motivo
            with open(previo[1], "w", encoding="utf-8") as f:
                json.dump(ficha, f, ensure_ascii=False, indent=2)
        except (OSError, ValueError):
            return False
        _imprimir("[paso %02d] %s" % (paso["idx"], linea_mensaje(ficha)))
        return True

    def tomar_mensajes(self, forzar=False):
        """Retrata los mensajes ya pintados, y las validaciones caidas cuyo
        mensaje no aparecio a tiempo (o todas, al parar)."""
        pintados, self.mensajes = self.mensajes, []
        for pagina, datos in pintados:
            motivo = self.rechazos.pop(pagina, (None,))[0]
            self._retratar_mensaje(pagina, motivo, datos)
        ahora = time.time() * 1000
        for pagina, (motivo, limite, url, paso) in list(self.rechazos.items()):
            if url and cambio_de_pantalla(pagina, url):
                # no hubo mensaje: el front llevo a otra pantalla (SIIF con
                # retanqueo -> CFA). Esa pantalla tiene su propio paso y su
                # pantallazo; aqui solo queda a donde fue.
                self.rechazos.pop(pagina, None)
                try:
                    salida = "" if pagina.is_closed() else pagina.url
                except Exception:
                    salida = ""
                self.retratos.append((pagina, {"ts": ahora_iso(), "validacion": motivo,
                                               "pantalla": None, "salida": salida or "(cerrada)"},
                                      None, paso))
            elif forzar or ahora >= limite:
                self.rechazos.pop(pagina, None)
                self._retratar_mensaje(pagina, motivo, None)

    def _retratar_mensaje(self, pagina, motivo, pantalla):
        ficha = {"ts": ahora_iso(), "validacion": motivo, "pantalla": pantalla}
        png = None
        try:
            if not pagina.is_closed():
                png = pagina.screenshot(full_page=True, timeout=5000)
        except Exception as e:
            # la ficha se guarda igual: el texto del mensaje ya es evidencia
            print("! pantallazo del mensaje fallo: %s" % e)
        self.retratos.append((pagina, ficha, png, None))

    def volcar_mensajes(self):
        """Escribe pantallazo y ficha de cada mensaje en el paso de su pestana
        (o en el paso donde fallo la validacion, si la pestana ya se fue).
        No toca Playwright."""
        pendientes, self.retratos = self.retratos, []
        for pagina, ficha, png, paso in pendientes:
            paso = paso or self.obs.paso_por_pagina.get(pagina) or self.obs.paso_actual()
            if paso is None:
                continue
            sistema = (ficha.get("validacion") or {}).get("sistema")
            raiz = PREFIJO_MENSAJE + ("_" + sistema if sistema else "")
            base, n = raiz, 1
            while os.path.exists(os.path.join(paso["dir"], base + ".json")):
                n += 1
                base = "%s_%d" % (raiz, n)
            try:
                if png:
                    with open(os.path.join(paso["dir"], base + ".png"), "wb") as f:
                        f.write(png)
                with open(os.path.join(paso["dir"], base + ".json"), "w",
                          encoding="utf-8") as f:
                    json.dump(ficha, f, ensure_ascii=False, indent=2)
            except OSError as e:
                print("! no pude guardar %s: %s" % (base, e))
                continue
            if ficha.get("validacion") is None and ficha.get("pantalla"):
                self.sin_motivo[pagina] = (paso["idx"], os.path.join(paso["dir"], base + ".json"))
            _imprimir("[paso %02d] %s" % (paso["idx"], linea_mensaje(ficha)))

    # -- desde el loop
    def tick(self):
        self.tomar_tarde()
        self.tomar_mensajes()
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
        for pagina, nombre, cuando, intentos, url, espera in self.tarde:
            if not forzar and (ahora < cuando or pagina in self.obs.pendientes):
                quedan.append((pagina, nombre, cuando, intentos, url, espera))
                continue
            etiqueta = etiqueta_shot(nombre)
            if cambio_de_pantalla(pagina, url):
                print("   [shot] %s: la pantalla cambio antes de quedar lista; no se retrata"
                      % etiqueta)
                continue
            if espera and not esta_visible(pagina, espera[0]):
                if not forzar and ahora < espera[1]:
                    quedan.append((pagina, nombre, cuando, intentos, url, espera))
                    continue
                print("   [shot] %s: no aparecio lo que se esperaba; se retrata como esta"
                      % etiqueta)
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
                pausa = min(self.settle_ms * intentos, MAX_REINTENTO_SHOT_MS)
                quedan.append((pagina, nombre, time.time() * 1000 + pausa,
                               intentos, url, espera))
        self.tarde = quedan

    def volcar(self):
        """Escribe los pantallazos ya con el paso resuelto.

        Se hace desde el loop y despues de drenar respuestas, para que un
        request que adelanta de paso deje su pantallazo en el paso correcto.
        No toca Playwright: se puede llamar al cerrar o desde el hilo vigilante.
        """
        self.volcar_mensajes()
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
        """Screenshot de entrada de los pasos que esperan: el settle (se
        abrieron antes de tiempo) o a que la pantalla quede lista (login,
        politicas). Si la pestana ya cambio de ruta, no se toma: seria la
        pantalla siguiente guardada en este paso."""
        ahora = time.time() * 1000
        quedan = []
        for paso, page, cuando, selector, limite in self.diferidos:
            if not forzar and ahora < cuando:
                quedan.append((paso, page, cuando, selector, limite))
                continue
            if cambio_de_pantalla(page, paso["url"]):
                print("   [shot] paso %02d: la pantalla cambio antes de quedar lista; "
                      "queda sin pantallazo de entrada" % paso["idx"])
                continue
            if selector and not esta_visible(page, selector):
                if not forzar and ahora < limite:
                    quedan.append((paso, page, cuando, selector, limite))
                    continue
                print("   [shot] paso %02d: la pantalla no termino de cargar; se retrata "
                      "como esta" % paso["idx"])
            try:
                page.screenshot(path=os.path.join(paso["dir"], "screenshot.png"),
                                full_page=True)
            except Exception as e:
                print(f"  ! no pude capturar pantalla del paso {paso['idx']}: {e}")
        self.diferidos = quedan

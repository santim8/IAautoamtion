#!/usr/bin/env python3
"""Observador de analitica: tu haces el flujo a mano, el script anota el dataLayer.

Mismo mecanismo que DataLayerMonitor del framework Java: se engancha
`dataLayer.push` con un script que corre ANTES que los de la pagina en cada
documento nuevo, y cada evento se espeja en sessionStorage para que sobreviva a
los cambios de ruta de la SPA y a las recargas completas.

El filtro de ruido es el mismo de AnalyticsMappingReport.isNoise: fuera GTM
(`gtm.*`), Core Web Vitals, payloads vacios y el ping de routing
(`eventName=virtual_page` que no viaja como `event=virtual_page`).

Uso:
  python observador_analitica.py --flujo "terminos" --solo-url "creditos/solicitud"

Ctrl+C (o el panel) cierra y genera el reporte.
"""
import argparse
import html as _h
import json
import os
import re
import sys
import time
from datetime import datetime

from playwright.sync_api import sync_playwright

from observador_flujo import CSS_REPORTE, ahora_iso, lanzar_chrome, ruta_de

SALIDA_DEFAULT = "evidencias_analitica"
# Los modelo_de_datos[*].json contra los que se contrasta lo capturado. Son
# editables: agregar o cambiar una entrada alcanza para que un evento nuevo se
# valide, sin tocar codigo.
SPECS_DEFAULT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "analitica")
# Un mismo push puede quedar registrado varias veces (GTM reencola la cola al
# inicializar, y el hook llega a apilarse). Los duplicados llegan con el payload
# identico y milisegundos de diferencia; un evento repetido de verdad -- el
# usuario que vuelve a hacer clic -- esta mucho mas separado en el tiempo.
VENTANA_DUPLICADO = 2.0

# Intentos fallidos seguidos antes de rendirse. Si la conexion con la pestana
# se rompe, todos los siguientes fallan igual y no tiene sentido esperar.
FALLOS_PARA_CORTAR = 5

# Playwright espera 30 s por operacion. Con dos consultas por vuelta, una
# pestana que no responde dejaba el loop sordo al centinela durante un minuto
# largo: el usuario le daba a Detener y no pasaba nada.
TIMEOUT_MS = 5000

# Pantallas que no son del flujo que se esta revisando. Se comparan, exactas,
# contra el `url` y el `title` del payload; se amplia con --ignorar. No se usa
# el par event/eventName porque los modales del flujo (modal_reactivacion)
# llegan con la misma forma y esos si interesan.
IGNORADOS_DEFAULT = ["/login-progresive-perfil"]

# Valores de `event` que no son interaccion de negocio. pageView es el rastreo
# de pagina heredado: repite lo que ya dice virtual_page y llena el reporte de
# entradas duplicadas.
EVENTOS_TECNICOS = {"corewebvitals", "pageview"}

# Espejo de utils/DataLayerMonitor.java. Se mantiene igual a proposito: si el
# framework cambia el hook, este tiene que cambiar con el o dejarian de ver lo
# mismo.
MONITOR_JS = r"""
(() => {
  var KEY = '__dlEvents';
  var loadStored = function () {
    try { return JSON.parse(sessionStorage.getItem(KEY)) || []; } catch (e) { return []; }
  };
  var save = function (arr) {
    try { sessionStorage.setItem(KEY, JSON.stringify(arr)); } catch (e) {}
  };
  window.__dlEvents = (window.__dlEvents && window.__dlEvents.length)
    ? window.__dlEvents : loadStored();
  if (window.__dlMonitorInstalled) { return; }
  window.__dlMonitorInstalled = true;

  // Clonado JSON-safe: structuredClone conserva ciclos que luego revientan al
  // serializar. Se corta el ciclo y se descartan funciones.
  var clone = function (value) {
    var seen = new WeakSet();
    try {
      return JSON.parse(JSON.stringify(value, function (key, val) {
        if (typeof val === 'function') { return undefined; }
        if (typeof val === 'object' && val !== null) {
          if (seen.has(val)) { return '[Circular]'; }
          seen.add(val);
        }
        return val;
      }));
    } catch (e) { return { __unserializable: String(e) }; }
  };

  var logEvent = function (payload) {
    window.__dlEvents.push({
      timestamp: new Date().toISOString(),
      url: location.href,
      payload: clone(payload)
    });
    save(window.__dlEvents);
  };

  var hookDataLayer = function () {
    if (!window.dataLayer || typeof window.dataLayer.push !== 'function') { return; }
    // Idempotente: envolver un wrapper ya envuelto duplicaba cada evento.
    if (window.dataLayer.push.__dlWrapped) { return; }
    var realPush = window.dataLayer.push.bind(window.dataLayer);
    var wrapper = function () {
      try {
        Array.prototype.forEach.call(arguments, function (a) { logEvent(a); });
      } catch (e) {}
      return realPush.apply(window.dataLayer, arguments);
    };
    wrapper.__dlWrapped = true;
    window.dataLayer.push = wrapper;
  };

  var reHook = function () { setTimeout(hookDataLayer, 50); };
  ['pushState', 'replaceState'].forEach(function (m) {
    var original = history[m];
    if (typeof original !== 'function') { return; }
    history[m] = function () { var r = original.apply(this, arguments); reHook(); return r; };
  });
  window.addEventListener('popstate', reHook);
  window.addEventListener('hashchange', reHook);

  var lastRef = window.dataLayer;
  setInterval(function () {
    if (window.dataLayer !== lastRef) { lastRef = window.dataLayer; hookDataLayer(); }
    else if (window.dataLayer && typeof window.dataLayer.push === 'function'
             && !window.dataLayer.push.__dlWrapped) { hookDataLayer(); }
  }, 500);

  hookDataLayer();
})();
"""

ESTADO_JS = """() => ({
  instalado: !!window.__dlMonitorInstalled,
  enganchado: !!(window.dataLayer && window.dataLayer.push
                 && window.dataLayer.push.__dlWrapped)
})"""

LEER_JS = """() => {
  try { if (window.__dlEvents && window.__dlEvents.length) return JSON.stringify(window.__dlEvents); } catch (e) {}
  try { var s = sessionStorage.getItem('__dlEvents'); return s ? s : '[]'; } catch (e) { return '[]'; }
}"""


# --- filtro de ruido (espejo de AnalyticsMappingReport.isNoise) -------------
def es_ruido(payload, ignorados=None):
    if not isinstance(payload, dict) or not payload:
        return True
    for patron in (ignorados if ignorados is not None else IGNORADOS_DEFAULT):
        objetivo = patron.strip().lower()
        if objetivo and any(str(payload.get(c, "")).strip().lower() == objetivo
                            for c in ("url", "title")):
            return True
    if "__unserializable" in payload or "webVitalsMeasurement" in payload:
        return True
    if any(isinstance(k, str) and k.startswith("gtm.") for k in payload):
        return True
    evento = str(payload.get("event", "")).lower()
    if evento.startswith("gtm.") or evento in EVENTOS_TECNICOS:
        return True
    # A diferencia del framework Java, aqui NO se descarta el
    # eventName=virtual_page que viaja como event=interactivo: los modales
    # (modal_reactivacion, etc.) se anuncian asi y son eventos de negocio que
    # hay que ver. Alla se filtra como artefacto de routing; este observador
    # existe para mostrar todo lo que pasa.
    anidado = payload.get("value")
    if isinstance(anidado, dict) and str(anidado.get("event", "")).lower() == "corewebvitals":
        return True
    return False


def todas_las_paginas(browser):
    """Las pestanas de todos los contextos.

    Una pestana nueva no siempre aparece en el contexto que habia al conectar;
    mirando solo ese, la del flujo podia abrirse y no verse nunca.
    """
    paginas = []
    try:
        for ctx in browser.contexts:
            try:
                paginas.extend(ctx.pages)
            except Exception:
                continue
    except Exception:
        pass
    return paginas


def momento(iso):
    """Segundos del timestamp ISO del snapshot; None si no se puede leer."""
    try:
        return datetime.strptime(iso[:23], "%Y-%m-%dT%H:%M:%S.%f").timestamp()
    except (ValueError, TypeError):
        return None


def nombre_evento(payload):
    for clave in ("eventName", "event"):
        valor = str(payload.get(clave, "")).strip()
        if valor:
            return valor
    return "(sin nombre)"


# --- captura ---------------------------------------------------------------
class Analitica:
    def __init__(self, dir_salida, patron, ignorados=None):
        self.dir = dir_salida
        self.ignorados = (list(ignorados) if ignorados is not None
                          else list(IGNORADOS_DEFAULT))
        # varias rutas: el front vive en dos despliegues
        if isinstance(patron, str):
            patron = [x.strip() for x in patron.split(",") if x.strip()]
        self.patrones = list(patron or [])
        self.lock = None
        self.enganchadas = set()   # add_init_script se acumula: una vez por pagina
        self.por_enganchar = []    # pestanas nuevas, a enganchar desde el loop
        self.eventos = []          # snapshots en orden de captura
        self.vistos = set()        # (timestamp, payload) ya emitidos
        self.ultimos = {}          # payload -> momento en que se emitio
        self.ruido = 0
        self.colapsados = 0        # mismo push registrado mas de una vez
        self.quejas = set()        # fallos ya avisados, para no repetirlos
        self.reinstalos = 0
        self.fallos_seguidos = 0   # la pagina dejo de responder
        self.dir_specs = SPECS_DEFAULT
        self.validacion = None

    def quejarse(self, que, error):
        """Avisa una vez por tipo de fallo. Callar dejaba la captura en cero
        sin ninguna pista de por que."""
        clave = "%s|%s" % (que, type(error).__name__)
        if clave in self.quejas:
            return
        self.quejas.add(clave)
        print("! %s: %s" % (que, str(error).splitlines()[0]))

    def asegurar(self, page):
        """El monitor tiene que seguir puesto; si no, se repone.

        add_init_script solo corre en documentos nuevos y hay navegaciones
        donde no alcanza a aplicarse. Sin esta comprobacion la pagina se queda
        sin hook y no se captura nada.
        """
        try:
            estado = page.evaluate(ESTADO_JS)
            self.fallos_seguidos = 0
        except Exception as e:
            self.fallos_seguidos += 1
            self.quejarse("no pude consultar el estado del monitor", e)
            return
        if estado.get("instalado"):
            return
        try:
            page.evaluate(MONITOR_JS)
            self.reinstalos += 1
            print("   [monitor] repuesto tras una navegacion")
        except Exception as e:
            self.quejarse("no pude reponer el monitor", e)

    def anotar_pagina(self, page):
        """Handler ligero: solo apunta la pestana nueva.

        Hacer llamadas de Playwright dentro de un handler rompe el loop de la
        API sincrona: a partir de ahi todo falla con "Event loop is closed" y
        la captura se queda en cero. El trabajo real lo hace el loop.
        """
        self.por_enganchar.append(page)

    def enganchar_pendientes(self):
        pendientes, self.por_enganchar = self.por_enganchar, []
        for page in pendientes:
            self.enganchar(page)

    def enganchar(self, page):
        """Instala el monitor. Devuelve si la pestana respondio.

        Callar aqui era grave: una pestana muerta -- de una corrida anterior que
        quedo abierta -- se enganchaba "bien", se fijaba el candado en ella y
        toda la captura se iba al vacio.
        """
        # add_init_script se acumula: llamarlo dos veces deja dos copias del
        # monitor corriendo en cada documento nuevo.
        if page in self.enganchadas:
            return True
        try:
            page.set_default_timeout(TIMEOUT_MS)
            page.add_init_script(MONITOR_JS)   # documentos futuros
            page.evaluate(MONITOR_JS)          # el documento actual
        except Exception as e:
            self.quejarse("no pude instalar el monitor en una pestana", e)
            return False
        self.enganchadas.add(page)
        return True

    def buscar_pestana(self, paginas):
        """Fija la pestana del flujo. Compara contra la ruta, no contra el query
        ni el fragmento: las paginas de SSO llevan la URL de la app en el hash."""
        if self.lock is not None or not self.patrones:
            return
        for pg in paginas:
            try:
                url = pg.url
            except Exception:
                continue
            if not any(p in ruta_de(url) for p in self.patrones):
                continue
            if not self.enganchar(pg):
                print(">> %s no responde; la salto y sigo buscando." % url[:70])
                continue
            self.lock = pg
            print("\n>> Pestana fijada: %s\n" % url)
            return

    def recoger(self, page):
        """Lee lo acumulado y emite solo lo que no habiamos visto."""
        try:
            crudo = page.evaluate(LEER_JS)
            self.fallos_seguidos = 0
        except Exception as e:
            self.fallos_seguidos += 1
            self.quejarse("no pude leer los eventos de la pagina", e)
            return
        try:
            snapshots = json.loads(crudo or "[]")
        except (json.JSONDecodeError, TypeError):
            return
        for snap in snapshots:
            payload = snap.get("payload")
            clave = (snap.get("timestamp", ""),
                     json.dumps(payload, sort_keys=True, ensure_ascii=False))
            if clave in self.vistos:
                continue
            self.vistos.add(clave)
            if es_ruido(payload, self.ignorados):
                self.ruido += 1
                continue
            firma = clave[1]
            cuando = momento(snap.get("timestamp", ""))
            previo = self.ultimos.get(firma)
            if (previo is not None and cuando is not None
                    and abs(cuando - previo) <= VENTANA_DUPLICADO):
                self.colapsados += 1
                continue           # el mismo push, registrado otra vez
            if cuando is not None:
                self.ultimos[firma] = cuando
            snap["_n"] = len(self.eventos) + 1
            self.eventos.append(snap)
            # append inmediato: si el proceso muere, los eventos ya estan en
            # disco y el reporte se rehace desde ahi
            try:
                with open(os.path.join(self.dir, "eventos.jsonl"), "a",
                          encoding="utf-8") as f:
                    f.write(json.dumps(snap, ensure_ascii=False) + "\n")
            except OSError:
                pass
            print("[ev %02d] %-34s %s"
                  % (snap["_n"], nombre_evento(payload),
                     ruta_de(snap.get("url", ""))[:70]))


# --- salida ----------------------------------------------------------------
CSS_EXTRA = """
  .ev { background:var(--card); border:1px solid var(--bd); border-left:3px solid var(--acc);
        border-radius:4px; margin-bottom:6px; }
  .ev.repe { border-left-color:var(--mut); opacity:.75; }
  .ev summary { cursor:pointer; padding:7px 10px; display:flex; gap:12px;
                align-items:center; font-size:12px; }
  .ev .num { font-weight:700; min-width:30px; color:var(--mut); }
  .ev .nom { font-weight:700; min-width:220px; }
  .ev .ruta { flex:1; color:var(--mut); word-break:break-all;
              font-family:ui-monospace,Consolas,monospace; }
  .ev .hora { color:var(--mut); white-space:nowrap; }
  .marca { background:var(--mut); color:#fff; font-size:9px; font-weight:700;
           padding:1px 5px; border-radius:3px; }
  .resumen b { color:var(--fg); }
  .val { margin:0 0 20px; }
  .val h3 { font-size:14px; margin:0 0 8px; }
  .val h3 small { color:var(--mut); font-weight:400; margin-left:6px; }
  .val table { border-collapse:collapse; width:100%; font-size:12px; }
  .val td { padding:4px 8px; border-bottom:1px solid var(--bd); vertical-align:top; }
  .val .st { width:56px; font-weight:700; white-space:nowrap; }
  .val tr.ok .st { color:var(--ok); }
  .val tr.falla .st { color:var(--err); }
  .val tr.sinspec .st { color:var(--mut); }
  .val .sp { color:var(--mut); font-family:ui-monospace,Consolas,monospace; }
  .val ul { margin:4px 0 0; padding-left:18px; color:var(--err); }
  .val li { font-family:ui-monospace,Consolas,monospace; font-size:11px; }
  .ev.nook { border-left-color:var(--err); }
  .chip { font-size:9px; font-weight:700; padding:1px 5px; border-radius:3px;
          letter-spacing:.4px; }
  .chip.mal { background:var(--err); color:#fff; }
  .chip.nospec { background:var(--mut); color:#fff; }
"""


def _bloque_validacion(val, esc):
    """Que dice el modelo_de_datos de cada evento capturado."""
    if not val or not val["resultados"]:
        return ""
    filas = []
    cuenta = {"ok": 0, "falla": 0, "sin-spec": 0}
    for r in val["resultados"]:
        cuenta[r["estado"]] += 1
        cls = {"ok": "ok", "falla": "falla", "sin-spec": "sinspec"}[r["estado"]]
        etiqueta = {"ok": "ok", "falla": "FALLA", "sin-spec": "sin spec"}[r["estado"]]
        lista = ("<ul>" + "".join("<li>" + esc(e) + "</li>" for e in r["errores"])
                 + "</ul>") if r["errores"] else ""
        filas.append(
            '<tr class="' + cls + '">'
            '<td class="st">' + esc(etiqueta) + '</td>'
            '<td>#' + esc(r["n"]) + ' ' + esc(r["evento"]) + lista + '</td>'
            '<td class="sp">' + esc(r["spec"]) + '</td></tr>')
    return ('<section class="val"><h3>Validacion contra modelo_de_datos '
            '<small>' + esc(cuenta["ok"]) + ' ok &middot; '
            + esc(cuenta["falla"]) + ' con fallas &middot; '
            + esc(cuenta["sin-spec"]) + ' sin spec &middot; '
            + esc(val["specs"]) + '</small></h3>'
            '<table>' + "".join(filas) + '</table></section>')


def escribir_reporte(obs, flujo, ruta):
    def esc(x):
        return _h.escape(str(x) if x is not None else "")

    # por numero de evento, para marcar cada fila con su veredicto
    veredictos = {r["n"]: r for r in
                  ((obs.validacion or {}).get("resultados") or [])}

    filas = []
    firmas = {}
    for snap in obs.eventos:
        payload = snap.get("payload") or {}
        firma = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        repetido = firma in firmas
        firmas.setdefault(firma, snap["_n"])
        v = veredictos.get(snap["_n"])
        estado = v["estado"] if v else None
        chip = ""
        if estado == "falla":
            chip = '<span class="chip mal">no cumple spec</span>'
        elif estado == "sin-spec":
            chip = '<span class="chip nospec">sin spec</span>'
        filas.append(
            '<details class="ev' + (' repe' if repetido else '')
            + (' nook' if estado == "falla" else '') + '"><summary>'
            '<span class="num">#' + esc(snap["_n"]) + '</span>'
            '<span class="nom">' + esc(nombre_evento(payload)) + '</span>'
            + chip
            + ('<span class="marca">repite #' + esc(firmas[firma]) + '</span>'
               if repetido else '')
            + '<span class="ruta">' + esc(ruta_de(snap.get("url", ""))) + '</span>'
            '<span class="hora">' + esc(snap.get("timestamp", "")[11:19]) + '</span>'
            '</summary><div class="det"><pre>'
            + esc(json.dumps(payload, indent=2, ensure_ascii=False))
            + '</pre></div></details>')

    distintos = len(firmas)
    doc = (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Analitica - ' + esc(flujo) + '</title>'
        '<style>' + CSS_REPORTE + CSS_EXTRA + '</style></head><body>'
        '<header><h1>Eventos de analitica &mdash; ' + esc(flujo) + '</h1>'
        '<p class="resumen"><b>' + esc(len(obs.eventos)) + '</b> eventos de negocio '
        '&middot; <b>' + esc(distintos) + '</b> distintos &middot; '
        + esc(obs.ruido) + ' de ruido tecnico omitidos (GTM / web-vitals)'
        + (' &middot; ' + esc(obs.colapsados) + ' duplicados colapsados'
           if obs.colapsados else '')
        + ' &middot; generado ' + esc(ahora_iso()) + '</p></header>'
        + _bloque_validacion(obs.validacion, esc)
        + ("".join(filas) or '<p class="vacio">No se capturo ningun evento de negocio.</p>')
        + '</body></html>'
    )
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(doc)


def validar_contra_specs(eventos, dir_specs):
    """Contrasta cada evento con su entrada de modelo_de_datos.

    Se apoya en analitica/validar_eventos.py para no tener dos criterios de
    validacion viviendo en paralelo. Si ese modulo no esta, no pasa nada: el
    reporte sale igual, solo que sin la seccion de validacion.
    """
    if not dir_specs or not os.path.isdir(dir_specs):
        return None
    sys.path.insert(0, dir_specs)
    try:
        import validar_eventos as ve
    except ImportError as e:
        print("! no pude cargar el validador: %s" % e)
        return None
    try:
        specs = ve.cargar_specs(dir_specs)
    except (OSError, ValueError) as e:
        print("! no pude leer los specs: %s" % e)
        return None
    if not specs:
        return None

    filas = []
    for snap in eventos:
        payload = snap.get("payload") or {}
        if payload.get("event") != "interactivo" or not payload.get("eventName"):
            continue           # el validador solo cubre los de interaccion
        nombre, entrada = ve.enrutar(payload, specs)
        if not entrada:
            filas.append({"n": snap["_n"], "evento": nombre_evento(payload),
                          "estado": "sin-spec", "spec": "", "errores": [],
                          "avisos": []})
            continue
        errores, avisos = ve.validar(payload, entrada)
        filas.append({"n": snap["_n"], "evento": nombre_evento(payload),
                      "estado": "falla" if errores else "ok",
                      "spec": "%s :: %s" % (nombre, entrada.get("evento", "")),
                      "errores": errores, "avisos": avisos})
    return {"specs": os.path.abspath(dir_specs), "resultados": filas}


def cerrar(obs, flujo, incremental=True):
    with open(os.path.join(obs.dir, "eventos.json"), "w", encoding="utf-8") as f:
        json.dump(obs.eventos, f, ensure_ascii=False, indent=2)
    with open(os.path.join(obs.dir, "payloads.json"), "w", encoding="utf-8") as f:
        json.dump([s.get("payload") for s in obs.eventos], f,
                  ensure_ascii=False, indent=2)
    obs.validacion = validar_contra_specs(obs.eventos, obs.dir_specs)
    if obs.validacion:
        with open(os.path.join(obs.dir, "validacion.json"), "w",
                  encoding="utf-8") as f:
            json.dump(obs.validacion, f, ensure_ascii=False, indent=2)
    escribir_reporte(obs, flujo, os.path.join(obs.dir, "reporte.html"))

    distintos = len({json.dumps(s.get("payload"), sort_keys=True, ensure_ascii=False)
                     for s in obs.eventos})
    print("\n%d evento(s) de negocio, %d distintos, %d de ruido omitidos%s"
          % (len(obs.eventos), distintos, obs.ruido,
             ", %d duplicados colapsados" % obs.colapsados if obs.colapsados else ""))
    if obs.reinstalos:
        print("(el monitor se repuso %d vez/veces tras navegar)" % obs.reinstalos)
    if not obs.eventos and not obs.ruido:
        print("\nNo llego NINGUN push, ni siquiera ruido de GTM. Suele ser que la"
              "\npestana observada no es la del flujo, o que se cerro y el "
              "candado\nquedo apuntando a una pagina muerta.")
    if obs.eventos:
        print("\n--- eventos capturados ---")
        for snap in obs.eventos:
            print("  %2d  %-34s %s" % (snap["_n"], nombre_evento(snap["payload"]),
                                       ruta_de(snap.get("url", ""))[:64]))
    val = obs.validacion
    if val and val["resultados"]:
        malos = [r for r in val["resultados"] if r["estado"] == "falla"]
        sin = [r for r in val["resultados"] if r["estado"] == "sin-spec"]
        print("\n--- validacion contra modelo_de_datos ---")
        print("  specs: %s" % val["specs"])
        for r in val["resultados"]:
            marca = {"ok": "ok  ", "falla": "FALLA", "sin-spec": "?   "}[r["estado"]]
            print("  %s #%-2s %-16s %s" % (marca, r["n"], r["evento"], r["spec"]))
            for e in r["errores"]:
                print("          %s" % e)
        print("  %d ok, %d con fallas, %d sin spec"
              % (len(val["resultados"]) - len(malos) - len(sin), len(malos),
                 len(sin)))
    print("\nEvidencia: " + os.path.abspath(obs.dir))
    print("Reporte:   " + os.path.abspath(os.path.join(obs.dir, "reporte.html")))


def rehacer_reporte(dir_evidencia):
    """Regenera el reporte desde eventos.jsonl, sin volver a navegar."""
    jsonl = os.path.join(dir_evidencia, "eventos.jsonl")
    if not os.path.exists(jsonl):
        print("No encontre eventos.jsonl en %s" % dir_evidencia)
        return 1
    obs = Analitica(dir_evidencia, None)
    with open(jsonl, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if not linea:
                continue
            try:
                snap = json.loads(linea)
            except json.JSONDecodeError:
                continue          # linea a medias por un cierre abrupto
            snap["_n"] = len(obs.eventos) + 1
            obs.eventos.append(snap)
    print("Reconstruyendo desde %s" % os.path.abspath(dir_evidencia))
    cerrar(obs, os.path.basename(dir_evidencia.rstrip("/\\")), incremental=False)
    return 0


# --- main ------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(
        description="Anota los eventos de dataLayer mientras haces el flujo a mano.")
    ap.add_argument("--flujo", default="analitica", help="nombre (va en la carpeta)")
    ap.add_argument("--solo-url", default="creditos/solicitud,loans-dev-solicitud", metavar="PATRON",
                    help="observa SOLO la pestana cuya ruta contenga PATRON; "
                         "varias separadas por coma")
    ap.add_argument("--puerto", type=int, default=9222, help="puerto CDP de Chrome")
    ap.add_argument("--out", default=SALIDA_DEFAULT, help="carpeta raiz de salida")
    ap.add_argument("--stop-file", default=None, metavar="RUTA",
                    help="corta limpiamente cuando aparezca ese archivo (lo usa el panel)")
    ap.add_argument("--specs", default=SPECS_DEFAULT, metavar="DIR",
                    help="carpeta con los modelo_de_datos[*].json contra los "
                         "que validar (default: %(default)s)")
    ap.add_argument("--ignorar", default=",".join(IGNORADOS_DEFAULT),
                    metavar="LISTA",
                    help="pantallas a no mapear, por url o title exactos, "
                         "separadas por coma (default: %(default)s)")
    ap.add_argument("--rehacer-reporte", default=None, metavar="DIR",
                    help="regenera el reporte desde eventos.jsonl de una corrida")
    ap.add_argument("--lanzar-chrome", action="store_true",
                    help="abre Chrome con el puerto de depuracion y sale")
    args = ap.parse_args()

    if args.lanzar_chrome:
        return lanzar_chrome(args.puerto)
    if args.rehacer_reporte:
        return rehacer_reporte(args.rehacer_reporte)

    marca = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    dir_salida = os.path.join(args.out, "%s_%s" % (
        re.sub(r"[^A-Za-z0-9._-]+", "-", args.flujo), marca))
    os.makedirs(dir_salida, exist_ok=True)
    obs = Analitica(dir_salida, args.solo_url,
                    ignorados=[x.strip() for x in args.ignorar.split(",")
                               if x.strip()])
    obs.dir_specs = args.specs

    with sync_playwright() as p:
        try:
            browser = p.chromium.connect_over_cdp("http://localhost:%d" % args.puerto)
        except Exception as e:
            print("No pude conectar al puerto %d: %s" % (args.puerto, e))
            print("Lanza Chrome primero desde el panel, o con --lanzar-chrome.")
            return 1
        if not browser.contexts:
            print("Chrome esta conectado pero no tiene contexto abierto.")
            return 1
        # Solo se engancha la pestana del flujo, no todas las abiertas: hablarle
        # a una pestana vieja o colgada bloqueaba el arranque entero, y a las
        # ajenas no hay nada que mirarles. Las que se abran despues nacen
        # limpias, asi que esas si se enganchan de una para no perder sus
        # primeros push.
        for ctx in browser.contexts:
            ctx.on("page", obs.anotar_pagina)
        obs.buscar_pestana(todas_las_paginas(browser))

        print("Monitor de dataLayer instalado.")
        if obs.ignorados:
            print("No se mapean: %s" % ", ".join(obs.ignorados))
        print("Alcance: la pestana cuya ruta contenga \"%s\"" % args.solo_url)
        if obs.lock is None:
            print("Aun no veo esa pestana; navega a ella y la fijo automaticamente.")
        print("Haz el flujo a mano. Ctrl+C para cerrar y generar el reporte.\n")

        if args.stop_file and os.path.exists(args.stop_file):
            os.remove(args.stop_file)
        sin_reporte = False
        try:
            while True:
                if args.stop_file and os.path.exists(args.stop_file):
                    # el modo viaja dentro del centinela, como en el observador
                    try:
                        with open(args.stop_file, encoding="utf-8") as f:
                            sin_reporte = f.read().strip().lower() == "sin-reporte"
                    except OSError:
                        sin_reporte = False
                    print("\nParada solicitada%s."
                          % (" (sin reporte)" if sin_reporte else ""))
                    try:
                        os.remove(args.stop_file)
                    except OSError:
                        pass
                    break
                obs.enganchar_pendientes()
                if obs.lock is None:
                    # Sin candado no se interroga nada. Antes se caia sobre
                    # context.pages[0], que en un Chrome recien abierto es la
                    # pestana en blanco: fallaba, sumaba fallos y la corrida se
                    # cortaba sola antes de que hubiera flujo que mirar.
                    obs.buscar_pestana(todas_las_paginas(browser))
                    if obs.lock is None:
                        if not todas_las_paginas(browser):
                            print("\nNo quedan pestanas abiertas.")
                            break
                        time.sleep(0.7)
                        continue
                    obs.fallos_seguidos = 0
                pagina = obs.lock
                if obs.lock is not None and obs.lock not in todas_las_paginas(browser):
                    print("\nSe cerro la pestana observada; busco otra.")
                    obs.lock = None
                    obs.fallos_seguidos = 0
                    continue
                if obs.fallos_seguidos >= FALLOS_PARA_CORTAR:
                    # girar sin leer nada durante minutos no ayuda a nadie:
                    # mejor cortar y entregar lo que haya, diciendo por que
                    print("\nLa pagina observada dejo de responder (%d intentos"
                          " seguidos).\nCierro y genero el reporte con lo que"
                          " haya." % obs.fallos_seguidos)
                    break
                try:
                    obs.asegurar(pagina)
                    obs.recoger(pagina)
                    pagina.wait_for_timeout(700)
                except Exception:
                    if obs.lock is not None and obs.lock not in todas_las_paginas(browser):
                        print("\nSe cerro la pestana observada.")
                        break
                    time.sleep(0.7)
        except KeyboardInterrupt:
            print("\nCerrando...")
            sin_reporte = False
        finally:
            try:
                if obs.lock is not None:
                    obs.recoger(obs.lock)     # lo ultimo que haya entrado
            except Exception:
                pass
    if sin_reporte:
        print("\nDetenido sin generar el reporte.")
        print("Evidencia: " + os.path.abspath(obs.dir))
        print("Cuando quieras el reporte:  --rehacer-reporte \"%s\""
              % os.path.abspath(obs.dir))
    else:
        cerrar(obs, args.flujo)
    return 0


if __name__ == "__main__":
    sys.exit(main())

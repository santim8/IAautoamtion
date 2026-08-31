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
# Un mismo push puede quedar registrado varias veces (GTM reencola la cola al
# inicializar, y el hook llega a apilarse). Los duplicados llegan con el payload
# identico y milisegundos de diferencia; un evento repetido de verdad -- el
# usuario que vuelve a hacer clic -- esta mucho mas separado en el tiempo.
VENTANA_DUPLICADO = 2.0

# Pantallas que no son del flujo que se esta revisando. Se comparan, exactas,
# contra el `url` y el `title` del payload; se amplia con --ignorar. No se usa
# el par event/eventName porque los modales del flujo (modal_reactivacion)
# llegan con la misma forma y esos si interesan.
IGNORADOS_DEFAULT = ["/login-progresive-perfil"]

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
    if evento.startswith("gtm.") or evento == "corewebvitals":
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
        self.eventos = []          # snapshots en orden de captura
        self.vistos = set()        # (timestamp, payload) ya emitidos
        self.ultimos = {}          # payload -> momento en que se emitio
        self.ruido = 0
        self.colapsados = 0        # mismo push registrado mas de una vez

    def enganchar(self, page):
        # add_init_script se acumula: llamarlo dos veces deja dos copias del
        # monitor corriendo en cada documento nuevo.
        if page in self.enganchadas:
            return
        self.enganchadas.add(page)
        try:
            page.add_init_script(MONITOR_JS)   # documentos futuros
        except Exception:
            pass
        try:
            page.evaluate(MONITOR_JS)          # el documento actual
        except Exception:
            pass

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
            if any(p in ruta_de(url) for p in self.patrones):
                self.lock = pg
                self.enganchar(pg)
                print("\n>> Pestana fijada: %s\n" % url)
                return

    def recoger(self, page):
        """Lee lo acumulado y emite solo lo que no habiamos visto."""
        try:
            crudo = page.evaluate(LEER_JS)
        except Exception:
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
"""


def escribir_reporte(obs, flujo, ruta):
    def esc(x):
        return _h.escape(str(x) if x is not None else "")

    filas = []
    firmas = {}
    for snap in obs.eventos:
        payload = snap.get("payload") or {}
        firma = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        repetido = firma in firmas
        firmas.setdefault(firma, snap["_n"])
        filas.append(
            '<details class="ev' + (' repe' if repetido else '') + '"><summary>'
            '<span class="num">#' + esc(snap["_n"]) + '</span>'
            '<span class="nom">' + esc(nombre_evento(payload)) + '</span>'
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
        + ("".join(filas) or '<p class="vacio">No se capturo ningun evento de negocio.</p>')
        + '</body></html>'
    )
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(doc)


def cerrar(obs, flujo, incremental=True):
    with open(os.path.join(obs.dir, "eventos.json"), "w", encoding="utf-8") as f:
        json.dump(obs.eventos, f, ensure_ascii=False, indent=2)
    with open(os.path.join(obs.dir, "payloads.json"), "w", encoding="utf-8") as f:
        json.dump([s.get("payload") for s in obs.eventos], f,
                  ensure_ascii=False, indent=2)
    escribir_reporte(obs, flujo, os.path.join(obs.dir, "reporte.html"))

    distintos = len({json.dumps(s.get("payload"), sort_keys=True, ensure_ascii=False)
                     for s in obs.eventos})
    print("\n%d evento(s) de negocio, %d distintos, %d de ruido omitidos%s"
          % (len(obs.eventos), distintos, obs.ruido,
             ", %d duplicados colapsados" % obs.colapsados if obs.colapsados else ""))
    if obs.eventos:
        print("\n--- eventos capturados ---")
        for snap in obs.eventos:
            print("  %2d  %-34s %s" % (snap["_n"], nombre_evento(snap["payload"]),
                                       ruta_de(snap.get("url", ""))[:64]))
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
        context = browser.contexts[0]

        # Engancha lo que ya este abierto y lo que se abra despues: el monitor
        # tiene que estar puesto ANTES de que la pagina empiece a empujar.
        for pg in context.pages:
            obs.enganchar(pg)
        context.on("page", lambda pg: obs.enganchar(pg))
        obs.buscar_pestana(context.pages)

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
                if obs.lock is None:
                    obs.buscar_pestana(context.pages)
                pagina = obs.lock or (context.pages[0] if context.pages else None)
                if pagina is None:
                    print("\nNo quedan pestanas abiertas.")
                    break
                try:
                    obs.recoger(pagina)
                    pagina.wait_for_timeout(700)
                except Exception:
                    if obs.lock is not None and obs.lock not in context.pages:
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

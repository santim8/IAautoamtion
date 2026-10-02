"""DataLayerMonitor: captura los dataLayer.push de GTM.

El script se registra antes de los scripts de la pagina en cada documento
nuevo (add_init_script, como Page.addScriptToEvaluateOnNewDocument en Java) y
se ejecuta tambien en el documento actual. Guarda cada evento en
window.__dlEvents y en sessionStorage para que sobreviva a navegaciones.
"""
import time

STORAGE_KEY = "__dlEvents"

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
    ? window.__dlEvents
    : loadStored();
  if (window.__dlMonitorInstalled) { return; }
  window.__dlMonitorInstalled = true;

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
    } catch (e) {
      return { __unserializable: String(e) };
    }
  };
  var logEvent = function (payload, meta) {
    meta = meta || {};
    window.__dlEvents.push({
      timestamp: new Date().toISOString(),
      url: location.href,
      route_event: meta.route_event || false,
      payload: clone(payload)
    });
    save(window.__dlEvents);
  };
  var hookDataLayer = function () {
    if (!window.dataLayer || typeof window.dataLayer.push !== 'function') { return; }
    if (window.dataLayer.push.__dlWrapped) { return; }
    var realPush = window.dataLayer.push.bind(window.dataLayer);
    var wrapper = function () {
      var args = arguments;
      try { Array.prototype.forEach.call(args, function (arg) { logEvent(arg); }); } catch (e) {}
      return realPush.apply(window.dataLayer, args);
    };
    wrapper.__dlWrapped = true;
    window.dataLayer.push = wrapper;
  };
  var reHook = function () { setTimeout(hookDataLayer, 50); };
  var wrapHistoryMethod = function (methodName) {
    var original = history[methodName];
    if (typeof original !== 'function') { return; }
    history[methodName] = function () {
      var result = original.apply(this, arguments);
      reHook();
      return result;
    };
  };
  wrapHistoryMethod('pushState');
  wrapHistoryMethod('replaceState');
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

_LEER_JS = """() => {
  try { if (window.__dlEvents && window.__dlEvents.length) { return window.__dlEvents; } } catch (e) {}
  try { var s = sessionStorage.getItem('%s'); return s ? JSON.parse(s) : []; } catch (e) { return []; }
}""" % STORAGE_KEY


def install(driver):
    driver.context.add_init_script(MONITOR_JS)
    try:
        driver.page.evaluate(MONITOR_JS)
    except Exception as e:
        print("DataLayerMonitor: no se pudo instalar en el documento actual: %s" % e)


def get_events(driver):
    """Lista de {timestamp, url, route_event, payload}."""
    try:
        return driver.page.evaluate(_LEER_JS) or []
    except Exception:
        # La pagina puede estar navegando justo en ese instante.
        return []


def wait_for_event(driver, matcher, timeout_s):
    fin = time.time() + timeout_s
    while True:
        for snapshot in get_events(driver):
            payload = snapshot.get("payload")
            if isinstance(payload, dict) and matcher(payload):
                return payload
        if time.time() >= fin:
            return None
        time.sleep(0.5)


def wait_for_event_named(driver, nombre, timeout_s):
    return wait_for_event(
        driver, lambda e: str(e.get("eventName")).lower() == nombre.lower(), timeout_s)

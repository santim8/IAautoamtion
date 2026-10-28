"""Driver, DriverFactory y DriverManager en uno.

En Java cada hilo tenia su ChromeDriver (DriverManager con ThreadLocal) y el
DriverFactory instalaba un interceptor JS de fetch/XHR mas el performance log
de Chrome para ver los status HTTP. Playwright ya entrega cada respuesta como
evento, asi que aqui se registran directamente en self.respuestas y el
interceptor JS no hace falta.

lento=500 mete esos milisegundos antes de cada accion (clic, escribir, ir a
una URL; no en evaluate ni en las esperas): sirve para seguir el flujo en vivo.

dispositivo="Pixel 7" emula ese telefono (viewport, densidad, user agent movil
y tactil) con los perfiles de Playwright: es Chrome de Android emulado, no un
equipo real.

Dos modos mas, para que un test siga sobre la sesion que dejo otro proceso
(p. ej. el QA se loguea con su clave y luego otro test prueba politicas):
  cdp=PUERTO       abre el navegador exponiendo CDP en ese puerto, con un
                   perfil temporal (contexto por defecto, visible por CDP)
  conectar=PUERTO  no abre nada: se engancha al navegador de ese puerto y
                   toma la pestana de la app; al cerrar lo deja abierto
"""
import os
import shutil
import tempfile
import time

from playwright.sync_api import sync_playwright

from .. import _rutas  # noqa: F401  (fija PLAYWRIGHT_BROWSERS_PATH si va congelado)

# Mismas banderas que DriverFactory.getDriver().
ARGS_CHROME = ["--ignore-certificate-errors", "--disable-web-security",
               "--allow-insecure-localhost"]


class Driver:
    def __init__(self, headless=False, capturas=None, cdp=None, conectar=None, dispositivo=None,
                 lento=None):
        self.headless = headless
        # Carpeta para takeScreenshotAndSaveItLocal / takeScreenshotReport.
        # None = no se guardan capturas (solo se anota el paso en consola).
        self.capturas = capturas
        self.cdp = cdp
        self.conectar = conectar
        self.dispositivo = dispositivo
        self.lento = lento
        self.respuestas = []
        self._pw = self.browser = self.context = self.page = None
        self._perfil = None

    def init_driver(self, url):
        """Driver.initDriverThread(browser, url, headless)."""
        self._pw = sync_playwright().start()
        if self.conectar:
            self.browser = self._pw.chromium.connect_over_cdp("http://localhost:%d" % self.conectar,
                                                              slow_mo=self.lento or 0)
            self.context = self.browser.contexts[0]
            self.context.on("response", self._registrar_respuesta)
            self.page = self._pestana_de_la_app()
            return self
        args = list(ARGS_CHROME)
        if self.dispositivo:
            if self.dispositivo not in self._pw.devices:
                raise ValueError("Playwright no tiene el dispositivo %r" % self.dispositivo)
            contexto = dict(self._pw.devices[self.dispositivo])
            contexto.pop("default_browser_type", None)
        elif self.headless:
            contexto = {"viewport": {"width": 1920, "height": 1080}}
        else:
            args.append("--start-maximized")
            contexto = {"no_viewport": True}
        # channel "chromium" = headless nuevo (Chrome completo): el headless
        # basico no tiene visor de PDF y los documentos abrian una pestana ":".
        lanzar = {"headless": self.headless, "args": args, "channel": "chromium",
                  "slow_mo": self.lento or 0}
        if self.cdp:
            args.append("--remote-debugging-port=%d" % self.cdp)
            self._perfil = tempfile.mkdtemp(prefix="colsubsidio_flow_")
            self.context = self._pw.chromium.launch_persistent_context(
                self._perfil, ignore_https_errors=True, **lanzar, **contexto)
            self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        else:
            self.browser = self._pw.chromium.launch(**lanzar)
            self.context = self.browser.new_context(ignore_https_errors=True, **contexto)
            self.page = self.context.new_page()
        self.context.on("response", self._registrar_respuesta)
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if self.capturas:
            os.makedirs(self.capturas, exist_ok=True)
        return self

    @property
    def es_movil(self):
        if self.dispositivo:
            return True
        try:
            return self.page.evaluate("() => matchMedia('(pointer: coarse)').matches")
        except Exception:
            return False

    def _pestana_de_la_app(self):
        """La ultima pestana con una URL real (la de la app, no about:blank)."""
        paginas = [p for p in self.context.pages if p.url.startswith("http")]
        if not paginas:
            raise RuntimeError("El navegador del puerto %d no tiene ninguna pestana abierta "
                               "en la app" % self.conectar)
        return paginas[-1]

    def _registrar_respuesta(self, response):
        self.respuestas.append({
            "url": response.url,
            "status": response.status,
            "metodo": response.request.method,
            "ts": time.time(),
        })

    def cookies(self):
        return {c["name"]: c["value"] for c in self.context.cookies()}

    def quit_driver(self):
        """Driver.quitDriver(). Enganchado por CDP solo se suelta: el navegador
        es de otro proceso y sigue abierto."""
        try:
            if self.conectar:
                pass
            elif self._perfil:
                self.context.close()
            elif self.browser:
                self.browser.close()
        except Exception:
            pass        # el QA ya cerro la ventana (e2e --dejar-abierto)
        finally:
            if self._pw:
                self._pw.stop()
            if self._perfil:
                shutil.rmtree(self._perfil, ignore_errors=True)
            self._pw = self.browser = self.context = self.page = None
            self._perfil = None

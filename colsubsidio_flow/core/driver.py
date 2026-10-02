"""Driver, DriverFactory y DriverManager en uno.

En Java cada hilo tenia su ChromeDriver (DriverManager con ThreadLocal) y el
DriverFactory instalaba un interceptor JS de fetch/XHR mas el performance log
de Chrome para ver los status HTTP. Playwright ya entrega cada respuesta como
evento, asi que aqui se registran directamente en self.respuestas y el
interceptor JS no hace falta.
"""
import os
import time

from playwright.sync_api import sync_playwright

from .. import _rutas  # noqa: F401  (fija PLAYWRIGHT_BROWSERS_PATH si va congelado)

# Mismas banderas que DriverFactory.getDriver().
ARGS_CHROME = ["--ignore-certificate-errors", "--disable-web-security",
               "--allow-insecure-localhost"]


class Driver:
    def __init__(self, headless=False, capturas=None):
        self.headless = headless
        # Carpeta para takeScreenshotAndSaveItLocal / takeScreenshotReport.
        # None = no se guardan capturas (solo se anota el paso en consola).
        self.capturas = capturas
        self.respuestas = []
        self._pw = self.browser = self.context = self.page = None

    def init_driver(self, url):
        """Driver.initDriverThread(browser, url, headless)."""
        self._pw = sync_playwright().start()
        args = list(ARGS_CHROME)
        if self.headless:
            contexto = {"viewport": {"width": 1920, "height": 1080}}
        else:
            args.append("--start-maximized")
            contexto = {"no_viewport": True}
        self.browser = self._pw.chromium.launch(headless=self.headless, args=args)
        self.context = self.browser.new_context(ignore_https_errors=True, **contexto)
        self.context.on("response", self._registrar_respuesta)
        self.page = self.context.new_page()
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        if self.capturas:
            os.makedirs(self.capturas, exist_ok=True)
        return self

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
        """Driver.quitDriver()."""
        try:
            if self.browser:
                self.browser.close()
        finally:
            if self._pw:
                self._pw.stop()
            self._pw = self.browser = self.context = self.page = None

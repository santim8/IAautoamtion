

import sys
import time
from playwright.sync_api import sync_playwright, Page

class BizagiAutomator:
    def __init__(self):
        self.base_url = "https://test-procesosdigitales-colsubsidio.bizagi.com/#"

    def abrir_pagina(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)  # False = abre ventana visible
            page = browser.new_page()

            try:
                page.goto(self.base_url, wait_until="load")
                print(f"Página abierta correctamente: {self.base_url}")

                # Mantener navegador abierto
                input("Presiona Enter para cerrar el navegador...")

            except Exception as e:
                print(f"Error al abrir la página: {e}")

            finally:
                browser.close()


def main():
    automator = BizagiAutomator()
    automator.abrir_pagina()


if __name__ == "__main__":
    main()
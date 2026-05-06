import os
import sys
import logging
from playwright.sync_api import sync_playwright, Page, Locator

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


class BizagiAutomator:
    def __init__(self, document_number: str | None = None, document_type: str | None = None):
        self.base_url = "https://test-procesosdigitales-colsubsidio.bizagi.com/#"
        self.username = os.environ.get("BIZAGI_USER", "angie.uribeav")
        self.password = os.environ.get("BIZAGI_PASSWORD", "2025*CRD")
        self.document_number = document_number or "2001002110"
        self.document_type = document_type or "CC"

    def esta_logueado(self, page: Page) -> bool:
        try:
            page.wait_for_selector("#menuListQueries", timeout=5000)
            return True
        except Exception:
            return False

    def login(self, page: Page) -> bool:
        log.info("Esperando a que carguen los dominios...")
        try:
            page.wait_for_selector("#domain", timeout=10000)
            page.select_option("#domain", "colsubsidio")
            log.info("Dominio 'colsubsidio' seleccionado")
        except Exception as e:
            log.error("Error al seleccionar dominio: %s", e)
            return False

        page.wait_for_timeout(2000)

        try:
            page.wait_for_selector("#user", timeout=5000)
            page.wait_for_selector("#password", timeout=5000)
        except Exception as e:
            log.error("No se encontraron los campos de login: %s", e)
            return False

        try:
            page.fill("#user", self.username)
            page.fill("#password", self.password)
            page.click("#btn-login")
            log.info("Credenciales ingresadas y botón login presionado")
        except Exception as e:
            log.error("Error en el proceso de login: %s", e)
            return False

        page.wait_for_timeout(5000)
        log.info("Login completado")
        return True

    def navegar_a_consultas(self, page: Page) -> bool:
        log.info("Navegando a Consultas...")
        steps = [
            ("#menuListQueries", None),
            ("text=Otras entidades", None),
            ("text=GCR_Solicitudes - Promotor", None),
        ]
        for selector, label in steps:
            try:
                page.wait_for_selector(selector, timeout=10000)
                page.click(selector)
                page.wait_for_timeout(2000)
            except Exception as e:
                log.error("Error al hacer clic en '%s': %s", selector, e)
                return False

        log.info("Navegación a consultas completada")
        return True

    def llenar_formulario_consulta(self, page: Page) -> bool:
        log.info("Llenando formulario con documento: %s", self.document_number)

        try:
            page.wait_for_selector(
                'input[type="checkbox"].ui-bizagi-render-control-included-all',
                timeout=10000,
            )
            page.check('input[type="checkbox"].ui-bizagi-render-control-included-all')
            page.wait_for_timeout(1000)
        except Exception as e:
            log.warning("No se pudo marcar el checkbox de inclusión: %s", e)

        try:
            page.wait_for_selector(
                "#combo-ce37ef65-46c7-4519-92b7-4c4615493aa3", timeout=10000
            )
            page.click("#combo-ce37ef65-46c7-4519-92b7-4c4615493aa3")
            page.wait_for_timeout(2000)
            
            # Seleccionar tipo de documento según el tipo especificado
            if self.document_type == "CE":
                doc_type_text = "Cédula de Extranjería"
            else:
                doc_type_text = "Cédula de Ciudadanía"
            
            page.wait_for_selector(f"text={doc_type_text}", timeout=10000)
            page.click(f"text={doc_type_text}")
            page.wait_for_timeout(1000)
        except Exception as e:
            log.error("Error al seleccionar tipo de documento: %s", e)
            return False
        if not self._ingresar_numero_documento(page):
            return False

        return self._presionar_buscar(page)

    def _ingresar_numero_documento(self, page: Page) -> bool:
        selectors = [
            'input[aria-labelledby*="aeb8b6ab-751a-4aac-a9c5-b504a1a56c0d"]',
            'input.ui-bizagi-render-text[autocomplete="off"]',
            'input.ui-bizagi-render-text[type="text"]',
            'input[maxlength="50"][value=""]',
            'input[autocomplete="off"][maxlength="50"]',
        ]

        for i, selector in enumerate(selectors):
            try:
                page.wait_for_selector(selector, timeout=5000)
                fields: Locator = page.locator(selector)
                field = self._primer_campo_vacio(fields)
                field.fill("")
                field.fill(self.document_number)
                page.wait_for_timeout(1000)
                if field.input_value() == self.document_number:
                    log.info("Documento ingresado con selector %d", i + 1)
                    return True
                log.warning(
                    "Selector %d: valor guardado '%s' != esperado '%s'",
                    i + 1,
                    field.input_value(),
                    self.document_number,
                )
            except Exception as e:
                log.debug("Selector %d falló: %s", i + 1, e)

        log.error("No se pudo ingresar el número de documento")
        return False

    def _primer_campo_vacio(self, fields: Locator) -> Locator:
        if fields.count() <= 1:
            return fields.first
        for j in range(fields.count()):
            if not fields.nth(j).input_value():
                return fields.nth(j)
        return fields.first

    def _presionar_buscar(self, page: Page) -> bool:
        for selector in ('span.ui-button-text:has-text("Buscar")', "text=Buscar"):
            try:
                page.wait_for_selector(selector, timeout=10000)
                page.click(selector)
                page.wait_for_timeout(3000)
                log.info("Botón Buscar presionado")
                return True
            except Exception as e:
                log.debug("Selector de Buscar '%s' falló: %s", selector, e)
        log.error("No se pudo presionar el botón Buscar")
        return False

    def obtener_ultima_solicitud(self, page: Page) -> str | None:
        try:
            page.wait_for_selector("tbody.biz-wp-table-body", timeout=15000)

            try:
                page.wait_for_selector('li.bz-page[data-page="2"]', timeout=5000)
                log.info("Paginación detectada, navegando a página 2...")
                page.click('li.bz-page[data-page="2"] span.number:has-text("2")')
                page.wait_for_timeout(3000)
                page.wait_for_selector("tbody.biz-wp-table-body", timeout=10000)
            except Exception:
                log.info("Sin paginación adicional, usando página actual")

            rows = page.locator("tbody.biz-wp-table-body tr")
            row_count = rows.count()
            log.info("Filas encontradas: %d", row_count)

            if row_count == 0:
                log.warning("No se encontraron resultados")
                return None

            cells = rows.last.locator("td")
            if cells.count() >= 3:
                numero = cells.nth(2).text_content().strip()
                log.info("Última solicitud: %s", numero)
                return numero

            log.warning("La última fila no tiene suficientes columnas")
            return None

        except Exception as e:
            log.error("Error al obtener la última solicitud: %s", e)
            return None

    def _navegar_a_admin_casos(self, page: Page, ultima_solicitud: str | None) -> None:
        try:
            page.wait_for_selector('span.text:has-text("Admin")', timeout=10000)
            page.click('span.text:has-text("Admin")')
            page.wait_for_timeout(2000)

            page.wait_for_selector(
                'span.title:has-text("Administración de procesos")', timeout=10000
            )
            page.click('span.title:has-text("Administración de procesos")')
            page.wait_for_timeout(3000)

            page.wait_for_selector(
                'li.category.CaseAdmin[data-id="CaseAdmin"]', timeout=10000
            )
            page.click('li.category.CaseAdmin[data-id="CaseAdmin"]')
            page.wait_for_timeout(3000)

            if ultima_solicitud:
                page.wait_for_selector(
                    'input#caseInput.biz-wp-input-text[autocomplete="off"]',
                    timeout=10000,
                )
                page.fill(
                    'input#caseInput.biz-wp-input-text[autocomplete="off"]',
                    ultima_solicitud,
                )
                page.wait_for_timeout(2000)
                page.wait_for_selector(
                    'span.ui-button-text:has-text("Buscar")', timeout=10000
                )
                page.click('span.ui-button-text:has-text("Buscar")')
                page.wait_for_timeout(3000)
                log.info("Búsqueda de caso %s iniciada", ultima_solicitud)
            else:
                log.warning("No hay número de solicitud para buscar en Admin")

        except Exception as e:
            log.error("Error al navegar a Administración de procesos: %s", e)

    def abrir_pagina(self) -> None:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=False,
                args=["--start-maximized"],
            )
            context = browser.new_context(no_viewport=True)
            page = context.new_page()

            try:
                page.goto(self.base_url, wait_until="load")
                log.info("Página abierta: %s", self.base_url)

                if self.esta_logueado(page):
                    log.info("Sesión activa detectada")
                else:
                    log.info("Iniciando sesión...")
                    if not self.login(page):
                        log.error("Falló el login")
                        return

                if not self.navegar_a_consultas(page):
                    log.error("Falló la navegación a consultas")
                    return

                if not self.llenar_formulario_consulta(page):
                    log.error("Falló el llenado del formulario")
                    return

                ultima_solicitud = self.obtener_ultima_solicitud(page)

                if ultima_solicitud:
                    print(f"\n=== RESULTADO ===")
                    print(f"Última solicitud: {ultima_solicitud}")
                    print(f"=================\n")
                else:
                    log.warning("No se pudo obtener el número de la última solicitud")

                try:
                    page.click("a.ui-dialog-titlebar-close.ui-corner-all")
                    page.wait_for_timeout(2000)
                except Exception as e:
                    log.debug("No se pudo cerrar el diálogo de resultados: %s", e)

                self._navegar_a_admin_casos(page, ultima_solicitud)

                input("Presiona Enter para cerrar el navegador...")

            except Exception as e:
                log.error("Error en el proceso principal: %s", e)
            finally:
                browser.close()


def main() -> None:
    if len(sys.argv) < 2:
        print("Uso: python bizagi_automator.py [CE] <número_documento>")
        print("Ejemplo: python bizagi_automator.py 648202")
        print("Ejemplo: python bizagi_automator.py CE 648202")
        return
    
    if len(sys.argv) == 2:
        # python bizagi_automator.py 648202
        document_number = sys.argv[1]
        document_type = "CC"
    else:
        # python bizagi_automator.py CE 648202
        document_type = "CE" if sys.argv[1].upper() == "CE" else "CC"
        document_number = sys.argv[2]
    
    automator = BizagiAutomator(document_number, document_type)
    log.info("Iniciando automatización con documento: %s (tipo: %s)", automator.document_number, automator.document_type)
    automator.abrir_pagina()


if __name__ == "__main__":
    main()

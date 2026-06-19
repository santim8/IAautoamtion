import sys
import logging
from playwright.sync_api import sync_playwright

from bizagi_cancel_case import BizagiAutomator, log

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


def consultar_caso(document_type: str, document_number: str) -> str | None:
    """Abre Bizagi, navega a consultas, busca el documento y obtiene la última
    solicitud. Deja el navegador ABIERTO para que el usuario interactúe.
    No navega a Admin ni cancela nada."""
    automator = BizagiAutomator(document_number, document_type)
    automator.headless = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False, args=["--start-maximized"])
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        ultima_solicitud = None
        try:
            page.goto(automator.base_url, wait_until="load")
            log.info("Página abierta: %s", automator.base_url)

            if automator.esta_logueado(page):
                log.info("Sesión activa detectada")
            else:
                log.info("Iniciando sesión...")
                if not automator.login(page):
                    log.error("Falló el login")
                    return None

            if not automator.navegar_a_consultas(page):
                log.error("Falló la navegación a consultas")
                return None

            if not automator.llenar_formulario_consulta(page):
                log.error("Falló el llenado del formulario")
                return None

            ultima_solicitud = automator.obtener_ultima_solicitud(page)

            if ultima_solicitud:
                print(f"\n=== RESULTADO ===")
                print(f"Última solicitud: {ultima_solicitud}")
                print(f"=================\n")
                _cerrar_dialogo_y_buscar_caso(automator, page, ultima_solicitud)
            else:
                log.warning("No se pudo obtener el número de la última solicitud")

            # Deja la pantalla abierta para interacción manual.
            # Si no hay consola interactiva (p.ej. ejecutado desde el panel de Claude),
            # input() lanza EOFError: en ese caso mantenemos el navegador abierto con
            # una espera larga en lugar de cerrarlo.
            try:
                input("Navegador abierto. Presiona Enter aquí para cerrarlo...")
            except EOFError:
                log.info("Sin consola interactiva: el navegador quedará abierto hasta que lo cierres.")
                try:
                    # Espera indefinida hasta que el usuario cierre la pestaña/navegador
                    page.wait_for_event("close", timeout=0)
                except Exception:
                    # Fallback: seguir mientras el navegador siga conectado
                    while browser.is_connected():
                        page.wait_for_timeout(1000)

        except Exception as e:
            log.error("Error en el proceso principal: %s", e)
        finally:
            browser.close()

        return ultima_solicitud


def _cerrar_dialogo_y_buscar_caso(automator, page, id_caso: str) -> None:
    """Cierra el diálogo de resultados y busca el caso en el buscador superior
    (#menuQuery), luego presiona Enter. Deja la vista lista para interactuar."""
    # 1) Cerrar el diálogo de resultados
    try:
        page.wait_for_selector("a.ui-dialog-titlebar-close.ui-corner-all", timeout=10000)
        page.click("a.ui-dialog-titlebar-close.ui-corner-all")
        automator._wait(page, 2000)
        log.info("Diálogo de resultados cerrado")
    except Exception as e:
        log.warning("No se pudo cerrar el diálogo de resultados: %s", e)

    # 2) Buscar el caso en el buscador superior y dar Enter
    try:
        # Activar el buscador si está colapsado
        try:
            page.click("#ui-bizagi-wp-app-bt-search")
            automator._wait(page, 1000)
        except Exception as e:
            log.debug("No fue necesario/posible abrir el buscador: %s", e)

        page.wait_for_selector("input#menuQuery", timeout=10000)
        page.fill("input#menuQuery", id_caso)
        automator._wait(page, 1000)
        page.press("input#menuQuery", "Enter")
        automator._wait(page, 3000)
        log.info("Caso %s buscado en el buscador superior (Enter)", id_caso)
    except Exception as e:
        log.error("No se pudo buscar el caso %s en el buscador superior: %s", id_caso, e)


def _parse_args(argv: list[str]) -> tuple[str, str] | None:
    """Acepta 'CE-212584', 'CE 212584', o solo '212584' (CC por defecto)."""
    tokens: list[str] = []
    for a in argv:
        tokens.extend(t for t in a.replace("-", " ").split() if t)

    if not tokens:
        return None

    if len(tokens) == 1:
        return "CC", tokens[0]

    document_type = "CE" if tokens[0].upper() == "CE" else "CC"
    return document_type, tokens[1]


def main() -> None:
    parsed = _parse_args(sys.argv[1:])
    if parsed is None:
        print("Uso: python bizagi_consultar_caso.py [CE] <número_documento>")
        print("Ejemplo: python bizagi_consultar_caso.py CE-212584")
        print("Ejemplo: python bizagi_consultar_caso.py CE 212584")
        print("Ejemplo: python bizagi_consultar_caso.py 1075662894")
        return

    document_type, document_number = parsed
    log.info(
        "Consultando caso del documento: %s (tipo: %s)",
        document_number,
        document_type,
    )
    consultar_caso(document_type, document_number)


if __name__ == "__main__":
    main()

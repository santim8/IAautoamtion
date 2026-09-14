import json
import sys
import logging
from playwright.sync_api import sync_playwright, Page

from bizagi_cancel_case import BizagiAutomator, log

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

QUERY_ANALISTA_OPERATIVO = "GCR_Solicitudes - Analista operativo"
# El campo "Numero de solicitud" del formulario de esta consulta, ubicado por
# su data-render-xpath (el mismo en cualquier corrida, a diferencia del id
# generado que trae el input).
SELECTOR_NUMERO_SOLICITUD = (
    'div[data-render-xpath="kmInformacionGeneral.sNumeroCaso"] '
    'input.ui-bizagi-render-text'
)


def navegar_a_analista_operativo(automator: BizagiAutomator, page: Page) -> bool:
    """Mismo menu que navegar_a_consultas, pero entra por GCR_Solicitudes -
    Analista operativo en vez de Promotor."""
    steps = ["#menuListQueries", "text=Otras entidades",
             f"text={QUERY_ANALISTA_OPERATIVO}"]
    for selector in steps:
        try:
            page.wait_for_selector(selector, timeout=10000)
            page.click(selector)
            automator._wait(page, 2000)
        except Exception as e:
            log.error("No se pudo navegar a Analista operativo (clic en '%s'): %s",
                       selector, e)
            return False
    log.info("Navegacion a Analista operativo completada")
    return True


def buscar_por_numero_solicitud(automator: BizagiAutomator, page: Page, id_caso: str) -> bool:
    """Marca 'incluir todo', escribe el numero de solicitud y presiona Buscar."""
    try:
        page.wait_for_selector(
            'input[type="checkbox"].ui-bizagi-render-control-included-all',
            timeout=10000)
        page.check('input[type="checkbox"].ui-bizagi-render-control-included-all')
        automator._wait(page, 1000)
    except Exception as e:
        log.warning("No se pudo marcar el checkbox de inclusion: %s", e)

    try:
        page.wait_for_selector(SELECTOR_NUMERO_SOLICITUD, timeout=10000)
        page.fill(SELECTOR_NUMERO_SOLICITUD, id_caso)
        automator._wait(page, 500)
    except Exception as e:
        log.error("No se pudo buscar el caso %s en Analista operativo: %s", id_caso, e)
        return False

    return automator._presionar_buscar(page)


def extraer_fila_json(page: Page) -> dict | None:
    """Arma un dict con la fila de resultados, ultimo segmento del
    data-xpath (ej. 'sNumeroCaso') -> valor.

    Buscar por numero de solicitud siempre trae como mucho una fila, asi que
    se devuelve un solo objeto (o None si no hubo resultados) en vez de una
    lista. El xpath completo se recorta al ultimo segmento para que el JSON
    sea legible; si dos campos distintos terminan en el mismo nombre (pasa,
    por ejemplo Fecha Desde/Hasta que comparten data-xpath, o los varios
    'sDetalleResultadoValidaci' de las distintas validaciones) el ultimo que
    se procese pisa al anterior.

    Los th con data-xpath solo existen en el encabezado clonado que arma
    floatThead para la cabecera pegajosa (.floatThead-container); el thead de
    la tabla real solo trae el aria-label. Se toman los xpath de ahi y los
    valores de la tabla real, que es la unica con tbody.biz-wp-table-body.
    """
    return page.evaluate("""
        () => {
            const headerTable = document.querySelector('.floatThead-container table.biz-wp-table');
            const headers = headerTable
                ? Array.from(headerTable.querySelectorAll('thead th.cases-column-header')).map(th => ({
                    label: (th.querySelector('.displayNameLabel')?.textContent || '').trim(),
                    xpath: th.getAttribute('data-xpath') || ''
                  }))
                : [];
            const dataTable = document.querySelector('#table-container table.biz-wp-table:not(.floatThead-table)');
            const fila = dataTable
                ? dataTable.querySelector('tbody.biz-wp-table-body > tr')
                : null;
            if (!fila) return null;
            const cells = Array.from(fila.querySelectorAll(':scope > td'));
            const obj = {};
            cells.forEach((td, i) => {
                const h = headers[i];
                const nombre = (h && (h.xpath || h.label)) || ('col_' + i);
                const key = nombre.split('.').pop();
                obj[key] = (td.querySelector('span')?.textContent ?? td.textContent ?? '').trim();
            });
            return obj;
        }
    """)


def consultar_json(id_caso: str, headless: bool = True) -> None:
    """Abre Bizagi, hace login, entra a GCR_Solicitudes - Analista operativo y
    busca por numero de solicitud.

    En headless (por defecto) no hay ventana que mirar: se cierra el
    navegador apenas se imprime el JSON. Sin headless deja el navegador
    abierto para revisar el resultado a mano, como antes.
    """
    automator = BizagiAutomator("0", "CC")
    automator.headless = headless

    with sync_playwright() as p:
        launch_args = [] if headless else ["--start-maximized"]
        browser = p.chromium.launch(headless=headless, args=launch_args)
        context = browser.new_context(no_viewport=True)
        page = context.new_page()

        try:
            page.goto(automator.base_url, wait_until="load")
            log.info("Pagina abierta: %s", automator.base_url)

            if automator.esta_logueado(page):
                log.info("Sesion activa detectada")
            else:
                log.info("Iniciando sesion...")
                if not automator.login(page):
                    log.error("Fallo el login")
                    return

            if not navegar_a_analista_operativo(automator, page):
                return

            if not buscar_por_numero_solicitud(automator, page, id_caso):
                return

            try:
                page.wait_for_selector("tbody.biz-wp-table-body tr", timeout=15000)
            except Exception as e:
                log.warning("La tabla de resultados no cargo a tiempo: %s", e)

            registro = extraer_fila_json(page)
            if registro:
                log.info("Caso %s: registro obtenido", id_caso)
                print("\n=== JSON ===")
                print(json.dumps(registro, ensure_ascii=False, indent=2))
                print("=== FIN JSON ===\n")
            else:
                log.warning("No se encontraron registros para el caso %s", id_caso)

            if not headless:
                try:
                    input("Navegador abierto. Presiona Enter aqui para cerrarlo...")
                except EOFError:
                    log.info("Sin consola interactiva: el navegador quedara abierto hasta que lo cierres.")
                    try:
                        page.wait_for_event("close", timeout=0)
                    except Exception:
                        while browser.is_connected():
                            page.wait_for_timeout(1000)

        except Exception as e:
            log.error("Error en el proceso principal: %s", e)
        finally:
            browser.close()


def main() -> None:
    args = [a for a in sys.argv[1:] if a != "--headless"]
    headless = "--headless" in sys.argv[1:]
    if len(args) < 1:
        print("Uso: python bizagi_consultar_json.py [--headless] <id_caso>")
        print("Ejemplo: python bizagi_consultar_json.py 279770")
        print("Ejemplo: python bizagi_consultar_json.py --headless 279770")
        return
    id_caso = args[0]
    log.info("Consultando caso %s en GCR_Solicitudes - Analista operativo (headless=%s)",
              id_caso, headless)
    consultar_json(id_caso, headless=headless)


if __name__ == "__main__":
    main()

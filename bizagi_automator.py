#!/usr/bin/env python3
"""
Bizagi Double Process Automator
Automatiza el proceso de búsqueda de solicitudes en Bizagi
"""

import sys
import time
from playwright.sync_api import sync_playwright, Page

class BizagiAutomator:
    def __init__(self):
        self.base_url = "https://test-procesosdigitales-colsubsidio.bizagi.com"
        
    def run_bizagi_doble(self, documento: str) -> str:
        """
        Ejecuta el proceso doble completo en Bizagi
        
        Args:
            documento (str): Número de documento a buscar
            
        Returns:
            str: Resultado del proceso con información detallada
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)  # Cambiar a True para modo invisible
            page = browser.new_page()
            
            try:
                # PASO 1: Búsqueda por documento y última solicitud con paginación
                ultimo_numero, pagina_info = self._paso1_busqueda_documento(page, documento)
                
                # PASO 2: Búsqueda por caso
                resultado_caso = self._paso2_busqueda_caso(page, ultimo_numero)
                
                return f"Documento: {documento} | Última: {ultimo_numero} {pagina_info} | Case search: {resultado_caso}"
                
            except Exception as e:
                return f"Error en el proceso para documento {documento}: {str(e)}"
                
            finally:
                browser.close()
    
    def _paso1_busqueda_documento(self, page: Page, documento: str) -> tuple:
        """
        PASO 1: Búsqueda por documento y extracción de última solicitud
        """
        print(f"🔍 Iniciando búsqueda para documento: {documento}")
        
        # Navegación a consultas
        page.locator('a').filter(has_text='Consultas').first.click()
        time.sleep(0.5)
        
        page.get_by_text('> Otras entidades').click()
        time.sleep(0.5)
        
        page.get_by_role('listitem').filter(has_text='GCR_Solicitudes - Promotor').click()
        time.sleep(0.5)
        
        # Configurar filtros de búsqueda
        page.get_by_role('checkbox').first.click()
        time.sleep(0.3)
        
        page.get_by_role('combobox', name='Tipo de documento:').click()
        time.sleep(0.3)
        
        page.get_by_role('option', name='Cédula de Ciudadanía').click()
        time.sleep(0.3)
        
        page.get_by_role('textbox', name='Número de documento:').fill(documento)
        time.sleep(0.5)
        
        page.get_by_role('button', name='Buscar').click()
        time.sleep(2)
        
        # Lógica de paginación optimizada
        ultimo_numero, pagina_info = self._extraer_ultima_solicitud(page)
        
        # Cerrar diálogo
        page.locator('a.ui-dialog-titlebar-close').click()
        time.sleep(1)
        
        print(f"✅ Última solicitud encontrada: {ultimo_numero} {pagina_info}")
        return ultimo_numero, pagina_info
    
    def _extraer_ultima_solicitud(self, page: Page) -> tuple:
        """
        Extrae la última solicitud con manejo de paginación
        """
        # Verificar si existe página 2
        page2_exists = page.locator('li.bz-page[data-page="2"]').is_visible()
        
        if page2_exists:
            # Navegar a última página
            last_page_button = page.locator('li.bz-page').last
            last_page_button.click()
            time.sleep(1)
            
            # Extraer de última página
            last_row_last_page = page.locator('tbody tr').last
            ultimo_numero = last_row_last_page.locator('td').nth(1).text_content()
            pagina_info = "(última página)"
        else:
            # Extraer de página 1
            last_row = page.locator('tbody tr').last
            ultimo_numero = last_row.locator('td').nth(1).text_content()
            pagina_info = "(página 1)"
        
        return ultimo_numero.strip(), pagina_info
    
    def _paso2_busqueda_caso(self, page: Page, ultimo_numero: str) -> str:
        """
        PASO 2: Búsqueda por caso
        """
        print(f"🔍 Buscando caso: {ultimo_numero}")
        
        # Navegar a URL principal
        page.goto(f"{self.base_url}/#")
        time.sleep(2)
        
        # Navegación a casos
        page.locator('a').filter(has_text='Admin').first.click()
        time.sleep(0.5)
        
        page.get_by_text('Administración de procesos>').click()
        time.sleep(0.5)
        
        page.locator('#categories').get_by_role('listitem').filter(has_text='Casos').click()
        time.sleep(0.5)
        
        page.locator('#caseInput').fill(ultimo_numero)
        time.sleep(0.5)
        
        page.get_by_role('button', name='Buscar').click()
        time.sleep(1)
        
        # Verificar resultado
        try:
            if page.get_by_text('No se encontraron registros').is_visible(timeout=1000):
                page.get_by_role('button', name='Aceptar').click(timeout=1000)
                resultado = 'No encontrado'
            else:
                resultado = 'Encontrado'
        except:
            resultado = 'Desconocido'
        
        print(f"✅ Resultado de búsqueda de caso: {resultado}")
        return resultado
    
    def ejecutar_documentos_multiples(self, documentos):
        """
        Ejecuta el proceso para múltiples documentos
        
        Args:
            documentos (list): Lista de números de documento
        """
        resultados = []
        
        for doc in documentos:
            print(f"\n{'='*50}")
            resultado = self.run_bizagi_doble(doc.strip())
            resultados.append(resultado)
            print(resultado)
            time.sleep(1)  # Pausa entre documentos
        
        return resultados

def main():
    """
    Función principal para ejecución desde línea de comandos
    """
    if len(sys.argv) < 2:
        print("📖 USO:")
        print("  python bizagi_automator.py <documento>")
        print("  python bizagi_automator.py multiples \"doc1,doc2,doc3\"")
        print("")
        print("📖 EJEMPLOS:")
        print("  python bizagi_automator.py 1037618937")
        print("  python bizagi_automator.py multiples \"1037618937,80123456,12345678\"")
        sys.exit(1)
    
    automator = BizagiAutomator()
    
    if sys.argv[1].lower() == 'multiples' and len(sys.argv) >= 3:
        # Modo múltiples documentos
        documentos = [doc.strip() for doc in sys.argv[2].split(',')]
        print(f"🔄 Procesando {len(documentos)} documentos...")
        resultados = automator.ejecutar_documentos_multiples(documentos)
        
        print(f"\n{'='*50}")
        print("📊 RESUMEN DE RESULTADOS:")
        for resultado in resultados:
            print(f"  {resultado}")
    else:
        # Modo individual
        documento = sys.argv[1]
        print(f"🔄 Procesando documento: {documento}")
        resultado = automator.run_bizagi_doble(documento)
        print(f"\n📋 RESULTADO: {resultado}")

if __name__ == "__main__":
    main()
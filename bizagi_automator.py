import sys
import time
from playwright.sync_api import sync_playwright, Page

class BizagiAutomator:
    def __init__(self, document_number=None):
        self.base_url = "https://test-procesosdigitales-colsubsidio.bizagi.com/#"
        self.username = "angie.uribeav"
        self.password = "2025*CRD"
        # Usar el número de documento proporcionado o el predeterminado
        self.document_number = document_number or "2001002110"

    def esta_logueado(self, page):
        """Verifica si ya estamos logueados"""
        try:
            # Si el menú de consultas es visible, significa que ya estamos logueados
            page.wait_for_selector("#menuListQueries", timeout=5000)
            return True
        except:
            return False

    def login(self, page):
        """Realiza el proceso de login"""
        # Esperar a que cargue el formulario de dominio
        print("Esperando a que carguen los dominios...")
        page.wait_for_selector("#domain", timeout=10000)
        
        # Seleccionar el dominio "colsubsidio" (que corresponde a "Gestiona tu solicitud(colsubsidio)")
        try:
            page.select_option("#domain", "colsubsidio")
            print("Dominio 'Gestiona tu solicitud(colsubsidio)' seleccionado correctamente")
        except Exception as e:
            print(f"Error al seleccionar dominio: {e}")
            return False

        # Esperar a que aparezcan los campos de login
        page.wait_for_timeout(2000)

        # Verificar que los campos de login estén visibles
        try:
            page.wait_for_selector('#user', timeout=5000)
            page.wait_for_selector('#password', timeout=5000)
            print("Campos de login encontrados")
        except Exception as e:
            print(f"No se encontraron los campos de login: {e}")
            return False

        # Ingresar credenciales
        print("Ingresando credenciales...")
        
        # Campo de usuario
        try:
            page.fill('#user', self.username)
            print("Usuario ingresado correctamente")
        except Exception as e:
            print(f"Error al ingresar usuario: {e}")
            return False

        # Campo de contraseña
        try:
            page.fill('#password', self.password)
            print("Contraseña ingresada correctamente")
        except Exception as e:
            print(f"Error al ingresar contraseña: {e}")
            return False

        # Hacer clic en el botón de login
        try:
            page.click('#btn-login')
            print("Botón de login presionado")
        except Exception as e:
            print(f"Error al presionar botón de login: {e}")
            return False

        # Esperar a que cargue la página principal
        page.wait_for_timeout(5000)
        print("Proceso de login completado")
        return True

    def navegar_a_consultas(self, page):
        """Navega a la sección de consultas"""
        print("Navegando a Consultas...")
        try:
            page.wait_for_selector("#menuListQueries", timeout=10000)
            page.click("#menuListQueries")
            print("Menú Consultas seleccionado")
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Error al hacer clic en Consultas: {e}")
            return False

        # Buscar y hacer clic en "Otras entidades"
        try:
            page.wait_for_selector("text=Otras entidades", timeout=10000)
            page.click("text=Otras entidades")
            print("Otras entidades seleccionado")
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Error al hacer clic en Otras entidades: {e}")
            return False

        # Buscar y hacer clic en "GCR_Solicitudes - Promotor"
        try:
            page.wait_for_selector("text=GCR_Solicitudes - Promotor", timeout=10000)
            page.click("text=GCR_Solicitudes - Promotor")
            print("GCR_Solicitudes - Promotor seleccionado")
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"Error al hacer clic en GCR_Solicitudes - Promotor: {e}")
            return False

        print("Navegación completada")
        return True

    def llenar_formulario_consulta(self, page):
        """Llena el formulario de consulta"""
        print(f"Llenando formulario de consulta con documento: {self.document_number}")
        
        # Marcar checkbox "ui-bizagi-render-control-included-all"
        try:
            page.wait_for_selector('input[type="checkbox"].ui-bizagi-render-control-included-all', timeout=10000)
            page.check('input[type="checkbox"].ui-bizagi-render-control-included-all')
            print("Checkbox de inclusión marcado")
            page.wait_for_timeout(1000)
        except Exception as e:
            print(f"Error al marcar checkbox: {e}")

        # Hacer clic en el combobox de tipo de documento
        try:
            page.wait_for_selector('#combo-ce37ef65-46c7-4519-92b7-4c4615493aa3', timeout=10000)
            page.click('#combo-ce37ef65-46c7-4519-92b7-4c4615493aa3')
            print("Combobox de tipo de documento abierto")
            page.wait_for_timeout(2000)
        except Exception as e:
            print(f"Error al abrir combobox de tipo de documento: {e}")
            return False

        # Seleccionar "Cédula de Ciudadanía"
        try:
            page.wait_for_selector("text=Cédula de Ciudadanía", timeout=10000)
            page.click("text=Cédula de Ciudadanía")
            print("Cédula de Ciudadanía seleccionada")
            page.wait_for_timeout(1000)
        except Exception as e:
            print(f"Error al seleccionar Cédula de Ciudadanía: {e}")
            return False

        # Rellenar campo de número de documento - intentar múltiples selectores
        doc_field = None
        selectors_to_try = [
            'input[aria-labelledby*="aeb8b6ab-751a-4aac-a9c5-b504a1a56c0d"]',
            'input.ui-bizagi-render-text[autocomplete="off"]',
            'input.ui-bizagi-render-text[type="text"]',
            'input[maxlength="50"][value=""]',
            'input[autocomplete="off"][maxlength="50"]'
        ]
        
        for i, selector in enumerate(selectors_to_try):
            try:
                print(f"Intentando con selector {i+1}: {selector}")
                page.wait_for_selector(selector, timeout=5000)
                
                # Si hay múltiples campos, intentar con el último o el primero sin valor
                fields = page.locator(selector)
                if fields.count() > 1:
                    # Intentar encontrar el campo vacío
                    for j in range(fields.count()):
                        field_value = fields.nth(j).input_value()
                        if not field_value or field_value == "":
                            doc_field = fields.nth(j)
                            break
                    if not doc_field:
                        doc_field = fields.first
                else:
                    doc_field = fields.first
                
                # Limpiar campo y rellenar
                doc_field.fill("")  # Limpiar primero
                doc_field.fill(self.document_number)
                print(f"Número de documento {self.document_number} ingresado con selector {i+1}")
                page.wait_for_timeout(1000)
                
                # Verificar que se ingresó correctamente
                if doc_field.input_value() == self.document_number:
                    print("Verificación exitosa del número de documento")
                    break
                else:
                    print(f"Valor ingresado: '{doc_field.input_value()}' (esperado: '{self.document_number}')")
                    
            except Exception as e:
                print(f"Error con selector {i+1}: {e}")
                continue
        else:
            print("No se pudo rellenar el número de documento con ningún selector")
            return False

        # Hacer clic en el botón Buscar
        try:
            page.wait_for_selector('span.ui-button-text:has-text("Buscar")', timeout=10000)
            page.click('span.ui-button-text:has-text("Buscar")')
            print("Botón Buscar presionado")
            page.wait_for_timeout(3000)  # Esperar a que se carguen los resultados
        except Exception as e:
            print(f"Error al presionar botón Buscar: {e}")
            # Intentar con selector alternativo
            try:
                page.click('text=Buscar')
                print("Botón Buscar presionado con selector alternativo")
                page.wait_for_timeout(3000)
            except Exception as e2:
                print(f"Error al presionar botón Buscar con selector alternativo: {e2}")
                return False

        print("Formulario de consulta completado y búsqueda iniciada")
        return True

    def abrir_pagina(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)  # False = abre ventana visible
            context = browser.new_context(viewport=None)  # viewport=None = pantalla completa
            page = context.new_page()

            try:
                page.goto(self.base_url, wait_until="load")
                print(f"Página abierta correctamente: {self.base_url}")

                # Verificar si ya estamos logueados
                if self.esta_logueado(page):
                    print("Ya estás logueado. Procediendo con la navegación...")
                else:
                    print("No estás logueado. Iniciando sesión...")
                    if not self.login(page):
                        print("Falló el proceso de login")
                        return

                # Navegar a la sección deseada
                if not self.navegar_a_consultas(page):
                    print("Falló la navegación a consultas")
                    return

                # Llenar el formulario de consulta
                if not self.llenar_formulario_consulta(page):
                    print("Falló el llenado del formulario")
                    return

                # Mantener navegador abierto
                input("Presiona Enter para cerrar el navegador...")

            except Exception as e:
                print(f"Error en el proceso: {e}")

            finally:
                browser.close()


def main():
    # Obtener el número de documento de los argumentos de línea de comandos
    document_number = sys.argv[1] if len(sys.argv) > 1 else None
    
    automator = BizagiAutomator(document_number)
    print(f"Iniciando esta automatización con documento: {automator.document_number}")
    automator.abrir_pagina()


if __name__ == "__main__":
    main()
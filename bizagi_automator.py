import sys
import time
from playwright.sync_api import sync_playwright, Page

class BizagiAutomator:
    def __init__(self):
        self.base_url = "https://test-procesosdigitales-colsubsidio.bizagi.com/#"
        self.username = "angie.uribeav"
        self.password = "2025*CRD"

    def abrir_pagina(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)  # False = abre ventana visible
            page = browser.new_page()

            try:
                page.goto(self.base_url, wait_until="load")
                print(f"Página abierta correctamente: {self.base_url}")

                # Esperar a que cargue el formulario de dominio
                print("Esperando a que carguen los dominios...")
                page.wait_for_selector("#domain", timeout=10000)
                
                # Seleccionar el dominio "colsubsidio" (que corresponde a "Gestiona tu solicitud(colsubsidio)")
                try:
                    page.select_option("#domain", "colsubsidio")
                    print("Dominio 'Gestiona tu solicitud(colsubsidio)' seleccionado correctamente")
                except Exception as e:
                    print(f"Error al seleccionar dominio: {e}")
                    return

                # Esperar a que aparezcan los campos de login
                page.wait_for_timeout(2000)

                # Verificar que los campos de login estén visibles
                try:
                    page.wait_for_selector('#user', timeout=5000)
                    page.wait_for_selector('#password', timeout=5000)
                    print("Campos de login encontrados")
                except Exception as e:
                    print(f"No se encontraron los campos de login: {e}")
                    return

                # Ingresar credenciales
                print("Ingresando credenciales...")
                
                # Campo de usuario
                try:
                    page.fill('#user', self.username)
                    print("Usuario ingresado correctamente")
                except Exception as e:
                    print(f"Error al ingresar usuario: {e}")

                # Campo de contraseña
                try:
                    page.fill('#password', self.password)
                    print("Contraseña ingresada correctamente")
                except Exception as e:
                    print(f"Error al ingresar contraseña: {e}")

                # Hacer clic en el botón de login
                try:
                    page.click('#btn-login')
                    print("Botón de login presionado")
                except Exception as e:
                    print(f"Error al presionar botón de login: {e}")

                # Esperar un momento para ver el resultado
                page.wait_for_timeout(5000)
                print("Proceso de login completado")

                # Mantener navegador abierto
                input("Presiona Enter para cerrar el navegador...")

            except Exception as e:
                print(f"Error en el proceso: {e}")

            finally:
                browser.close()


def main():
    automator = BizagiAutomator()
    automator.abrir_pagina()


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Observador pasivo de flujos: tu navegas a mano, el script mira y guarda evidencia.

Se engancha a un Chrome ya abierto (CDP, puerto 9222) igual que open_chrome.py.
NO maneja el navegador: solo escucha.

La unidad de evidencia es el PASO (una pantalla). Se abre un paso nuevo cuando
cambia la URL -- por navegacion real o por ruta de SPA (history.pushState) -- y
todos los requests que ocurren hasta el siguiente cambio quedan agrupados ahi.

Salida:
  evidences/<flujo>_<fecha>/
      00_<slug>/screenshot.png
      00_<slug>/requests.jsonl
      ...
      captura.har        (HAR 1.2 derivado de lo capturado)
      resumen.json
      reporte.html       (timeline: pantalla | requests, lado a lado)

Uso:
  1. python observador_flujo.py --lanzar-chrome
  2. python observador_flujo.py --flujo "validaciones-card"
  3. Navegas normal. Ctrl+C para cerrar y generar el reporte.

Por defecto solo captura los hosts del backend (ver HOSTS_DEFAULT) y redacta
credenciales. --todos-los-hosts y --sin-redactar desactivan cada cosa.

--request-check consulta ademas /request/check (ver sonda_check.py): apenas
responde el login de Gigya (con el documento que trae), al detectar el documento
en validaciones y al llegar a informacion personal, cuando el caso ya esta
creado: ese endpoint lo llama el servidor del front, no el navegador, asi que
sin la sonda nunca aparece en la evidencia.

Los requests que el front nunca pudo leer tambien quedan, marcados: los que
Chrome bloquea por CORS (con el status real que respondio el servidor), los
cortados por la red y los que seguian en vuelo al parar. Al parar se espera
hasta --espera-en-vuelo segundos a que estos ultimos respondan.

Este archivo es solo el punto de entrada (lo lanza el panel y lo empaqueta
PyInstaller). El codigo vive en el paquete observador/; su __init__.py tiene
el mapa de modulos y donde se extiende cada cosa.
"""
import sys

from observador.cli import main
# lo que importan otros scripts (observador_analitica.py)
from observador.navegador import lanzar_chrome
from observador.reporte_html import CSS_REPORTE
from observador.util import ahora_iso, ruta_de

__all__ = ["main", "lanzar_chrome", "CSS_REPORTE", "ahora_iso", "ruta_de"]

if __name__ == "__main__":
    sys.exit(main())

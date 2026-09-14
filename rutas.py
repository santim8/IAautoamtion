#!/usr/bin/env python3
"""Donde esta cada cosa, corriendo desde el repo o desde el .exe.

Un script suelto tiene una sola carpeta: la suya. Congelado con PyInstaller son
dos, y confundirlas es el error que rompe todo:

  RECURSOS  lo que viaja DENTRO del .exe (el codigo, las semillas). Congelado
            es una carpeta temporal que PyInstaller descomprime al arrancar y
            BORRA al cerrar. Escribir ahi es escribir en el vacio.
  BASE      lo que se escribe y tiene que sobrevivir: evidencias, esquemas,
            ajustes. Congelado es la carpeta donde esta el .exe.

Desde el repo las dos son la misma y nada de esto se nota, que es justo la
idea: el codigo no tiene que preguntar en cual de los dos mundos esta.
"""
import glob
import os
import sys

CONGELADO = getattr(sys, "frozen", False)
RECURSOS = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
BASE = os.path.dirname(sys.executable) if CONGELADO else RECURSOS

# Datos del usuario. Ya vivian fuera del repo para sobrevivir a un git clean;
# congelado sirven ademas para que dos QA en la misma maquina no se pisen.
DIR_DATOS = os.path.join(os.path.expanduser("~"), ".panel_qa")

# Navegador de Playwright: SOLO lo usan los scripts de Bizagi, que abren su
# propio Chromium. El observador se engancha por CDP al Chrome de verdad y no
# necesita nada de esto.
#
# Donde lo deja `playwright install` cuando nadie le dice otra cosa.
POR_DEFECTO = os.path.join(os.environ.get("LOCALAPPDATA")
                           or os.path.join(os.path.expanduser("~"), "AppData",
                                           "Local"),
                           "ms-playwright")
NAVEGADORES = os.path.join(DIR_DATOS, "browsers")


def _hay_chromium(raiz):
    return bool(glob.glob(os.path.join(raiz, "chromium-*")))


# Congelado no hay consola donde correr `playwright install`, asi que el panel
# lo baja solo a una carpeta nuestra. Pero primero se mira la ubicacion por
# defecto: quien ya corria esto desde el repo tiene el navegador ahi, y hacerle
# bajar otros 150 MB identicos seria una tonteria.
if CONGELADO and not _hay_chromium(POR_DEFECTO):
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", NAVEGADORES)


def chromium_instalado():
    """Hay un chromium bajado donde Playwright lo va a buscar?"""
    return _hay_chromium(os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
                         or POR_DEFECTO)


def recurso(*partes):
    """Un archivo que viaja con el programa; de solo lectura."""
    return os.path.join(RECURSOS, *partes)


def dato(*partes):
    """Un archivo que el programa escribe y tiene que seguir ahi manana."""
    return os.path.join(BASE, *partes)

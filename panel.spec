# -*- mode: python ; coding: utf-8 -*-
"""Receta de PyInstaller para el Panel QA.

Se construye con:  construir_exe.bat   (o: pyinstaller panel.spec)

Dos decisiones que valen la pena explicar:

1. Los datos se listan UNO POR UNO, nunca la carpeta entera. Al lado de este
   archivo vive token.txt con el PAT de Azure DevOps: esta en .gitignore, pero
   .gitignore no sabe nada de PyInstaller. Un ("." , ".") aqui lo meteria
   dentro del .exe que se reparte, y de ahi se saca con un unzip.

2. El navegador de Playwright NO se empaqueta. Son ~150 MB que solo usan las
   dos pestanas de Bizagi; el panel lo baja solo la primera vez que hacen
   falta (ver asegurar_chromium). El .exe queda en decenas de MB en vez de
   pasar de 200.
"""
from PyInstaller.utils.hooks import collect_all

# Los scripts que el panel corre relanzandose a si mismo con --child. No se
# importan en el codigo con un `import` normal, asi que PyInstaller no los ve
# solo: hay que nombrarlos.
HIJOS = [
    "observador_flujo",
    "observador_analitica",
    "bizagi_cancel_case",
    "bizagi_consultar_caso",
]

datas = [
    # semilla del catalogo de usuarios; el panel prefiere el que este junto al
    # .exe, este es el de respaldo para quien lo abre recien bajado
    ("usuarios_compartidos.json", "."),
]
binaries = []
hiddenimports = HIJOS + ["esquemas", "rutas"]

# playwright trae su driver de node como dato del paquete; sin collect_all el
# .exe arranca y falla al abrir el navegador
for paquete in ("playwright", "jsonschema", "openpyxl"):
    d, b, h = collect_all(paquete)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["panel_observador.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "numpy", "pandas"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PanelQA",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    # sin consola: es una ventana, igual que el pythonw de panel.bat. Los
    # scripts hijos igual entregan su stdout, porque el panel se los lanza por
    # tuberia y no por consola.
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

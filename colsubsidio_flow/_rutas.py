"""Deja importable el rutas.py de la raiz del repo desde dentro del paquete."""
import os
import sys

_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _RAIZ not in sys.path:
    sys.path.insert(0, _RAIZ)

import rutas  # noqa: E402,F401

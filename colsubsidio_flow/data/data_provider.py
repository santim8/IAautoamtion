"""DataProviderUtil en Python.

Las cedulas viven en cedulas.json (se versiona), agrupadas por data provider:
fill_data_api, login_credito, consumo_225423... Cada grupo es una lista de
{"tipo", "numero", "nota"}.

Las claves NO van ahi (en Java estaban en el codigo). Se buscan, en orden:
  1. ~/.panel_qa/usuarios_prueba.json -- el archivo de la pestana Usuarios del
     panel, fuera del repo;
  2. la variable de entorno COLS_CLAVE;
  3. si no hay, el runner la pide por consola.
"""
import json
import os
from dataclasses import dataclass, field

ARCHIVO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cedulas.json")
USUARIOS_PANEL = os.path.join(os.path.expanduser("~"), ".panel_qa", "usuarios_prueba.json")
TIPOS = ("CC", "CE")


@dataclass
class Usuario:
    tipo: str
    numero: str
    nota: str = ""
    clave: str = field(default=None, repr=False)

    @property
    def documento(self):
        return "%s:%s" % (self.tipo, self.numero)


def cargar():
    with open(ARCHIVO, encoding="utf-8") as f:
        return json.load(f)


def guardar(datos):
    with open(ARCHIVO, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.write("\n")


def grupos():
    return [k for k in cargar() if not k.startswith("_")]


def grupo(nombre):
    datos = cargar()
    if nombre not in datos:
        raise KeyError("No existe el data provider '%s'. Hay: %s" % (nombre, ", ".join(grupos())))
    return [Usuario(f["tipo"], f["numero"], f.get("nota", "")) for f in datos[nombre]]


def agregar(nombre, tipo, numero, nota=""):
    tipo = tipo.upper()
    if tipo not in TIPOS or not numero.isdigit():
        raise ValueError("Documento invalido: %s:%s (tipos: %s)" % (tipo, numero, ", ".join(TIPOS)))
    datos = cargar()
    filas = datos.setdefault(nombre, [])
    for f in filas:
        if f["tipo"] == tipo and f["numero"] == numero:
            if nota:
                f["nota"] = nota
            break
    else:
        filas.append({"tipo": tipo, "numero": numero, "nota": nota})
    guardar(datos)


def quitar(nombre, tipo, numero):
    datos = cargar()
    antes = len(datos.get(nombre, []))
    datos[nombre] = [f for f in datos.get(nombre, [])
                     if not (f["tipo"] == tipo.upper() and f["numero"] == numero)]
    guardar(datos)
    return antes - len(datos[nombre])


def clave_de(tipo, numero):
    """Clave del usuario sin pedirla: archivo del panel o COLS_CLAVE."""
    if os.path.exists(USUARIOS_PANEL):
        try:
            with open(USUARIOS_PANEL, encoding="utf-8") as f:
                for u in json.load(f):
                    if (str(u.get("usuario")) == numero
                            and str(u.get("tipo", "CC")).upper() == tipo.upper()
                            and u.get("clave")):
                        return u["clave"]
        except (OSError, ValueError):
            pass
    return os.environ.get("COLS_CLAVE") or None


def con_claves(usuarios):
    for u in usuarios:
        u.clave = clave_de(u.tipo, u.numero)
    return usuarios


# ---- Los dos data providers de Java, con el mismo nombre ----

def fill_data_api():
    """[(tipo, numero)] sin repetidos por numero, como en Java."""
    vistos, filas = set(), []
    for u in grupo("fill_data_api"):
        if u.numero not in vistos:
            vistos.add(u.numero)
            filas.append((u.tipo, u.numero))
    return filas


def login_credito_data():
    """[(tipo, numero, clave)] -- clave None si no esta en el panel ni en COLS_CLAVE."""
    return [(u.tipo, u.numero, u.clave) for u in con_claves(grupo("login_credito"))]

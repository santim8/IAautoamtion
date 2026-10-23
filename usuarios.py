#!/usr/bin/env python3
"""Banco de usuarios de prueba: una ficha por cedula, con su estado real.

La pestana Usuarios del panel guarda cada usuario en
~/.panel_qa/usuarios_prueba.json. Hasta ahora lo unico que decia para que
servia era la descripcion, en texto libre ("APROVADO", "facutativo"), que no se
puede filtrar y se queda vieja: una cedula cambia de estado cada vez que alguien
la usa (abre un caso en Bizagi, ASCARD le mueve el bolsillo). Cada registro
conserva sus campos de siempre (tipo, usuario, clave, descripcion, status,
falla) y suma tres:

  etiquetas  lo que sabemos de la cedula y no cambia solo: mujer,
             novedades-autorizada, amparada, la HU donde sirvio...
  uso        quien la tiene reservada, para que HU y desde cuando
  estado     lo que trae Refrescar preguntandole a los servicios. Lo escribe
             el refresco; no se edita a mano

Refrescar pregunta por cada cedula, contra platform-test (el back de dev):
  affiliation-validations v2  SAP, la misma que llama el front: tipo de
                           trabajador, grupo, categoria, genero y el motivo
                           si rechaza
  card-validations v2      ASCARD: novedad (tipoSolicitud), amparada, bolsillos
  elegibilidad de productos (SIIF), campanas (preaprobado)
  /request/check           caso abierto en Bizagi y paso pendiente (la retoma)
  Gigya isAvailableLoginID solo con --preguntar-ciam (una cuenta que existe no
                           deja de existir): si tiene cuenta CIAM en dev y si
                           la creo Bruno (su correo +cc<numero> esta tomado):
                           a esa le pone la clave de registro-dev si no tenia
  Gigya accounts.login     solo con --login y si hay clave: dice si la cuenta
                           ya esta verificada (206002 = falta abrir el correo)
Listas restrictivas ya no esta vigente: no se consulta.

Uso:
  python usuarios.py revisar CC:123 [CE:456 ...] [--preguntar-ciam]
                           la ficha completa: la suma al banco si falta, la
                           refresca y dice si pasa, que novedad es, el caso y
                           la cuenta CIAM (la guardada, o la de Gigya si se pide)
  python usuarios.py crear-ciam CC:123 [...]       cuenta en el login de dev
                           con Bruno (Crear Usuarios Lote[Gigya])
  python usuarios.py buscar [filtros] [--json] [--reservar HU [--cuantos N]]
  python usuarios.py refrescar [CC:123 ...] [filtros] [--login] [--preguntar-ciam] [--hilos 5]
  python usuarios.py reservar CC:123 [CC:456 ...] --hu 225427
  python usuarios.py liberar CC:123 [...]
  python usuarios.py etiquetar CC:123 [...] [--agregar X] [--quitar Y]
  python usuarios.py importar ARCHIVO.json
  python usuarios.py exportar cedulas GRUPO [filtros] [--reemplazar]
  python usuarios.py exportar bruno [filtros]

Filtros (todos opcionales, se combinan con Y):
  --afiliacion ZAPE|pensionado|ZGRE...   --genero F|M
  --novedad originacion|aumento|reactivacion|rechazo
  --sin-caso | --con-caso   --ciam existe|no-existe|login-ok|sin-verificar
  --libres   --etiqueta X   --texto X   --status X
"""
import argparse
import copy
import getpass
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

from rutas import BASE, DIR_DATOS
from sonda_check import SIN_CASO, URL as URL_CHECK, resumir

ARCHIVO = os.path.join(DIR_DATOS, "usuarios_prueba.json")
BACKUPS = os.path.join(DIR_DATOS, "backups")
MAX_BACKUPS = 30

CEDULAS_JSON = os.path.join(BASE, "colsubsidio_flow", "data", "cedulas.json")
BRUNO_DIR = os.path.join(BASE, "bruno", "validate-request")
CSV_BRUNO = os.path.join(BRUNO_DIR, "data", "usuarios_registro.csv")
BRUNO_LOTE = "Crear Usuarios Lote[Gigya].bru"

ESTADOS = ["Disponible", "En uso", "Bloqueado", "Quemado", "Con falla"]
# Lo que saca a un usuario de "libres". Sin status tambien cuenta como libre:
# la mitad de la libreta nunca lo tuvo.
NO_LIBRES = {"en uso", "bloqueado", "quemado", "con falla"}

TIPOS_SERVICIO = {"CC": "CO1C", "CE": "CO1E"}

# afiliado.afiliacion.tipoTrabajador de SAP. Bizagi lo mapea a la letra que
# viaja en request-data: ZTRA->D, ZAIN->I, ZAPE->P, ZAFA->F.
TRABAJADOR = {"ZTRA": "Dependiente", "ZAIN": "Independiente",
              "ZAPE": "Pensionado", "ZAFA": "Facultativo"}
GRUPOS = {"ZGRP": "Dependiente", "ZGRI": "Independiente",
          "ZGRE": "Pensionado", "ZGRA": "Facultativo"}
# afiliado.genero: el swagger no trae catalogo; 1/2 sale de comparar capturas
GENEROS = {"1": "Mujer", "2": "Hombre"}
NOVEDADES = {1: "Originacion", 2: "Aumento", 3: "Reactivacion"}

# El apiKey del screen-set de dev.colsubsidio.com (publico, va en el JS de la
# pagina). No es el ciam_gigya_api_key de token.txt: ese es el del token CIAM
# de Apigee y no sirve para preguntar por cuentas del login de dev.
GIGYA_API_KEY_DEV = "4_7e7hXQFydtXC85iCAHxVhw"
GIGYA = "https://accounts.us1.gigya.com/"
LOGIN_CODIGOS = {
    0: "OK",
    206001: "REGISTRO_INCOMPLETO",
    206002: "PENDIENTE_VERIFICACION",
    401030: "CLAVE_VIEJA",
    403042: "CLAVE_ERRADA",
    403120: "BLOQUEADA",
}
LOGIN_TEXTO = {
    "OK": "Login OK",
    "PENDIENTE_VERIFICACION": "Sin verificar",
    "REGISTRO_INCOMPLETO": "Registro incompleto",
    "CLAVE_VIEJA": "Clave vieja",
    "CLAVE_ERRADA": "Clave errada",
    "BLOQUEADA": "Bloqueada",
}

# Lo que card-validations v2 trae en datosSinProcesar: un "JSON" con comillas
# simples y strings anidados que no hay parser que lo lea. Solo interesa cada
# bolsillo con su estado: 'bolsillo':{'codigo':'01','estado':{'codigo':'1',...
RE_BOLSILLO = re.compile(r"'bolsillo':\{'codigo':'([^']*)','estado':\{'codigo':'([^']*)',"
                         r"'descripcion':'([^']*)'")

# Las validaciones de elegibilidad, en el orden del flujo. "Pasa las
# validaciones" y "pasa todas" son las tres. Listas restrictivas ya no esta
# vigente: se quito.
VALIDACIONES = ("sap", "siif", "ascard")
VALIDACIONES_BASE = VALIDACIONES

# Secciones de "estado" que escribe un refresco. Si un servicio falla esa vez,
# su seccion conserva lo que traia y el error queda en estado.errores.
SECCIONES = ("nombre", "sap", "tms", "ascard", "siif",
             "preaprobado", "caso", "ciam")


class Fallo(Exception):
    """Un servicio respondio, pero no con lo que se necesita."""


# --- persistencia ------------------------------------------------------------
def leer(ruta=None, estricto=False):
    """La libreta como lista. estricto: un archivo roto lanza ValueError en vez
    de devolver [] (la CLI no debe pisar con una lista vacia lo que no leyo)."""
    ruta = ruta or ARCHIVO
    try:
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
    except OSError:
        return []
    except ValueError:
        if estricto:
            raise
        return []
    return datos if isinstance(datos, list) else []


def guardar(datos, ruta=None, respaldo=True):
    """Guarda copia de lo anterior y escribe de forma atomica. Lanza OSError.

    La copia es contra el error humano (borrar la fila que no era); el
    os.replace es contra el corte a media escritura, que dejaria el JSON
    partido y sin poder leerse. respaldo=False en los guardados de avance de
    un refresco: con una copia por cedula, 30 copias se van en un solo lote y
    se pierden las de antes.
    """
    ruta = ruta or ARCHIVO
    os.makedirs(BACKUPS, exist_ok=True)
    if respaldo and os.path.exists(ruta):
        # con precision de segundo, varios guardados seguidos se pisaban
        # entre si y quedaba una sola copia
        marca = "%s_%03d" % (time.strftime("%Y%m%d_%H%M%S"),
                             int(time.time() * 1000) % 1000)
        shutil.copy2(ruta, os.path.join(BACKUPS, "usuarios_%s.json" % marca))
        _podar()
    tmp = ruta + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
    os.replace(tmp, ruta)


def _podar():
    """Deja solo las ultimas MAX_BACKUPS copias."""
    try:
        copias = sorted(os.path.join(BACKUPS, f) for f in os.listdir(BACKUPS)
                        if f.startswith("usuarios_") and f.endswith(".json"))
        for viejo in copias[:-MAX_BACKUPS]:
            os.remove(viejo)
    except OSError:
        pass


# --- claves y documentos -------------------------------------------------------
def clave(u):
    return (str(u.get("tipo") or "CC").upper(), str(u.get("usuario") or "").strip())


RE_DOC_PEGADO = re.compile(r"^\s*(CC|CE|CO1C|CO1E)\s*[-\s]?\s*(\d+)\s*$", re.I)


def parse_doc(texto):
    """'CC:123', 'CE:456', 'CO1C:123', 'CC123', 'CC 123' o solo '123' (CC)
    -> ('CC', '123')."""
    pegado = RE_DOC_PEGADO.match(str(texto))
    if pegado:
        texto = "%s:%s" % pegado.groups()
    tipo, sep, numero = str(texto).partition(":")
    if not sep:
        tipo, numero = "CC", tipo
    tipo = {"CO1C": "CC", "CO1E": "CE"}.get(tipo.strip().upper(), tipo.strip().upper())
    numero = numero.strip()
    if tipo not in TIPOS_SERVICIO or not numero.isdigit():
        raise ValueError("documento esperado CC:NUMERO o CE:NUMERO, recibido %r" % texto)
    return tipo, numero


def por_clave(datos):
    """{(tipo, numero): [registros]}: la libreta admite repetidos."""
    idx = {}
    for u in datos:
        idx.setdefault(clave(u), []).append(u)
    return idx


# un documento dentro de un texto pegado: "CC 123", "CE:456", "CO1C-789",
# "52.335.676" (Excel con miles) o el numero solo
RE_DOC_EN_TEXTO = re.compile(
    r"(?:\b(CC|CE|CO1C|CO1E)\s*[:\-]?\s*)?(\d{1,3}(?:\.\d{3})+(?![\d.])|\d+)", re.I)


def documentos_en_texto(texto):
    """Los documentos de lo que se pega en el panel: '123, CC 456 CE:789' o
    una columna de Excel (con la del tipo al lado, o sin ella). Sin tipo
    queda None: se busca en CC y en CE, y si hay que agregarlo es CC.
    Devuelve ([(tipo, numero)] en orden y sin repetir, [palabras que no son
    un documento])."""
    texto = str(texto or "")
    docs = []
    for tipo, numero in RE_DOC_EN_TEXTO.findall(texto):
        tipo = {"CO1C": "CC", "CO1E": "CE"}.get(tipo.upper(), tipo.upper()) or None
        doc = (tipo, numero.replace(".", ""))
        if doc not in docs:
            docs.append(doc)
    return docs, re.findall(r"\w+", RE_DOC_EN_TEXTO.sub(" ", texto))


def buscar_documentos(datos, docs, parcial=False):
    """Los registros de esos documentos, en el orden en que se pidieron. Un
    documento sin tipo encuentra CC y CE. parcial: el numero puede ser un
    pedazo (mientras se escribe); primero el exacto y los que empiezan por el.
    Devuelve ([(indice, registro)], [(tipo, numero) que no estan]): que falte
    se decide siempre por el documento completo."""
    filas, faltan, vistos = [], [], set()
    for tipo, numero in docs:
        hallados = [(i, u) for i, u in enumerate(datos)
                    if tipo in (None, clave(u)[0])
                    and (numero in clave(u)[1] if parcial else clave(u)[1] == numero)]
        if not any(clave(u)[1] == numero for _i, u in hallados):
            faltan.append((tipo or "CC", numero))
        # sort es estable: entre iguales queda el orden de la libreta
        hallados.sort(key=lambda iu: (clave(iu[1])[1] != numero,
                                      not clave(iu[1])[1].startswith(numero)))
        for i, u in hallados:
            if i not in vistos:
                vistos.add(i)
                filas.append((i, u))
    return filas, faltan


def _ahora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm(texto):
    """Minusculas y sin tildes, para comparar lo que escribe una persona."""
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in texto if not unicodedata.combining(c)).strip().lower()


def _sin_vacios(d):
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


# --- lectura de la ficha ---------------------------------------------------------
def _estado(u):
    return u.get("estado") or {}


def afiliacion(u):
    sap = _estado(u).get("sap") or {}
    cod = sap.get("tipoTrabajador")
    if cod:
        return "%s (%s)" % (TRABAJADOR.get(cod, "Otro"), cod)
    grupo = sap.get("grupo")
    return "%s (%s)" % (GRUPOS.get(grupo, "Otro"), grupo) if grupo else ""


def categoria(u):
    return (_estado(u).get("sap") or {}).get("categoria") or ""


def genero(u):
    return GENEROS.get((_estado(u).get("sap") or {}).get("genero"), "")


def novedad(u):
    a = _estado(u).get("ascard") or {}
    if a.get("estado") == "OK":
        return NOVEDADES.get(a.get("tipoSolicitud"), "tipoSolicitud %s" % a.get("tipoSolicitud"))
    if a.get("estado"):
        motivo = a.get("regla") or a.get("codigoError") or a.get("estado")
        return "Rechazo: %s" % motivo
    return ""


def caso(u):
    c = _estado(u).get("caso") or {}
    if not c:
        return ""
    if c.get("estado") == SIN_CASO:
        return "Sin caso"
    partes = [c.get("estado") or "?"]
    if c.get("pasoPendiente"):
        partes.append(c["pasoPendiente"])
    if c.get("idCaso"):
        partes.append("#%s" % c["idCaso"])
    return " ".join(partes)


def ciam(u):
    c = _estado(u).get("ciam") or {}
    if c.get("login"):
        return LOGIN_TEXTO.get(c["login"], c["login"])
    if c.get("existe") is True:
        return "Existe"
    if c.get("existe") is False:
        return "No existe"
    return ""


def refrescado(u):
    e = _estado(u)
    ts = e.get("actualizado")
    if not ts:
        return ""
    try:
        texto = datetime.fromisoformat(ts).astimezone().strftime("%d/%m %H:%M")
    except ValueError:
        texto = ts
    errores = e.get("errores") or {}
    return "%s (%d error%s)" % (texto, len(errores), "es" if len(errores) > 1 else "") \
        if errores else texto


def libre(u):
    return (u.get("status") or "").strip().lower() not in NO_LIBRES and not u.get("uso")


def refrescable(u):
    """Solo CC o CE con numero: lo demas los servicios no lo entienden."""
    tipo, numero = clave(u)
    return numero.isdigit() and tipo in TIPOS_SERVICIO


def validaciones(u):
    """{validacion: True (pasa) | False (no pasa) | None (sin dato)}.

    Pasa = el servicio respondio OK: affiliation-validations para SAP,
    elegibilidad de productos para SIIF y card-validations v2 para ASCARD. Si
    el ultimo refresco fallo en una, queda el valor anterior (y el error en la
    ficha)."""
    e = _estado(u)
    sap = e.get("sap") or {}
    ascard = e.get("ascard") or {}
    siif = str(e.get("siif") or "")
    if siif.upper().startswith("PASS"):
        pasa_siif = True
    elif "estado" in siif:
        pasa_siif = False       # el servicio respondio y rechazo
    else:
        # "FAIL - HTTP 500": el servicio se cayo, no dijo que no (fichas de
        # antes de que eso se guardara como error)
        pasa_siif = None
    return {
        # fichas de antes de este campo solo guardaban la validacion si no era OK
        "sap": (sap.get("validacion", "OK") == "OK") if sap else None,
        "siif": pasa_siif,
        "ascard": (ascard["estado"] == "OK") if ascard.get("estado") else None,
    }


def pasa(u, nombres=VALIDACIONES_BASE):
    v = validaciones(u)
    return all(v.get(n) is True for n in nombres)


def texto_validaciones(u):
    """'Pasa las 3', 'No pasa: SIIF, ASCARD' o 'Sin dato: SIIF'."""
    v = validaciones(u)
    if all(x is None for x in v.values()):
        return ""
    malas = [n.upper() for n in VALIDACIONES if v[n] is False]
    if malas:
        return "No pasa: " + ", ".join(malas)
    faltan = [n.upper() for n in VALIDACIONES if v[n] is None]
    return "Sin dato: " + ", ".join(faltan) if faltan else "Pasa las 3"


def preaprobado(u):
    valor = _estado(u).get("preaprobado")
    return "" if valor is None else ("Si" if valor else "No")


def resumen(u):
    """Lo que se lee de un vistazo: lo usa la tabla del panel y la CLI."""
    return {"afiliacion": afiliacion(u), "categoria": categoria(u), "genero": genero(u),
            "validaciones": texto_validaciones(u), "preaprobado": preaprobado(u),
            "novedad": novedad(u), "caso": caso(u), "ciam": ciam(u),
            "refrescado": refrescado(u)}


def nota_corta(u):
    r = resumen(u)
    return " | ".join(v for v in (r["afiliacion"], r["categoria"], r["genero"],
                                   r["novedad"], r["caso"]) if v)


def _motivo(seccion):
    """'Ingresos insuficientes (INVALID_REQUIREMENTS)' de una seccion sap/ascard."""
    regla = seccion.get("regla") or seccion.get("detalle")
    codigo = seccion.get("codigoError")
    if regla and codigo:
        return "%s (%s)" % (regla, codigo)
    return regla or codigo or ""


def ficha(u):
    """La ficha en lineas: si pasa cada validacion y por que no, la novedad,
    el caso y la cuenta CIAM. Lo que no respondio en el ultimo refresco dice
    'no respondio' y muestra el dato anterior, si habia."""
    e = _estado(u)
    sap = e.get("sap") or {}
    a = e.get("ascard") or {}
    v = validaciones(u)
    errores = e.get("errores") or {}
    veredicto = {True: "Pasa", False: "No pasa", None: "Sin dato"}

    def linea(nombre, *partes):
        texto = " · ".join(str(p) for p in partes if p)
        error = errores.get(nombre.lower())
        if error:
            texto += "%s(no respondio: %s)" % (" " if texto else "", error[:90])
        return "  %-12s %s" % (nombre, texto)

    datos_sap = ", ".join(x for x in (
        sap.get("estado"), afiliacion(u),
        "cat %s" % sap["categoria"] if sap.get("categoria") else "", genero(u),
        "%s anos" % sap["edad"] if sap.get("edad") else "",
        (sap.get("empresa") or "").strip(),
        "tarjeta %s" % e["tms"] if e.get("tms") else "") if x)
    nov = NOVEDADES.get(a.get("tipoSolicitud")) if a.get("estado") == "OK" else ""

    siif = str(e.get("siif") or "")
    # "FAIL - HTTP 200 estado: VALIDATION_ERROR - X": solo lo de despues del veredicto
    detalle_siif = siif.split(" - ", 1)[1] if v["siif"] is False and " - " in siif else ""

    uso = u.get("uso") or {}
    banco = ", ".join(x for x in (
        "status %s" % u["status"] if u.get("status") else "",
        "falla: %s" % u["falla"] if u.get("falla") else "",
        "reservada por %s (HU %s)" % (uso.get("por"), uso.get("hu")) if uso else "",
        "etiquetas: %s" % ", ".join(u["etiquetas"]) if u.get("etiquetas") else "") if x)
    resumen_final = " | ".join(x for x in (
        "Pasa SAP, SIIF y ASCARD" if pasa(u) else texto_validaciones(u),
        nov or novedad(u), "CIAM: %s" % (ciam(u) or "?"), caso(u)) if x)
    return "\n".join([
        "%s %s  %s" % (u.get("tipo") or "CC", u.get("usuario"), e.get("nombre") or ""),
        linea("SAP", veredicto[v["sap"]], "" if v["sap"] is not False else _motivo(sap)
              or sap.get("validacion"), datos_sap),
        linea("SIIF", veredicto[v["siif"]], detalle_siif),
        linea("ASCARD", veredicto[v["ascard"]], nov or _motivo(a),
              "amparada" if a.get("amparada") else "",
              "bolsillos %s" % a["bolsillos"] if a.get("bolsillos") else ""),
        linea("Preaprobado", preaprobado(u)),
        linea("Caso", caso(u)),
        linea("CIAM", ciam(u), "creada con Bruno" if (e.get("ciam") or {}).get("bruno") else ""),
    ] +(["  %-12s %s" % ("Banco", banco)] if banco else []) + [
        "  => %s" % resumen_final])


# --- filtros -------------------------------------------------------------------
GENERO_FILTRO = {"f": "1", "mujer": "1", "1": "1", "m": "2", "h": "2", "hombre": "2", "2": "2"}
NOVEDAD_FILTRO = {"originacion": 1, "aumento": 2, "reactivacion": 3}


def coincide(u, afiliacion=None, genero=None, novedad=None, caso=None, ciam=None,
             libres=False, etiqueta=None, texto=None, status=None, pasa_todas=None,
             no_pasa=False, preaprobado=None, categoria=None, amparada=None):
    """Todos los filtros se combinan con Y; uno vacio no filtra. Un usuario
    nunca refrescado no pasa ningun filtro que dependa del estado.

    pasa_todas: nombres de VALIDACIONES que tienen que dar OK. no_pasa: al
    menos una de VALIDACIONES dio no. preaprobado: True/False/None."""
    e = _estado(u)
    sap = e.get("sap") or {}
    if pasa_todas and not pasa(u, pasa_todas):
        return False
    if no_pasa and False not in validaciones(u).values():
        return False
    if preaprobado is not None and e.get("preaprobado") is not preaprobado:
        return False
    if categoria and _norm(sap.get("categoria")) != _norm(categoria):
        return False
    if amparada is not None and (e.get("ascard") or {}).get("amparada") is not amparada:
        return False
    if afiliacion:
        buscado = _norm(afiliacion)
        cod, grupo = sap.get("tipoTrabajador"), sap.get("grupo")
        opciones = {_norm(cod), _norm(grupo), _norm(TRABAJADOR.get(cod)), _norm(GRUPOS.get(grupo))}
        if buscado not in opciones - {""}:
            return False
    if genero:
        if sap.get("genero") != GENERO_FILTRO.get(_norm(genero), genero):
            return False
    if novedad:
        a = e.get("ascard") or {}
        buscado = _norm(novedad)
        if buscado == "rechazo":
            if not a.get("estado") or a.get("estado") == "OK":
                return False
        elif a.get("estado") != "OK" or a.get("tipoSolicitud") != NOVEDAD_FILTRO.get(buscado):
            return False
    if caso:
        c = e.get("caso") or {}
        if not c:
            return False
        sin = c.get("estado") == SIN_CASO
        if (_norm(caso) == "sin") != sin:
            return False
    if ciam:
        c = e.get("ciam") or {}
        buscado = _norm(ciam)
        ok = {"existe": c.get("existe") is True,
              "no-existe": c.get("existe") is False,
              "login-ok": c.get("login") == "OK",
              "sin-verificar": c.get("login") == "PENDIENTE_VERIFICACION"}.get(buscado)
        if not ok:
            return False
    if libres and not libre(u):
        return False
    if etiqueta and _norm(etiqueta) not in {_norm(t) for t in u.get("etiquetas") or []}:
        return False
    if status and _norm(u.get("status")) != _norm(status):
        return False
    if texto:
        # cada palabra tiene que aparecer, en cualquier orden
        pajar = _norm(" ".join([str(u.get(k) or "") for k in ("usuario", "descripcion", "falla")]
                               + list(u.get("etiquetas") or []) + [str(e.get("nombre") or "")]))
        if not all(palabra in pajar for palabra in _norm(texto).split()):
            return False
    return True


def filtrar(datos, **filtros):
    return [(i, u) for i, u in enumerate(datos) if coincide(u, **filtros)]


# --- cambios a la ficha ----------------------------------------------------------
def _etiqueta(t):
    return re.sub(r"\s+", "-", str(t).strip().lower())


def etiquetar(u, agregar=(), quitar=()):
    """Agrega y quita etiquetas sin repetir. Devuelve True si cambio algo."""
    antes = list(u.get("etiquetas") or [])
    fuera = {_etiqueta(t) for t in quitar}
    nuevas = [t for t in antes if _etiqueta(t) not in fuera]
    for t in agregar:
        t = _etiqueta(t)
        if t and t not in nuevas:
            nuevas.append(t)
    if nuevas:
        u["etiquetas"] = nuevas
    else:
        u.pop("etiquetas", None)
    return nuevas != antes


def reservar(u, hu, por=None):
    u["status"] = "En uso"
    u["uso"] = {"por": por or getpass.getuser(), "hu": str(hu).strip(), "desde": _ahora()}


def liberar(u):
    u.pop("uso", None)
    if (u.get("status") or "").strip().lower() == "en uso":
        u["status"] = "Disponible"


def aplicar(datos, k, estado):
    """Mete el resultado de un refresco en todos los registros de esa cedula.
    Las secciones que fallaron esta vez conservan lo que traian."""
    for u in datos:
        if clave(u) != k:
            continue
        nuevo = dict(_estado(u))
        for s in SECCIONES:
            if s in estado:
                nuevo[s] = estado[s]
        nuevo["actualizado"] = estado.get("actualizado") or _ahora()
        if estado.get("errores"):
            nuevo["errores"] = estado["errores"]
        else:
            nuevo.pop("errores", None)
        u["estado"] = nuevo
        # la creo Bruno: nacio con la clave de registro-dev. Una que ya
        # tiene clave no se toca (pudo cambiarse en el front)
        if not u.get("clave") and (nuevo.get("ciam") or {}).get("bruno"):
            u["clave"] = clave_registro() or ""


def importar(datos, entrantes):
    """Agrega las cedulas que faltan y suma etiquetas a las que ya estan. No
    toca claves ni status de lo existente. Devuelve (agregados, actualizados)."""
    idx = por_clave(datos)
    agregados = actualizados = 0
    for e in entrantes:
        tipo, numero = parse_doc("%s:%s" % (e.get("tipo") or "CC",
                                            e.get("usuario") or e.get("numero") or ""))
        k = (tipo, numero)
        if k in idx:
            cambio = False
            for u in idx[k]:
                cambio |= etiquetar(u, e.get("etiquetas") or [])
                if e.get("descripcion") and not u.get("descripcion"):
                    u["descripcion"] = e["descripcion"]
                    cambio = True
            actualizados += cambio
            continue
        u = {"tipo": tipo, "usuario": numero, "clave": "",
             "descripcion": e.get("descripcion") or "", "status": e.get("status") or "",
             "falla": ""}
        etiquetar(u, e.get("etiquetas") or [])
        datos.append(u)
        idx[k] = [u]
        agregados += 1
    return agregados, actualizados


# --- catalogo del repo -----------------------------------------------------------
# usuarios_compartidos.json lleva la libreta, las etiquetas, la reserva y el
# estado del ultimo refresco: quien lo trae ve la tabla igual que quien lo
# publico. Del estado no van el nombre, la edad ni la empresa del afiliado: son
# datos de una persona y el repo es publico. La tabla no los usa y la ficha los
# vuelve a traer con Refrescar.
LIBRETA = ("tipo", "usuario", "clave", "descripcion", "status", "falla")
PERSONALES = ("nombre",)
PERSONALES_SAP = ("edad", "empresa")


def publicable(u, con_clave=False):
    """El registro como va al catalogo del repo. La clave solo si se pide."""
    fila = {c: u.get(c, "") for c in LIBRETA}
    if not con_clave:
        fila["clave"] = ""
    if u.get("etiquetas"):
        fila["etiquetas"] = list(u["etiquetas"])
    if u.get("uso"):
        fila["uso"] = dict(u["uso"])
    if u.get("estado"):
        estado = copy.deepcopy(u["estado"])
        for campo in PERSONALES:
            estado.pop(campo, None)
        for campo in PERSONALES_SAP:
            (estado.get("sap") or {}).pop(campo, None)
        fila["estado"] = estado
    return fila


def _actualizado(u):
    """Cuando se refresco ('' si nunca). _ahora() siempre lo escribe en UTC y
    con el mismo formato, asi que se compara como texto."""
    return _estado(u).get("actualizado") or ""


def _con_personales(estado, local):
    """El estado del repo con el nombre, la edad y la empresa que ya se
    tenian: el catalogo no los trae."""
    nuevo = copy.deepcopy(estado)
    for campo in PERSONALES:
        if local.get(campo):
            nuevo.setdefault(campo, local[campo])
    sap, sap_local = nuevo.get("sap"), local.get("sap") or {}
    if isinstance(sap, dict):
        for campo in PERSONALES_SAP:
            if sap_local.get(campo):
                sap.setdefault(campo, sap_local[campo])
    return nuevo


def traer(datos, compartidos):
    """Suma el catalogo del repo a la libreta. Lo que falta entra tal cual
    viene (las repetidas del catalogo tambien). En lo que ya esta se suman
    etiquetas, se llena lo vacio (clave, descripcion, status, falla, reserva) y
    el estado se cambia si el del repo es de un refresco mas nuevo: lo que cada
    quien escribio no se pisa. Devuelve (agregados, actualizados).

    Una cedula repetida se empareja por orden: lo vacio de la segunda fila se
    llena con la segunda del catalogo, no con la primera (cada fila tiene su
    propia descripcion y falla). Etiquetas y estado van a todas, como en un
    refresco."""
    tengo = por_clave(datos)
    vistas = {}
    agregados = actualizados = 0
    for c in compartidos:
        k = clave(c)
        if k not in tengo:
            datos.append(copy.deepcopy(c))
            agregados += 1
            continue
        posicion = vistas[k] = vistas.get(k, -1) + 1
        cambio = False
        for i, u in enumerate(tengo[k]):
            cambio |= etiquetar(u, c.get("etiquetas") or [])
            if c.get("estado") and _actualizado(c) > _actualizado(u):
                u["estado"] = _con_personales(c["estado"], _estado(u))
                cambio = True
            if i != posicion:
                continue
            for campo in ("clave", "descripcion", "status", "falla"):
                if c.get(campo) and not u.get(campo):
                    u[campo] = c[campo]
                    cambio = True
            # la reserva llega con su status: sin el quedaria reservada y
            # "Disponible" a la vez
            if c.get("uso") and not u.get("uso"):
                u["uso"] = dict(c["uso"])
                u["status"] = c.get("status") or u.get("status", "")
                cambio = True
        actualizados += cambio
    return agregados, actualizados


# --- cargar archivos con cedulas -----------------------------------------------
# Encabezados que se reconocen, ya en minusculas, sin tildes ni espacios
COL_TIPO = {"tipo", "tipodoc", "tipodocumento", "tipoid", "tipoidentificacion",
            "tipodedocumento", "regtipodoc"}
COL_NUMERO = {"numero", "numerodocumento", "documento", "cedula", "identificacion",
              "numeroid", "numeroidentificacion", "nrodocumento", "nodocumento",
              "numerodedocumento", "usuario", "regnumerodocumento"}
COL_NOTA = {"descripcion", "nota", "notas", "observacion", "observaciones", "comentario"}


def _col(texto):
    return re.sub(r"[^a-z0-9]", "", _norm(texto))


def _tipo_de(valor):
    t = _norm(valor)
    if t in ("", "cc", "co1c", "c") or "ciudadan" in t:
        return "CC"
    if t in ("ce", "co1e", "e") or "extranj" in t:
        return "CE"
    return None


def _numero_de(valor):
    if isinstance(valor, float) and valor.is_integer():
        valor = int(valor)
    texto = str(valor if valor is not None else "").strip()
    # 52.335.676 o 52,335,676: asi sale de un Excel con formato de miles
    if re.fullmatch(r"\d{1,3}([.,]\d{3})+", texto):
        texto = re.sub(r"[.,]", "", texto)
    return texto if texto.isdigit() else None


def _filas_archivo(ruta):
    if os.path.splitext(ruta)[1].lower() in (".xlsx", ".xlsm", ".xls"):
        # leido como texto daria basura y un "no encontre cedulas" enganoso
        raise ValueError("%s es un Excel: guardalo como CSV (Archivo > Guardar "
                         "como > CSV) e importa ese." % os.path.basename(ruta))
    # un CSV guardado desde Excel suele venir en cp1252: las cedulas son
    # digitos y no se pierden con el reemplazo
    with open(ruta, encoding="utf-8-sig", errors="replace") as f:
        lineas = f.read().splitlines()
    filas = []
    for linea in lineas:
        partes = [p.strip().strip('"') for p in re.split(r"[,;\t|]", linea)]
        if len(partes) == 1:
            partes = linea.replace(":", " ").split()     # "CC:123", "CC 123" o "123"
        filas.append(partes)
    return filas


def leer_archivo(ruta):
    """Cedulas de un .csv, .txt o .json. Con encabezado (tipo/numero,
    documento, cedula...) o una cedula por linea. Sin tipo, es CC.
    Devuelve ([{tipo, usuario, descripcion?}], [filas que no se entendieron])."""
    if ruta.lower().endswith(".json"):
        with open(ruta, encoding="utf-8") as f:
            datos = json.load(f)
        return (datos if isinstance(datos, list) else []), []
    filas = [f for f in _filas_archivo(ruta)
             if any(c not in (None, "") and str(c).strip() for c in f)]
    if not filas:
        return [], []
    # el encabezado puede no ser la primera fila (un titulo arriba, en Excel)
    inicio, i_tipo, i_num, i_nota = None, None, None, None
    for n, fila in enumerate(filas[:5]):
        cab = [_col(c) for c in fila]
        if any(c in COL_NUMERO for c in cab):
            inicio = n + 1
            i_num = next(i for i, c in enumerate(cab) if c in COL_NUMERO)
            i_tipo = next((i for i, c in enumerate(cab) if c in COL_TIPO), None)
            i_nota = next((i for i, c in enumerate(cab) if c in COL_NOTA), None)
            break
    entrantes, malas, vistos = [], [], set()
    for fila in filas[inicio or 0:]:
        def celda(i):
            return fila[i] if i is not None and i < len(fila) else None
        if inicio is None:
            # sin encabezado, fila por fila: el numero es la primera celda con
            # digitos y el tipo, la de antes si la hay ("CC:123" o solo "123")
            n_num = next((i for i, c in enumerate(fila) if _numero_de(c)), None)
            numero = _numero_de(celda(n_num))
            tipo = _tipo_de(celda(n_num - 1)) if n_num else "CC"
        else:
            numero = _numero_de(celda(i_num))
            tipo = _tipo_de(celda(i_tipo)) if i_tipo is not None else "CC"
        if not numero or not tipo:
            malas.append([c for c in fila if c not in (None, "")])
            continue
        if (tipo, numero) in vistos:
            continue
        vistos.add((tipo, numero))
        e = {"tipo": tipo, "usuario": numero}
        if celda(i_nota):
            e["descripcion"] = str(celda(i_nota)).strip()
        entrantes.append(e)
    return entrantes, malas


def etiqueta_de_archivo(ruta):
    base = re.sub(r"[^a-z0-9]+", "-", _norm(os.path.splitext(os.path.basename(ruta))[0]))
    return ("lote-" + base.strip("-"))[:45]


# --- perfil en lenguaje natural --------------------------------------------------
# "mujer pensionada preaprobada que pase las validaciones" -> filtros. Lo que no
# se reconoce se busca como texto (una cedula, una etiqueta, un nombre).
PALABRAS_VACIAS = set("""
dame deme dar quiero necesito busca buscar buscame encuentra un una uno unos unas el la los
las lo de del al a y e o u que q con para por en se sea sean este esta estan tenga tengan
tiene tienen usuario usuarios usuaria usuarias cedula cedulas documento documentos persona
personas afiliado afiliada afiliados afiliadas cliente clientes es decir mi me su sus
cualquier cualquiera alguno alguna algun ya tambien ademas como cuyo cuya esto
""".split())
CANTIDADES = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5}
PERFIL_AFILIACION = {
    "dependiente": "ZTRA", "dependientes": "ZTRA", "dependienta": "ZTRA",
    "independiente": "ZAIN", "independientes": "ZAIN",
    "pensionado": "ZAPE", "pensionados": "ZAPE", "pensionada": "ZAPE", "pensionadas": "ZAPE",
    "facultativo": "ZAFA", "facultativos": "ZAFA", "facultativa": "ZAFA", "facultativas": "ZAFA",
}
# la forma femenina ya dice el genero: "una pensionada" es mujer
FEMENINAS = {"pensionada", "pensionadas", "facultativa", "facultativas", "dependienta"}
PERFIL_GENERO = {"mujer": "1", "mujeres": "1", "femenino": "1", "femenina": "1", "ella": "1",
                 "hombre": "2", "hombres": "2", "masculino": "2"}
PERFIL_NOVEDAD = {"originacion": "originacion", "originaciones": "originacion",
                  "aumento": "aumento", "aumentos": "aumento", "incremento": "aumento",
                  "reactivacion": "reactivacion", "reactivaciones": "reactivacion",
                  "rechazo": "rechazo", "rechazado": "rechazo", "rechazada": "rechazo",
                  "rechaza": "rechazo", "mora": "rechazo"}
# preaprobado, preaprobada, preaprovado (con v), pre-aprobados...
PREAPROBADO = re.compile(r"^preapro[bv]ad[oa]s?$")
PASA = {"pasa", "pase", "pasan", "pasen", "apto", "apta", "aptos", "aptas", "valido", "valida",
        "validos", "validas", "validaciones", "validacion", "cumple", "cumplan", "cumpla"}
FALLA = {"falla", "fallan", "falle", "fallen"}
NIEGA = {"sin", "no", "ni"}
NOMBRE_VALIDACION = {"sap": "sap", "siif": "siif", "ascard": "ascard"}


def interpretar(texto):
    """Traduce un perfil escrito a los filtros de coincide(). Se combinan con Y.

    Devuelve (filtros, entendido, cantidad): entendido es la lista de lo que
    se reconocio, para mostrarlo; cantidad sale de "dame 2 ..." (o None)."""
    f, entendido, resto = {}, [], []
    cantidad = None
    # "pre-aprobado" y "pre aprobado" se juntan antes de partir en palabras
    tokens = re.findall(r"[a-z0-9]+", re.sub(r"pre[\s-]+apro", "preapro", _norm(texto)))
    pasa_nombres, pide_pasa, pide_no_pasa = [], False, False
    i = 0
    while i < len(tokens):
        t = tokens[i]
        niega = i > 0 and tokens[i - 1] in NIEGA
        siguiente = tokens[i + 1] if i + 1 < len(tokens) else ""
        if t in NIEGA:
            pass
        elif cantidad is None and not f and not resto and (
                t in CANTIDADES or (t.isdigit() and len(t) <= 2)):
            cantidad = CANTIDADES.get(t) or int(t)
        elif t in PERFIL_AFILIACION:
            f["afiliacion"] = PERFIL_AFILIACION[t]
            if t in FEMENINAS:
                f["genero"] = "1"
        elif t in PERFIL_GENERO:
            f["genero"] = PERFIL_GENERO[t]
        elif t in PERFIL_NOVEDAD:
            f["novedad"] = PERFIL_NOVEDAD[t]
        elif PREAPROBADO.match(t):
            f["preaprobado"] = not niega
        elif t in ("caso", "casos"):
            f["caso"] = "sin" if niega else "con"
        elif t in ("retoma", "abierto"):
            f["caso"] = "con"
        elif t in ("libre", "libres", "disponible", "disponibles"):
            f["libres"] = True
        elif t in ("ciam", "cuenta", "login"):
            f["ciam"] = "no-existe" if niega else f.get("ciam") or "existe"
        elif t in ("verificado", "verificada", "verificar"):
            f["ciam"] = "sin-verificar" if niega else "login-ok"
        elif t in ("categoria", "cat") and siguiente in ("a", "b", "c"):
            f["categoria"] = siguiente.upper()
            i += 1
        elif t in ("amparada", "amparado", "amparadas"):
            f["amparada"] = not niega
        elif t in FALLA or (t in PASA and niega):
            pide_no_pasa = True
        elif t in PASA:
            pide_pasa = True
        elif t in NOMBRE_VALIDACION:
            pasa_nombres.append(NOMBRE_VALIDACION[t])
        elif t == "todas" and pide_pasa:
            pasa_nombres.extend(VALIDACIONES)
        elif t in PALABRAS_VACIAS or (len(t) == 1 and not t.isdigit()):
            pass
        else:
            resto.append(t)
        i += 1
    if pide_no_pasa:
        f["no_pasa"] = True
    elif pide_pasa or pasa_nombres:
        f["pasa_todas"] = tuple(dict.fromkeys(pasa_nombres)) or VALIDACIONES_BASE
    if resto:
        f["texto"] = " ".join(resto)
    return f, describir(f), cantidad


def describir(f):
    """Los filtros en palabras: 'mujer · pensionado · preaprobado · pasa SAP, SIIF, ASCARD'."""
    partes = []
    if f.get("genero"):
        partes.append(GENEROS.get(f["genero"], f["genero"]).lower())
    if f.get("afiliacion"):
        cod = f["afiliacion"]
        partes.append((TRABAJADOR.get(cod) or GRUPOS.get(cod) or cod).lower())
    if f.get("categoria"):
        partes.append("categoria " + f["categoria"])
    if f.get("novedad"):
        partes.append(f["novedad"])
    if f.get("preaprobado") is not None:
        partes.append("preaprobado" if f["preaprobado"] else "sin preaprobado")
    if f.get("pasa_todas"):
        partes.append("pasa " + ", ".join(n.upper() for n in f["pasa_todas"]))
    if f.get("no_pasa"):
        partes.append("falla alguna validacion")
    if f.get("amparada") is not None:
        partes.append("amparada" if f["amparada"] else "no amparada")
    if f.get("caso"):
        partes.append("sin caso" if f["caso"] == "sin" else "con caso")
    if f.get("ciam"):
        partes.append({"existe": "con cuenta CIAM", "no-existe": "sin cuenta CIAM",
                       "login-ok": "CIAM verificado",
                       "sin-verificar": "CIAM sin verificar"}.get(f["ciam"], f["ciam"]))
    if f.get("libres"):
        partes.append("libres")
    if f.get("etiqueta"):
        partes.append("etiqueta " + f["etiqueta"])
    if f.get("status"):
        partes.append("status " + f["status"])
    if f.get("texto"):
        partes.append('texto "%s"' % f["texto"])
    return partes


# --- refresco ------------------------------------------------------------------
_va = None
_lock = threading.Lock()


def preparar():
    """validaciones_api con su API key lista. RuntimeError si token.txt no alcanza."""
    global _va
    with _lock:
        if _va is None:
            import validaciones_api as va
            va.API_KEY_ELIGIBILITY = va._secreto("api_key_card_validations")
            va.token_apigee()       # falla aqui, una vez, si token.txt esta mal
            _va = va
    return _va


def _corto(cuerpo):
    texto = cuerpo if isinstance(cuerpo, str) else json.dumps(cuerpo, ensure_ascii=False)
    texto = re.sub(r"\s+", " ", texto or "")
    return texto[:160]


# Consultas simultaneas por servidor. Con 8 o mas a la vez el WAF de AWS
# contesta 403 (su pagina HTML), Apigee 401 "Unauthorized" y SAP se pasa de
# 20 s: el dato no llega y la ficha queda con errores que no son del afiliado.
POR_SERVIDOR = 4
_cupos = {}
_lock_cupos = threading.Lock()
# lo que devuelve el trafico, no el negocio: vale reintentar con espera. El
# WAF (403 "Acceso Denegado") y CloudFront (503 "could not be satisfied") de
# platform-test cortan a rafagas y se recuperan en segundos (medido el 20/10):
# un solo reintento a los 2 s a veces no alcanzaba. Un 500 no se reintenta:
# el LRM0002 de /request/check sale siempre con la misma cedula
REINTENTABLES = {401, 403, 429, 502, 503, 504}
ESPERAS = (2, 5, 10)


def _cupo(url):
    servidor = urllib.parse.urlsplit(url).netloc
    with _lock_cupos:
        return _cupos.setdefault(servidor, threading.BoundedSemaphore(POR_SERVIDOR))


def _pedir(va, metodo, url, timeout=20, **kw):
    """va._curl con tope por servidor y reintentos (ESPERAS) si el rechazo es
    de trafico. Sin respuesta es un Fallo legible: _curl devuelve el repr del
    comando entero cuando curl se pasa del tiempo."""
    for espera in ESPERAS + (None,):
        with _cupo(url):
            status, cuerpo = va._curl(metodo, url, timeout=timeout, **kw)
        if status not in REINTENTABLES or espera is None:
            break
        time.sleep(espera)
    if status is None:
        if "timed out" in str(cuerpo):
            raise Fallo("sin respuesta en %d s" % timeout)
        raise Fallo("sin respuesta: %s" % _corto(cuerpo))
    return status, cuerpo


def _sap_de_afiliado(afiliado, sap_crudo, adicionales):
    afiliacion_sap = afiliado.get("afiliacion") or {}
    empleadores = sap_crudo.get("empleadores") if isinstance(sap_crudo, dict) else None
    companias = empleadores.get("companias") if isinstance(empleadores, dict) else None
    empresa = companias[0].get("nombre") if companias and isinstance(companias[0], dict) else None
    tms = afiliado.get("tarjetaMultiservicios") or {}
    return {
        "nombre": " ".join(p for p in (afiliado.get("primerNombre"),
                                       afiliado.get("primerApellido")) if p),
        "sap": _sin_vacios({
            "estado": afiliado.get("estado"),
            "tipoTrabajador": afiliacion_sap.get("tipoTrabajador"),
            "grupo": afiliacion_sap.get("grupo"),
            "categoria": afiliacion_sap.get("categoria") or adicionales.get("categoria"),
            "genero": afiliado.get("genero"),
            "edad": afiliado.get("edad"),
            "tipoAfiliacion": adicionales.get("tipoAfiliacion"),
            "empresa": empresa,
        }),
        "tms": tms.get("estado") if isinstance(tms, dict) else None,
    }


def _sap(va, tipo, numero):
    doc = TIPOS_SERVICIO[tipo]
    # La v2 externa, la que llama el front en /validaciones. La v1 interna
    # aplica otras reglas (rechaza por "Ingresos insuficientes" a quien la v2
    # deja pasar) y con algunos afiliados da 500 (contributionRate nulo): su
    # veredicto no dice si la cedula pasa en el flujo.
    status, cuerpo = _pedir(
        va, "POST", va.BASE_EXT + "/loans/eligibility/external/v2/affiliation-validations",
        headers={"Authorization": va.token_ciam()},
        body={"idCaso": "564789", "documento": {"tipo": doc, "numero": numero}})
    rv = cuerpo.get("resultadoValidacion") if isinstance(cuerpo, dict) else None
    rv = rv if isinstance(rv, dict) else {}
    error = rv.get("datosError") if isinstance(rv.get("datosError"), dict) else {}
    motivo = _sin_vacios({"codigoError": error.get("codigoErrorValidacion"),
                          "regla": error.get("reglaErrorValidacion"),
                          "detalle": error.get("descripcionErrorValidacion")})
    crudo = rv.get("datosSinProcesar")
    try:
        sap = json.loads(crudo) if isinstance(crudo, str) else (crudo or {})
    except ValueError:
        sap = {}
    afiliado = sap.get("afiliado") if isinstance(sap, dict) else None
    if not isinstance(afiliado, dict):
        # respaldo, como en validaciones_api: el validador de derechos
        # devuelve el mismo afiliado de SAP
        status_v, cuerpo_v = _pedir(
            va, "GET", va.BASE_APIGEE + "/api/v2/afiliacion/validador",
            headers={"Authorization": "Bearer %s" % va.token_apigee()},
            params={"numeroId": numero, "tipoId": doc})
        datos = cuerpo_v.get("data") if isinstance(cuerpo_v, dict) else None
        sap = datos[0] if isinstance(datos, list) and datos and isinstance(datos[0], dict) else {}
        afiliado = sap.get("afiliado")
        if not isinstance(afiliado, dict):
            if rv.get("estado") and rv.get("estado") != "OK":
                # SAP respondio y rechazo (no afiliado, retirado...): es un
                # "no pasa" con su motivo, no un servicio caido
                return {"sap": dict(motivo, validacion=" - ".join(
                    str(x) for x in (rv.get("estado"), rv.get("validacion")) if x))}
            raise Fallo("sin afiliado en SAP (affiliation-validations HTTP %s %s, "
                        "validador HTTP %s)" % (status, rv.get("estado") or "", status_v))
    salida = _sap_de_afiliado(afiliado, sap, rv.get("datosAdicionales") or {})
    # siempre: si el afiliado salio del validador de derechos (respaldo),
    # affiliation-validations no dijo OK y SAP no se puede contar como pasada
    if rv.get("estado") == "OK":
        salida["sap"]["validacion"] = "OK"
    elif rv.get("estado"):
        salida["sap"]["validacion"] = " - ".join(
            str(x) for x in (rv.get("estado"), rv.get("validacion")) if x)
        salida["sap"].update(motivo)
    else:
        salida["sap"]["validacion"] = "sin resultado (HTTP %s)" % status
    return salida


def _ascard(va, tipo, numero):
    status, cuerpo = _pedir(
        va, "POST", va.BASE_EXT + "/loans/eligibility/external/v2/card-validations",
        headers={"Authorization": va.token_ciam()},
        body={"documento": {"tipo": TIPOS_SERVICIO[tipo], "numero": numero}})
    rv = cuerpo.get("resultadoValidacion") if isinstance(cuerpo, dict) else None
    if not isinstance(rv, dict) or not rv.get("estado"):
        raise Fallo("HTTP %s %s" % (status, _corto(cuerpo)))
    error = rv.get("datosError") if isinstance(rv.get("datosError"), dict) else {}
    bolsillos = RE_BOLSILLO.findall(str(rv.get("datosSinProcesar") or ""))
    return {"ascard": _sin_vacios({
        "estado": rv.get("estado"),
        "tipoSolicitud": rv.get("tipoSolicitud"),
        "amparada": rv.get("tarjetaAmparada"),
        "codigoError": error.get("codigoErrorValidacion"),
        "regla": error.get("reglaErrorValidacion"),
        "detalle": error.get("descripcionErrorValidacion"),
        "bolsillos": ", ".join("%s:%s %s" % b for b in bolsillos),
    })}


def _validacion_apigee(va, ruta, body, timeout=20):
    status, cuerpo = _pedir(va, "POST", va.BASE_APIGEE + ruta, timeout=timeout,
                            headers={"Authorization": "Bearer %s" % va.token_apigee()},
                            body=body)
    resultado = cuerpo.get("resultadoValidacion") if isinstance(cuerpo, dict) else None
    if not isinstance(resultado, dict) and not 200 <= status < 300:
        # un 500 sin resultadoValidacion es el servicio caido, no un rechazo:
        # va a errores y la seccion conserva lo que traia
        raise Fallo("HTTP %s %s" % (status, _corto(cuerpo)))
    estado, detalle = va._interpretar_validacion(status, cuerpo)
    return "%s - %s" % (estado, detalle)


def _siif(va, tipo, numero):
    return {"siif": _validacion_apigee(
        va, "/api/v2/credito/elegibilidad/productos",
        {"idCaso": "a6d876f9c98d90",
         "documento": {"tipo": TIPOS_SERVICIO[tipo], "numero": numero}})}


def _preaprobado(va, tipo, numero):
    doc = {"CC": "1", "CE": "2"}[tipo]
    status, cuerpo = _pedir(
        va, "GET", va.BASE_INT + "/loans/eligibility/internal/v1/campaigns/%s/%s" % (doc, numero),
        headers={"x-api-key": va.API_KEY_ELIGIBILITY})
    if status == 200:
        return {"preaprobado": True}
    if status == 404:
        return {"preaprobado": False}
    raise Fallo("HTTP %s %s" % (status, _corto(cuerpo)))


def _caso(va, tipo, numero):
    status, cuerpo = _pedir(va, "POST", URL_CHECK, timeout=30,
                            headers={"Authorization": va.token_ciam()},
                            body={"tipo": TIPOS_SERVICIO[tipo], "numero": numero})
    resumen_caso = resumir(status, cuerpo)
    if status != 404 and not (isinstance(cuerpo, dict) and cuerpo.get("consultarCaso")):
        raise Fallo("HTTP %s %s" % (status, _corto(cuerpo)))
    consultado = cuerpo.get("consultarCaso") if isinstance(cuerpo, dict) else None
    adicionales = consultado.get("datosAdicionales") if isinstance(consultado, dict) else None
    if isinstance(adicionales, dict) and adicionales.get("tipoAfiliacion"):
        resumen_caso["tipoAfiliacion"] = adicionales["tipoAfiliacion"]
    return {"caso": resumen_caso}


# Gigya corta con 403048 si se le pregunta mucho: con 5 hilos sin espacio corto
# a las ~25 cedulas y a una cada 2 s en la 105. El castigo dura minutos (a
# veces vuelve a cortar despues de una consulta que paso) y seguir preguntando
# lo alarga: al primero se deja de preguntar un rato y lo de CIAM conserva lo
# que traia
GIGYA_LIMITE = 403048
GIGYA_PAUSA = 300
GIGYA_ESPACIO = 2.5
_gigya_hasta = [0.0]
_gigya_ultima = [0.0]
_gigya_turno = threading.Lock()


def _gigya(metodo, **campos):
    """POST de formulario a Gigya, igual que el screen-set desde el navegador.
    urllib y no curl: la clave no tiene que quedar en la linea de comandos.
    Una llamada cada GIGYA_ESPACIO segundos, sumando todos los hilos."""
    with _gigya_turno:
        espera = _gigya_ultima[0] + GIGYA_ESPACIO - time.time()
        if espera > 0 and time.time() >= _gigya_hasta[0]:
            time.sleep(espera)
        _gigya_ultima[0] = time.time()
    if time.time() < _gigya_hasta[0]:
        raise Fallo("Gigya limito las consultas (403048): no se pregunto, reintenta en unos minutos")
    datos = urllib.parse.urlencode(dict(campos, apiKey=GIGYA_API_KEY_DEV,
                                        format="json")).encode()
    pedido = urllib.request.Request(GIGYA + metodo, data=datos, headers={
        "content-type": "application/x-www-form-urlencoded",
        "origin": "https://cdns.us1.gigya.com",
        "referer": "https://cdns.us1.gigya.com/"})
    try:
        with _cupo(GIGYA), urllib.request.urlopen(pedido, timeout=20) as r:
            respuesta = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, OSError) as e:
        raise Fallo("Gigya %s: %s" % (metodo, e))
    if respuesta.get("errorCode") == GIGYA_LIMITE:
        _gigya_hasta[0] = time.time() + GIGYA_PAUSA
        raise Fallo("Gigya limito las consultas (403048): reintenta en unos minutos")
    return respuesta


def _ciam(_va, tipo, numero):
    r = _gigya("accounts.isAvailableLoginID", loginID=tipo + numero)
    if r.get("errorCode") != 0:
        raise Fallo("%s %s" % (r.get("errorCode"), r.get("errorMessage")))
    return {"ciam": {"existe": not r.get("isAvailable")}}


PASOS = (("sap", _sap), ("ascard", _ascard), ("siif", _siif), ("preaprobado", _preaprobado), ("caso", _caso))
# CIAM no va en el refresco: una cuenta que existe no deja de existir y Gigya
# corta con 403048 si se le pregunta mucho. Solo cuando se pide
PASO_CIAM = ("ciam", _ciam)


def _huella(clave_login):
    return hashlib.sha256(clave_login.encode("utf-8")).hexdigest()[:12]


def _login(est, previo, tipo, numero, clave_login):
    """Prueba la clave en Gigya, sin insistir con una que ya fallo: cada
    intento errado cuenta para el bloqueo de la cuenta."""
    ciam_previo = (previo or {}).get("ciam") or {}
    # sin preguntar CIAM se parte de lo guardado: el login no borra si existe
    ciam_nuevo = dict(est.get("ciam") or ciam_previo)
    if not clave_login:
        # sin --login se conserva lo que dio el ultimo intento
        for k in ("login", "huella", "loginTs"):
            if k in ciam_previo and ciam_nuevo.get("existe") is not False:
                ciam_nuevo.setdefault(k, ciam_previo[k])
    elif ciam_nuevo.get("existe") is False:
        pass
    elif (ciam_previo.get("login") == "CLAVE_ERRADA"
          and ciam_previo.get("huella") == _huella(clave_login)):
        ciam_nuevo.update({k: ciam_previo[k] for k in ("login", "huella", "loginTs")
                           if k in ciam_previo})
        est["errores"]["login"] = ("no se reintento: esta misma clave ya dio CLAVE_ERRADA; "
                                   "corrigela en la libreta")
    else:
        try:
            r = _gigya("accounts.login", loginID=tipo + numero, password=clave_login)
            codigo = r.get("errorCode")
            ciam_nuevo["login"] = LOGIN_CODIGOS.get(
                codigo, "ERROR %s %s" % (codigo, r.get("errorMessage") or ""))
            ciam_nuevo["huella"] = _huella(clave_login)
            ciam_nuevo["loginTs"] = _ahora()
        except Fallo as e:
            est["errores"]["login"] = str(e)
    if ciam_nuevo:
        est["ciam"] = ciam_nuevo


def _bruno(est, previo, tipo, numero, preguntar=True):
    """Marca si la cuenta la creo Bruno: registra con regCorreoBase+cc<numero>,
    asi que si ese correo esta tomado, es suya. Se pregunta una vez por
    cuenta, y solo si hace falta la clave (preguntar): queda en el estado."""
    c = est.get("ciam")
    if not c or c.get("existe") is not True or "ciam" in est["errores"]:
        return
    previo_ciam = (previo or {}).get("ciam") or {}
    if "bruno" in previo_ciam:
        c["bruno"] = previo_ciam["bruno"]
        return
    correo = correo_bruno(tipo, numero) if preguntar else None
    if not correo:
        return
    try:
        r = _gigya("accounts.isAvailableLoginID", loginID=correo)
    except Fallo:
        return
    if r.get("errorCode") == 0:
        c["bruno"] = not r.get("isAvailable")


def consultar(tipo, numero, clave_login=None, previo=None, sin_clave=True, ciam=False):
    """Estado de una cedula: solo las secciones que respondieron, mas errores.
    ciam: preguntar tambien a Gigya si tiene cuenta; sin_clave: la libreta no
    tiene su clave, y entonces se mira si la cuenta es de Bruno."""
    va = preparar()
    est = {"actualizado": _ahora(), "errores": {}}
    pasos = PASOS + ((PASO_CIAM,) if ciam else ())
    # en paralelo: la cedula tarda lo que el servicio mas lento, no la suma
    with ThreadPoolExecutor(max_workers=len(pasos)) as pool:
        futuros = {pool.submit(paso, va, tipo, numero): nombre for nombre, paso in pasos}
        for futuro in as_completed(futuros):
            try:
                est.update(futuro.result())
            except Exception as e:      # un servicio caido no tumba el resto
                est["errores"][futuros[futuro]] = str(e)[:300]
    if "ciam" in est["errores"] and (previo or {}).get("ciam"):
        est["ciam"] = dict(previo["ciam"])   # no se sabe si existe: queda lo de antes
    _login(est, previo, tipo, numero, clave_login)
    if ciam:
        _bruno(est, previo, tipo, numero, preguntar=sin_clave)
    if not est["errores"]:
        est.pop("errores")
    return est


def refrescar(registros, login=False, hilos=5, al_terminar_uno=None, ciam=False):
    """Consulta cada cedula una sola vez, aunque este repetida en la libreta.
    Devuelve {(tipo, numero): estado}; al_terminar_uno(k, estado) se llama
    desde los hilos del pool a medida que llegan."""
    preparar()
    unicos = {}
    for u in registros:
        k = clave(u)
        if refrescable(u) and k not in unicos:
            unicos[k] = u
    sin_clave = {clave(u) for u in registros if not u.get("clave")}
    salida = {}
    with ThreadPoolExecutor(max_workers=max(1, hilos)) as pool:
        futuros = {pool.submit(consultar, k[0], k[1],
                               (u.get("clave") or None) if login else None,
                               u.get("estado"), k in sin_clave, ciam): k
                   for k, u in unicos.items()}
        for futuro in as_completed(futuros):
            k = futuros[futuro]
            try:
                est = futuro.result()
            except Exception as e:
                est = {"actualizado": _ahora(), "errores": {"refresco": str(e)[:300]}}
            salida[k] = est
            if al_terminar_uno:
                al_terminar_uno(k, est)
    return salida


# --- exportar ------------------------------------------------------------------
def exportar_cedulas(grupo, registros, reemplazar=False, ruta=CEDULAS_JSON):
    """Escribe las cedulas en un data provider de cedulas.json (sin claves)."""
    with open(ruta, encoding="utf-8") as f:
        datos = json.load(f)
    filas = [] if reemplazar else list(datos.get(grupo) or [])
    hay = {(f["tipo"], f["numero"]) for f in filas}
    nuevas = 0
    for u in registros:
        k = clave(u)
        if k in hay:
            continue
        filas.append({"tipo": k[0], "numero": k[1], "nota": nota_corta(u)})
        hay.add(k)
        nuevas += 1
    datos[grupo] = filas
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return nuevas, len(filas)


def exportar_bruno(registros, ruta=CSV_BRUNO):
    """CSV que lee Crear Usuarios Lote[Gigya] (bru run --csv-file-path)."""
    hay, filas = set(), []
    for u in registros:
        k = clave(u)
        if k not in hay:
            hay.add(k)
            filas.append("%s,%s" % k)
    # data/ no se versiona: en un clon recien hecho no existe
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("regTipoDoc,regNumeroDocumento\n")
        f.write("".join(fila + "\n" for fila in filas))
    return len(filas)


# --- crear la cuenta CIAM --------------------------------------------------------
GIGYA_REGISTRO = {
    0: "CREADA: ya puede iniciar sesion",
    206001: "CREADA pero con registro incompleto (faltan campos)",
    206002: "CREADA, falta verificar el correo (abrir el enlace del buzon)",
    400003: "NO CREADA: el correo o el usuario ya existen",
    400009: "NO CREADA: error de validacion",
    401020: "NO CREADA: Gigya pide captcha; crearla desde el navegador",
}
ENV_REGISTRO = os.path.join(BRUNO_DIR, "environments", "registro-dev.bru")


def _var_registro(nombre):
    """Una variable del environment registro-dev. None si no esta."""
    try:
        with open(ENV_REGISTRO, encoding="utf-8") as f:
            m = re.search(r"^[ \t]*%s:(.*)$" % re.escape(nombre), f.read(), re.M)
    except OSError:
        return None
    return (m.group(1).strip() or None) if m else None


def clave_registro():
    """regPassword de registro-dev: la clave con la que Crear Usuarios
    Lote[Gigya] crea todas las cuentas. None si el environment no la tiene."""
    return _var_registro("regPassword")


def correo_bruno(tipo, numero):
    """El correo con que Bruno registra la cedula: regCorreoBase con
    +cc<numero> (ej. base+cc123@dominio). None sin regCorreoBase."""
    base = _var_registro("regCorreoBase") or ""
    if "@" not in base:
        return None
    usuario, dominio = base.split("@", 1)
    return ("%s+%s%s@%s" % (usuario, tipo, numero, dominio)).lower()


def crear_ciam(registros):
    """Corre Crear Usuarios Lote[Gigya] de Bruno con estas cedulas (reescribe
    data/usuarios_registro.csv). Devuelve [(clave, texto, uid, correo)]. El
    request salta solo las que ya tienen cuenta. RuntimeError si no hay bru."""
    claves = list(dict.fromkeys(clave(u) for u in registros))
    if not claves:
        return []
    # bru.ps1 no corre con la execution policy de la maquina; bru.cmd si
    exe = shutil.which("bru.cmd") or shutil.which("bru")
    if not exe:
        raise RuntimeError("no encuentro el CLI de Bruno (npm install -g @usebruno/cli)")
    exportar_bruno(registros)
    fd, reporte = tempfile.mkstemp(prefix="bruno_registro_", suffix=".json")
    os.close(fd)
    try:
        proc = subprocess.run(
            [exe, "run", BRUNO_LOTE, "--env", "registro-dev",
             "--csv-file-path", os.path.relpath(CSV_BRUNO, BRUNO_DIR),
             "--reporter-json", reporte,
             # sin esto la clave queda escrita en el reporte
             "--reporter-skip-request-body"],
            cwd=BRUNO_DIR, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60 + 20 * len(claves))
        try:
            with open(reporte, encoding="utf-8") as f:
                corridas = json.load(f)
        except ValueError:
            corridas = None
        if not corridas:
            raise RuntimeError("bru no dejo reporte (exit %s): %s"
                               % (proc.returncode, _corto(proc.stdout + proc.stderr)))
    finally:
        os.remove(reporte)
    resultados = [r for c in (corridas if isinstance(corridas, list) else [corridas])
                  for r in c.get("results") or []]
    salida = []
    for n, k in enumerate(claves):
        r = next((r for r in resultados if r.get("iterationIndex") == n), None)
        data = ((r or {}).get("response") or {}).get("data")
        data = data if isinstance(data, dict) else {}
        if r is None:
            texto = "sin resultado de Bruno"
        elif r.get("status") == "skipped" or ("errorCode" not in data and not r.get("error")):
            texto = "YA TENIA CUENTA (el usuario o el correo existen); no se toco"
        elif "errorCode" in data:
            codigo = data["errorCode"]
            texto = GIGYA_REGISTRO.get(codigo, "NO CREADA: %s %s" % (codigo, data.get("errorMessage")))
            if data.get("validationErrors"):
                texto += " %s" % _corto(data["validationErrors"])
        else:
            texto = "NO CREADA: %s" % _corto(r.get("error"))
        correos = data.get("emails") if isinstance(data.get("emails"), dict) else {}
        correo = next(iter((correos.get("unverified") or []) + (correos.get("verified") or [])),
                      (data.get("profile") or {}).get("email") if isinstance(data.get("profile"), dict)
                      else None)
        salida.append((k, texto, data.get("UID"), correo))
    return salida


# --- CLI -----------------------------------------------------------------------
def _lista_validaciones(texto):
    if not texto:
        return None
    if _norm(texto) == "todas":
        return VALIDACIONES
    nombres = tuple(NOMBRE_VALIDACION.get(_norm(x), _norm(x)) for x in texto.split(",") if x.strip())
    malos = [n for n in nombres if n not in VALIDACIONES]
    if malos:
        raise ValueError("validacion desconocida: %s (hay: %s, o 'todas')"
                         % (", ".join(malos), ", ".join(VALIDACIONES)))
    return nombres


def _filtros(args):
    """El perfil en palabras primero; las opciones explicitas mandan sobre el."""
    perfil = " ".join(getattr(args, "perfil_libre", None) or [])
    if args.perfil:
        perfil = (perfil + " " + args.perfil).strip()
    f, _entendido, cantidad = interpretar(perfil) if perfil else ({}, [], None)
    explicitos = {
        "afiliacion": args.afiliacion, "genero": args.genero, "novedad": args.novedad,
        "caso": "sin" if args.sin_caso else ("con" if args.con_caso else None),
        "ciam": args.ciam, "libres": args.libres or None, "etiqueta": args.etiqueta,
        "texto": args.texto, "status": args.status, "categoria": args.categoria,
        "pasa_todas": _lista_validaciones(args.pasa), "no_pasa": args.no_pasa or None,
        "preaprobado": True if args.preaprobado else (False if args.sin_preaprobado else None),
    }
    f.update({k: v for k, v in explicitos.items() if v is not None})
    return f, cantidad


def _imprimir(filas):
    if not filas:
        print("Ningun usuario cumple los filtros.")
        return
    fmt = "%-2s %-11s %-21s %-3s %-6s %-22s %-3s %-23s %-30s %-12s %-10s %s"
    print(fmt % ("", "Usuario", "Afiliacion", "Cat", "Genero", "Validaciones", "Pre",
                 "Novedad", "Caso", "CIAM", "Status", "Etiquetas / uso"))
    for _i, u in filas:
        r = resumen(u)
        uso = u.get("uso") or {}
        extra = ", ".join(u.get("etiquetas") or [])
        if uso:
            extra = ("%s  [reservado por %s, HU %s]" % (extra, uso.get("por"), uso.get("hu"))).strip()
        print(fmt % (u.get("tipo", ""), u.get("usuario", ""), r["afiliacion"][:21],
                     r["categoria"], r["genero"], r["validaciones"][:22], r["preaprobado"],
                     r["novedad"][:23], r["caso"][:30], r["ciam"][:12],
                     (u.get("status") or "")[:10], extra))
    print("%d usuario(s)." % len(filas))


def _publico(u):
    """La ficha sin la clave ni su huella, para --json."""
    salida = {k: v for k, v in u.items() if k != "clave"}
    if isinstance(salida.get("estado"), dict) and isinstance(salida["estado"].get("ciam"), dict):
        salida["estado"] = dict(salida["estado"])
        salida["estado"]["ciam"] = {k: v for k, v in salida["estado"]["ciam"].items()
                                    if k != "huella"}
    return salida


def _por_documentos(datos, documentos):
    idx = por_clave(datos)
    elegidos, faltan = [], []
    for d in documentos:
        k = parse_doc(d)
        if k in idx:
            elegidos.extend(idx[k])
        else:
            faltan.append("%s:%s" % k)
    if faltan:
        print("! no estan en la libreta: %s" % ", ".join(faltan))
    return elegidos


def _juntar_docs(tokens):
    """['CC', '123', 'CE:4'] -> ['CC:123', 'CE:4']: el tipo puede venir
    separado del numero por un espacio."""
    salida, i = [], 0
    while i < len(tokens):
        t = tokens[i].strip().rstrip(",")
        if (t.upper() in ("CC", "CE", "CO1C", "CO1E") and i + 1 < len(tokens)
                and tokens[i + 1].strip().rstrip(",").isdigit()):
            salida.append("%s:%s" % (t, tokens[i + 1].strip().rstrip(",")))
            i += 2
            continue
        if t:
            salida.append(t)
        i += 1
    return salida


def _sumar_faltantes(datos, documentos, etiqueta):
    """Agrega al banco las cedulas que no estan, con la etiqueta. Devuelve las
    claves pedidas, en orden y sin repetir."""
    claves = list(dict.fromkeys(parse_doc(d) for d in _juntar_docs(documentos)))
    hay = por_clave(datos)
    nuevas = [k for k in claves if k not in hay]
    if nuevas:
        importar(datos, [{"tipo": k[0], "usuario": k[1], "etiquetas": [etiqueta]} for k in nuevas])
        guardar(datos)
        print("+ %d nueva(s) en el banco con la etiqueta %s: %s"
              % (len(nuevas), etiqueta, ", ".join("%s:%s" % k for k in nuevas)))
    return claves


def _refrescar_cli(elegidos, login=False, hilos=5, fichas=False, ciam=False):
    total = len({clave(u) for u in elegidos})
    if not total:
        print("! nada que refrescar")
        return 1
    print("> refrescando %d cedula(s) con %d hilo(s)%s%s..."
          % (total, hilos, ", probando login" if login else "",
             ", preguntando CIAM" if ciam else ""), flush=True)
    hechos, pendientes, lock = [], {}, threading.Lock()
    guardados = [0]

    def volcar_pendientes():
        # se relee cada vez: el archivo pudo cambiar mientras se consultaba
        datos = leer(estricto=True)
        for k, est in pendientes.items():
            aplicar(datos, k, est)
        guardar(datos, respaldo=not guardados[0])
        guardados[0] += 1
        pendientes.clear()
        return datos

    def avance(k, est):
        with lock:
            hechos.append(k)
            pendientes[k] = est
            errores = est.get("errores") or {}
            print("  [%d/%d] %s:%s%s" % (len(hechos), total, k[0], k[1],
                                         ("  errores: " + ", ".join(sorted(errores)))
                                         if errores else ""), flush=True)
            # cada 5: cortar un lote largo no pierde lo ya consultado
            if len(pendientes) >= 5:
                volcar_pendientes()
    try:
        resultados = refrescar(elegidos, login=login, hilos=hilos, al_terminar_uno=avance,
                               ciam=ciam)
    except RuntimeError as err:
        print("! %s" % err)
        return 2
    with lock:
        datos = volcar_pendientes()
    filas = [(n, u) for n, u in enumerate(datos) if clave(u) in resultados]
    vistos, unicos = set(), []
    for n, u in filas:
        if clave(u) not in vistos:
            vistos.add(clave(u))
            unicos.append(u)
    if fichas:
        print("\n\n".join(ficha(u) for u in unicos))
        return 0
    _imprimir(filas)
    pasan = [u for u in unicos if pasa(u)]
    print("Pasan SAP, SIIF y ASCARD: %d de %d (%d tambien preaprobados)."
          % (len(pasan), len(unicos), sum(1 for u in pasan if _estado(u).get("preaprobado"))))
    return 0


def main(argv=None):
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="comando", required=True)

    def con_filtros(p):
        p.add_argument("--perfil", help='en palabras: "mujer pensionada preaprobada que pase validaciones"')
        p.add_argument("--afiliacion")
        p.add_argument("--genero")
        p.add_argument("--categoria", choices=("A", "B", "C", "a", "b", "c"))
        p.add_argument("--novedad", choices=("originacion", "aumento", "reactivacion", "rechazo"))
        p.add_argument("--pasa", nargs="?", const="sap,siif,ascard", metavar="LISTA",
                       help="pasa estas validaciones (sin LISTA o 'todas': sap,siif,ascard)")
        p.add_argument("--no-pasa", action="store_true", help="falla al menos una validacion")
        p.add_argument("--preaprobado", action="store_true")
        p.add_argument("--sin-preaprobado", action="store_true")
        p.add_argument("--sin-caso", action="store_true")
        p.add_argument("--con-caso", action="store_true")
        p.add_argument("--ciam", choices=("existe", "no-existe", "login-ok", "sin-verificar"))
        p.add_argument("--libres", action="store_true")
        p.add_argument("--etiqueta")
        p.add_argument("--texto")
        p.add_argument("--status")
        return p

    b = con_filtros(sub.add_parser("buscar", help="lista los que cumplen los filtros"))
    b.add_argument("perfil_libre", nargs="*", metavar="PERFIL",
                   help='el perfil en palabras, sin comillas: mujer preaprobada que pase validaciones')
    b.add_argument("--json", action="store_true", help="la ficha completa, sin claves")
    b.add_argument("--reservar", metavar="HU", help="reserva los libres que cumplan")
    b.add_argument("--cuantos", type=int, help="cuantos reservar (default: los del perfil, o 1)")

    hoy = "consulta-%s" % time.strftime("%Y-%m-%d")
    rv = sub.add_parser(
        "revisar", help="la ficha completa: la suma al banco si falta, la refresca y dice si "
                        "pasa, que novedad es, el caso y la cuenta CIAM")
    rv.add_argument("documentos", nargs="+", help="CC:123, CC123, 'CC 123' o solo 123 (CC)")
    rv.add_argument("--etiqueta", default=hoy, help="para las que entran nuevas (default: %s)" % hoy)
    rv.add_argument("--hilos", type=int, default=5)
    rv.add_argument("--preguntar-ciam", action="store_true",
                    help="preguntar tambien a Gigya si tiene cuenta CIAM (sin esto, la guardada)")

    cc = sub.add_parser("crear-ciam", help="crea la cuenta del login de dev con Bruno "
                                           "(Crear Usuarios Lote[Gigya])")
    cc.add_argument("documentos", nargs="+")
    cc.add_argument("--etiqueta", default=hoy, help="para las que entran nuevas al banco")

    r = con_filtros(sub.add_parser("refrescar", help="consulta el estado real en los servicios"))
    r.add_argument("documentos", nargs="*", help="CC:123 ...; sin documentos, los que cumplan los filtros")
    r.add_argument("--login", action="store_true",
                   help="probar la clave en Gigya (dice si la cuenta esta verificada)")
    r.add_argument("--preguntar-ciam", action="store_true",
                   help="preguntar tambien a Gigya si tiene cuenta CIAM (sin esto, la guardada)")
    r.add_argument("--hilos", type=int, default=5)

    s = sub.add_parser("reservar", help="marca En uso, con quien y para que HU")
    s.add_argument("documentos", nargs="+")
    s.add_argument("--hu", required=True)
    s.add_argument("--por", help="default: el usuario de Windows")
    s.add_argument("--forzar", action="store_true", help="aunque no este libre")

    lib = sub.add_parser("liberar", help="quita la reserva y lo deja Disponible")
    lib.add_argument("documentos", nargs="+")

    e = sub.add_parser("etiquetar", help="agrega o quita etiquetas")
    e.add_argument("documentos", nargs="+")
    e.add_argument("--agregar", action="append", default=[])
    e.add_argument("--quitar", action="append", default=[])

    i = sub.add_parser("importar", help="suma cedulas desde un CSV, TXT o JSON")
    i.add_argument("archivo", help=".csv/.txt con columnas tipo y numero (o una cedula "
                                   "por linea), o un .json de {tipo, usuario, etiquetas?}")
    i.add_argument("--etiqueta", help="etiqueta de la carga (default: lote-<nombre del archivo>)")
    i.add_argument("--refrescar", action="store_true", help="validarlas apenas entran")
    i.add_argument("--hilos", type=int, default=5)

    x = sub.add_parser("exportar", help="a un data provider de cedulas.json o al CSV de Bruno")
    x.add_argument("destino", choices=("cedulas", "bruno"))
    x.add_argument("grupo", nargs="?", help="data provider de cedulas.json (destino cedulas)")
    x.add_argument("--reemplazar", action="store_true", help="vacia el data provider antes")
    con_filtros(x)

    args = ap.parse_args(argv if argv is not None else sys.argv[1:])
    try:
        datos = leer(estricto=True)
    except ValueError as err:
        print("! %s no se puede leer (%s). Revisa la copia en %s" % (ARCHIVO, err, BACKUPS))
        return 2

    try:
        if args.comando == "buscar":
            filtros, cantidad = _filtros(args)
            if filtros:
                print("Perfil: %s" % " | ".join(describir(filtros)))
            filas = filtrar(datos, **filtros)
            if args.reservar:
                cuantos = args.cuantos or cantidad or 1
                libres = [(n, u) for n, u in filas if libre(u)][:max(1, cuantos)]
                if not libres:
                    print("! ninguno libre con esos filtros")
                    return 1
                for _n, u in libres:
                    reservar(u, args.reservar)
                guardar(datos)
                print("Reservados para la HU %s:" % args.reservar)
                filas = libres
            if args.json:
                print(json.dumps([_publico(u) for _n, u in filas], ensure_ascii=False, indent=2))
            else:
                _imprimir(filas)
            return 0

        if args.comando == "revisar":
            claves = set(_sumar_faltantes(datos, args.documentos, _etiqueta(args.etiqueta)))
            return _refrescar_cli([u for u in datos if clave(u) in claves], hilos=args.hilos,
                                  fichas=True, ciam=args.preguntar_ciam)

        if args.comando == "crear-ciam":
            pedidas = _sumar_faltantes(datos, args.documentos, _etiqueta(args.etiqueta))
            idx = por_clave(datos)
            print("> creando %d cuenta(s) con Bruno..." % len(pedidas), flush=True)
            try:
                resultados = crear_ciam([idx[k][0] for k in pedidas])
            except (RuntimeError, subprocess.TimeoutExpired) as err:
                print("! %s" % err)
                return 2
            # releer: bru tardo y el panel pudo guardar mientras
            datos = leer(estricto=True)
            idx = por_clave(datos)
            creadas = 0
            clave_nueva = clave_registro()
            for k, texto, uid, correo in resultados:
                print("%s:%s  %s%s%s" % (k[0], k[1], texto, "  correo %s" % correo if correo else "",
                                         "  UID %s" % uid if uid else ""))
                if uid or texto.startswith("YA TENIA"):
                    for u in idx.get(k, []):
                        u["estado"] = dict(_estado(u))
                        u["estado"]["ciam"] = dict(u["estado"].get("ciam") or {}, existe=True)
                        if uid:
                            etiquetar(u, ["ciam-creado-%s" % time.strftime("%Y-%m-%d")])
                            # la cuenta nacio con esta clave: el panel la muestra y
                            # refrescar --login la prueba. Una que ya existia no se toca
                            if clave_nueva:
                                u["clave"] = clave_nueva
                    creadas += bool(uid)
            guardar(datos)
            print("%d creada(s) de %d. Login: tipo+numero (ej. %s%s), clave del environment "
                  "registro-dev%s." % (creadas, len(resultados), pedidas[0][0], pedidas[0][1],
                                       ", guardada en el banco" if creadas and clave_nueva else ""))
            return 0

        if args.comando == "refrescar":
            if args.documentos:
                elegidos = _por_documentos(datos, _juntar_docs(args.documentos))
            else:
                filtros, _cantidad = _filtros(args)
                elegidos = [u for _n, u in filtrar(datos, **filtros)]
            return _refrescar_cli(elegidos, args.login, args.hilos, ciam=args.preguntar_ciam)

        if args.comando in ("reservar", "liberar", "etiquetar"):
            elegidos = _por_documentos(datos, args.documentos)
            for u in elegidos:
                if args.comando == "reservar":
                    if not libre(u) and not args.forzar:
                        print("! %s:%s no esta libre (status %r%s); usa --forzar"
                              % (clave(u) + (u.get("status") or "",
                                             ", reservado por %s" % u["uso"]["por"]
                                             if u.get("uso") else "")))
                        continue
                    reservar(u, args.hu, args.por)
                elif args.comando == "liberar":
                    liberar(u)
                else:
                    etiquetar(u, args.agregar, args.quitar)
            guardar(datos)
            _imprimir([(n, u) for n, u in enumerate(datos)
                       if clave(u) in {clave(v) for v in elegidos}])
            return 0

        if args.comando == "importar":
            entrantes, malas = leer_archivo(args.archivo)
            if not entrantes:
                print("! no encontre cedulas en %s" % args.archivo)
                return 1
            etiqueta = _etiqueta(args.etiqueta) if args.etiqueta else etiqueta_de_archivo(args.archivo)
            for ent in entrantes:
                ent["etiquetas"] = list(ent.get("etiquetas") or []) + [etiqueta]
            hay = por_clave(datos)
            ya_estaban = sum(1 for ent in entrantes
                             if parse_doc("%s:%s" % (ent.get("tipo") or "CC",
                                                     ent.get("usuario") or ent.get("numero")))
                             in hay)
            agregados, _actualizados = importar(datos, entrantes)
            guardar(datos)
            print("%d cedula(s) en %s: %d nuevas, %d ya estaban. Etiqueta: %s"
                  % (len(entrantes), os.path.basename(args.archivo), agregados, ya_estaban,
                     etiqueta))
            if malas:
                print("! %d fila(s) sin cedula valida (ej.: %s)"
                      % (len(malas), "; ".join(" ".join(str(c) for c in m) for m in malas[:3])))
            if args.refrescar:
                return _refrescar_cli([u for _n, u in filtrar(datos, etiqueta=etiqueta)],
                                      hilos=args.hilos)
            print("Para validarlas: python usuarios.py refrescar --etiqueta %s" % etiqueta)
            return 0

        if args.comando == "exportar":
            filtros, _cantidad = _filtros(args)
            elegidos = [u for _n, u in filtrar(datos, **filtros)]
            if args.destino == "cedulas":
                if not args.grupo:
                    print("! exportar cedulas necesita el nombre del data provider")
                    return 2
                nuevas, total = exportar_cedulas(args.grupo, elegidos, args.reemplazar)
                print("%s: %d nueva(s), %d en total (%s)"
                      % (args.grupo, nuevas, total, CEDULAS_JSON))
            else:
                n = exportar_bruno(elegidos)
                print("%d cedula(s) en %s" % (n, CSV_BRUNO))
            return 0
    except OSError as err:
        print("! %s" % err)
        return 2
    except ValueError as err:
        print("! %s" % err)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

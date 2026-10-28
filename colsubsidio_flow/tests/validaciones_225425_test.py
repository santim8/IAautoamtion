"""HU 225425: validaciones de caja (SAP, ASCARD y SIIF) desde el front.

Inicia sesion como hasta-politicas (token o clave), deja que /validaciones
llame los tres servicios y los valida desde lo que capturo el observador:
  - que ninguno responda con error tecnico (5xx, red cortada)
  - el request: documento del afiliado, grupoProducto e idProducto del producto
  - el contrato: resultadoValidacion.validacion y estado; codigo si rechaza;
    que SAP externo no exponga el salario en datosAdicionales
  - el orden y el corte: SAP -> ASCARD -> SIIF, uno tras la respuesta del
    anterior, y nada despues de un rechazo
  - la pantalla: politicas si todo pasa; si no, el mensaje de Drupal
    (casuistica) del codigo, o CFA si SIIF pide retanqueo en Consumo
  - lo esperado para la cedula: campo "esperado" del data provider, con
    "sap"/"ascard"/"siif" = OK | RECHAZO | NO_LLAMADO | <codigo> y
    "pantalla" = politicas | mensaje | otro sitio

Al final imprime una tabla con todas las cedulas y la deja en
evidences/validaciones-225425_<producto>_<fecha>.json y .md.

No esta en Java: es nuevo.
"""
import html
import json
import re
from datetime import datetime, timedelta

from .. import _rutas  # noqa: F401
from ..core import reporte as log
from . import hasta_politicas_test as hp

import rutas  # noqa: E402  (raiz del repo, via _rutas)

NOMBRE = "Validaciones225425"
TEST_ID = "225425"
AUTORES = "Santiago Correa"
CATEGORIAS = ("REGRESSION",)
DATA_PROVIDER = "validaciones_225425"
URL = hp.URL
MANEJA_HASTA_LOGIN = True

SERVICIOS = (("sap", "/affiliation-validations", "SAP-AFILIACIONES"),
             ("ascard", "/card-validations", "ASCARD-TMS-CUPO"),
             ("siif", "/product-validations", "SIIF-OBLIGACIONES"))
# productCatalog.constants.ts del front.
ID_PRODUCTO = {"libre-inversion": 1, "compra-de-cartera": 2, "mujeres": 72}
TIPO_FRONT = {"CC": "CO1C", "CE": "CO1E"}
NO_LLAMADO = "NO_LLAMADO"
RECHAZO = "RECHAZO"
# El front reacciona a la respuesta, no al ultimo byte: margen para el orden.
TOLERANCIA_ORDEN = timedelta(milliseconds=300)

FILAS = []          # una por cedula, para la tabla de al_terminar
_casuisticas = {}


def necesita_clave(opciones):
    return hp.necesita_clave(opciones)


def url_inicial(opciones):
    return hp.url_inicial(opciones)


def check(ok, nombre, detalle=""):
    (log.pass_ if ok else log.fail)(nombre + (" -- " + detalle if detalle else ""))
    return ok


def leer(texto):
    try:
        return json.loads(texto) if texto else None
    except ValueError:
        return None


def limpio(texto):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", texto or ""))).strip()


def casuistica(driver, codigo):
    if not _casuisticas:
        respuesta = driver.context.request.get(
            "https://platform-test-external.colsubsidio.com/loans-cert-admin-solicitud"
            "/api_creditos/parametros/casuisticas", timeout=20000)
        for c in (respuesta.json() if respuesta.ok else []):
            _casuisticas.setdefault(c.get("code"), c)
    return _casuisticas.get(codigo)


# -- lo capturado
def llamada(obs, ruta):
    regs = [r for p in obs.pasos for r in p["requests"]
            if ruta in r["url"] and r["metodo"] == "POST"]
    if len(regs) > 1:
        log.warning("%s se llamo %d veces" % (ruta, len(regs)))
    return regs[0] if regs else None


def resultado(reg):
    """OK, el codigo del rechazo, HTTP <status> <codigo> o NO_LLAMADO."""
    if reg is None:
        return NO_LLAMADO
    status = reg.get("status") or 0
    cuerpo = leer(reg.get("response_body")) or {}
    if reg.get("fallo") or not 200 <= status < 300:
        error = (cuerpo.get("errores") or [{}])[0]
        return ("HTTP %s %s" % (status or reg.get("fallo"), error.get("codigoError", ""))).strip()
    rv = cuerpo.get("resultadoValidacion") or {}
    if rv.get("estado") == "OK":
        return "OK"
    return (rv.get("datosError") or {}).get("codigoErrorValidacion") or rv.get("estado") or "?"


def inicio(reg):
    t = reg.get("timing") or {}
    if t.get("inicio"):
        return datetime.fromtimestamp(t["inicio"] / 1000).astimezone()
    return datetime.fromisoformat(reg["ts"])


def fin(reg):
    """Fin real de la respuesta (o llegada de cabeceras si el cuerpo no termino)."""
    t = reg.get("timing") or {}
    marca = t.get("fin") or t.get("cabeceras")
    if marca:
        return datetime.fromtimestamp(marca / 1000).astimezone()
    return inicio(reg) + timedelta(milliseconds=reg.get("duracion_ms") or 0)


def latencia(reg):
    t = reg.get("timing") or {}
    if t.get("inicio") and t.get("fin"):
        return "%d ms" % (t["fin"] - t["inicio"])
    if t.get("inicio") and t.get("cabeceras"):
        return "%d ms (cabeceras; el cuerpo no termino)" % (t["cabeceras"] - t["inicio"])
    return "%d ms" % (reg.get("duracion_ms") or 0)


def coincide(esperado, real):
    if esperado == RECHAZO:
        return real not in ("OK", NO_LLAMADO) and not real.startswith("HTTP")
    return esperado == real


# -- las pruebas
def probar_requests(regs, usuario, opciones):
    consumo = opciones.get("entrada") != "cupo"
    slug = opciones.get("slug") or "libre-inversion"
    for clave, _ruta, nombre in SERVICIOS:
        reg = regs[clave]
        if reg is None:
            continue
        body = leer(reg.get("request_body")) or {}
        doc = body.get("documento") or {}
        check(doc == {"tipo": TIPO_FRONT[usuario.tipo], "numero": usuario.numero},
              "%s: request con el documento del afiliado" % nombre, json.dumps(doc))
        check(body.get("grupoProducto") == ("CONSUMO" if consumo else "CUPO"),
              "%s: grupoProducto %s" % (nombre, body.get("grupoProducto")))
        if consumo and slug in ID_PRODUCTO:
            check(str(body.get("idProducto")) == str(ID_PRODUCTO[slug]),
                  "%s: idProducto %s para %s" % (nombre, body.get("idProducto"), slug))
        elif not consumo:
            check("idProducto" not in body, "%s: Cupo sin idProducto" % nombre)


def probar_respuestas(regs, res):
    for clave, _ruta, nombre in SERVICIOS:
        reg = regs[clave]
        if reg is None:
            continue
        check(not res[clave].startswith("HTTP"), "%s responde sin error tecnico" % nombre,
              "%s en %s%s" % (res[clave], latencia(reg),
                              "; " + reg["nota"] if reg.get("nota") else ""))
        cuerpo = leer(reg.get("response_body"))
        if not cuerpo or res[clave].startswith("HTTP"):
            continue
        rv = cuerpo.get("resultadoValidacion") or {}
        check(rv.get("validacion") == nombre and rv.get("estado") in ("OK", "VALIDATION_ERROR"),
              "%s: contrato de la respuesta" % nombre,
              "validacion=%s estado=%s" % (rv.get("validacion"), rv.get("estado")))
        if rv.get("estado") == "VALIDATION_ERROR":
            error = rv.get("datosError") or {}
            check(bool(error.get("codigoErrorValidacion")), "%s: el rechazo trae codigo" % nombre,
                  "%s / %s" % (error.get("codigoErrorValidacion"), error.get("reglaErrorValidacion")))
        if clave == "sap":
            check("salario" not in (rv.get("datosAdicionales") or {}),
                  "SAP externo no expone el salario en datosAdicionales")


def probar_orden(regs, res):
    previo = None   # (clave, nombre) del ultimo servicio llamado
    corte = None    # nombre del servicio que no paso
    for clave, _ruta, nombre in SERVICIOS:
        reg = regs[clave]
        if corte:
            check(reg is None, "%s no se llama si %s no paso" % (nombre, corte))
            continue
        if previo:
            if not check(reg is not None, "%s se llama porque %s paso" % (nombre, previo[1])):
                break
            check(inicio(reg) >= fin(regs[previo[0]]) - TOLERANCIA_ORDEN,
                  "%s empieza despues de la respuesta de %s" % (nombre, previo[1]))
        elif reg is None:
            break       # ni SAP se llamo: lo dice la pantalla
        if res[clave] != "OK":
            corte = nombre
        previo = (clave, nombre)


def probar_pantalla(driver, res, desenlace, texto, opciones):
    rechazo = next((r for r in res.values() if r not in ("OK", NO_LLAMADO)), None)
    if rechazo is None:
        check(desenlace == "politicas", "Todo paso: llega a politicas", desenlace)
        return
    codigo = "EXECUTION_ERROR" if rechazo.startswith("HTTP") else rechazo
    if codigo == "MANDATORY_REFINANCE" and opciones.get("entrada") != "cupo":
        check(desenlace == "otro sitio", "Retanqueo: el front manda a CFA", desenlace)
        return
    check(desenlace == "mensaje", "%s: el front muestra un mensaje" % codigo, desenlace)
    entrada = casuistica(driver, codigo)
    if not check(entrada is not None, "Drupal tiene casuistica para %s" % codigo):
        return
    clave = limpio(entrada.get("descripcion")) or limpio(entrada.get("titulo"))
    check(clave[:60] in limpio(texto), "El mensaje en pantalla es el de %s" % codigo,
          "esperado: %r" % clave[:80])


def probar_esperado(usuario, res, desenlace):
    esperado = usuario.esperado or {}
    if not esperado:
        log.info("Sin 'esperado' en el data provider: solo se revisan las reglas generales")
        return
    reales = dict(res, pantalla=desenlace)
    for clave in ("sap", "ascard", "siif", "pantalla"):
        if clave in esperado:
            check(coincide(esperado[clave], reales[clave]), "Esperado %s=%s" % (clave, esperado[clave]),
                  "obtenido %s" % reales[clave])


def run(driver, usuario, opciones):
    if opciones.get("directo"):
        log.warning("--directo se salta las validaciones: no aplica a este test")
        opciones = dict(opciones, directo=False)
    capturado = {}

    def pasos(obs):
        capturado["desenlace"] = hp.llegar_a_politicas(driver, obs, usuario, opciones)
        capturado["texto"] = hp.texto_pantalla(driver)
        capturado["obs"] = obs

    hp.capturar(driver, usuario, opciones, "validaciones-225425", pasos)
    obs, desenlace = capturado.get("obs"), capturado.get("desenlace")
    if obs is None or desenlace is None:
        log.fail("No se inicio sesion: no hay servicios que revisar")
        return
    regs = {clave: llamada(obs, ruta) for clave, ruta, _ in SERVICIOS}
    res = {clave: resultado(reg) for clave, reg in regs.items()}
    log.info("SAP=%s | ASCARD=%s | SIIF=%s | pantalla=%s"
             % (res["sap"], res["ascard"], res["siif"], desenlace))

    fallas_antes = len(log.actual().fallas)
    probar_requests(regs, usuario, opciones)
    probar_respuestas(regs, res)
    probar_orden(regs, res)
    probar_pantalla(driver, res, desenlace, capturado.get("texto", ""), opciones)
    probar_esperado(usuario, res, desenlace)
    FILAS.append({"documento": usuario.documento, "nota": usuario.nota, **res,
                  "pantalla": desenlace, "esperado": usuario.esperado,
                  "fallas": log.actual().fallas[fallas_antes:], "evidencia": obs.dir})


def al_terminar(opciones):
    if not FILAS:
        return
    titulos = ("Documento", "SAP", "ASCARD", "SIIF", "Pantalla", "Fallas", "Nota")
    filas = [(f["documento"], f["sap"], f["ascard"], f["siif"], f["pantalla"] or "-",
              str(len(f["fallas"])), f["nota"]) for f in FILAS]
    anchos = [max(len(t), *(len(x[i]) for x in filas)) for i, t in enumerate(titulos[:-1])]
    print("\n=== Servicios por cedula (%s)" % hp.producto(opciones))
    print("  " + "  ".join(t.ljust(a) for t, a in zip(titulos, anchos)) + "  Nota")
    for x in filas:
        print("  " + "  ".join(v.ljust(a) for v, a in zip(x, anchos)) + "  " + x[-1])
    base = rutas.dato("evidences", "validaciones-225425_%s_%s"
                      % (hp.producto(opciones), datetime.now().strftime("%Y-%m-%d_%H%M%S")))
    with open(base + ".json", "w", encoding="utf-8") as f:
        json.dump(FILAS, f, ensure_ascii=False, indent=2)
    with open(base + ".md", "w", encoding="utf-8") as f:
        f.write("| %s |\n|%s|\n" % (" | ".join(titulos), "---|" * len(titulos)))
        for x in filas:
            f.write("| %s |\n" % " | ".join(v.replace("|", "/") for v in x))
        f.write("\n")
        for fila in FILAS:
            if fila["fallas"]:
                f.write("**%s**\n" % fila["documento"])
                f.writelines("- %s\n" % falla for falla in fila["fallas"])
    print("  Tabla: %s.md" % base)

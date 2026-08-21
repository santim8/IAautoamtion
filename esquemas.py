#!/usr/bin/env python3
"""Esquemas de payload/respuesta de los servicios de negocio y su validacion.

La idea: una corrida "buena" del flujo define el contrato observado (que campos
manda el front y que devuelve el back). Ese contrato se guarda en un baseline
JSON Schema y las corridas siguientes se contrastan contra el.

La validacion es SOFT: recorre todo, junta todos los hallazgos y nunca corta la
generacion de evidencia. Un cambio de contrato es un dato del reporte, no una
excepcion que te deja sin reporte.

Se usa desde observador_flujo.py, pero el baseline es un JSON normal y corriente
que se puede versionar y revisar en un PR.
"""
import json
import os
from datetime import datetime, timezone

try:
    from jsonschema import Draft7Validator
except ImportError:                                  # pragma: no cover
    Draft7Validator = None

# Un servicio se identifica por metodo + el endpoint rastreado que caso, no por
# la URL completa: la URL lleva ids (/campaigns/1/1032410060) que cambian en
# cada corrida y partirian el baseline en mil claves distintas.
def clave_servicio(reg):
    rastreados = reg.get("rastreados") or []
    if not rastreados:
        return None
    return "%s %s" % (reg.get("metodo", "?"), rastreados[0])


def _quizas_json(txt):
    if not txt:
        return None
    try:
        return json.loads(txt)
    except (json.JSONDecodeError, TypeError):
        return None


# --- inferencia ------------------------------------------------------------
def inferir_esquema(valor):
    """JSON Schema (draft-07) deducido de un ejemplo concreto."""
    if valor is None:
        return {"type": "null"}
    if isinstance(valor, bool):
        return {"type": "boolean"}
    if isinstance(valor, int):
        return {"type": "integer"}
    if isinstance(valor, float):
        return {"type": "number"}
    if isinstance(valor, str):
        return {"type": "string"}
    if isinstance(valor, list):
        if not valor:
            return {"type": "array"}
        items = None
        for it in valor:
            items = fundir_esquemas(items, inferir_esquema(it))
        return {"type": "array", "items": items}
    if isinstance(valor, dict):
        return {
            "type": "object",
            "properties": {k: inferir_esquema(v) for k, v in valor.items()},
            # required se afina al fundir varios ejemplos: aqui, con uno solo,
            # todo lo presente se asume obligatorio
            "required": sorted(valor.keys()),
        }
    return {}


def fundir_esquemas(a, b):
    """Une dos esquemas inferidos de ejemplos distintos del mismo servicio.

    required queda como INTERSECCION: solo es obligatorio lo que aparecio en
    todos los ejemplos. Un campo que a veces viene y a veces no es opcional,
    no una falla.
    """
    if a is None:
        return b
    if b is None:
        return a

    tipos = set()
    for e in (a, b):
        t = e.get("type")
        if isinstance(t, list):
            tipos.update(t)
        elif t:
            tipos.add(t)
    if "number" in tipos and "integer" in tipos:
        tipos.discard("integer")     # un entero valida contra number
    out = {}
    if tipos:
        out["type"] = sorted(tipos)[0] if len(tipos) == 1 else sorted(tipos)

    pa, pb = a.get("properties"), b.get("properties")
    if pa or pb:
        pa, pb = pa or {}, pb or {}
        out["properties"] = {k: fundir_esquemas(pa.get(k), pb.get(k))
                             for k in set(pa) | set(pb)}
        out["required"] = sorted(set(a.get("required", [])) & set(b.get("required", [])))

    ia, ib = a.get("items"), b.get("items")
    if ia or ib:
        out["items"] = fundir_esquemas(ia, ib)
    return out


def esquemas_de_corrida(pasos):
    """Recorre la evidencia y deduce el contrato de cada servicio rastreado."""
    acum = {}
    for paso in pasos:
        for r in paso.get("requests", []):
            clave = clave_servicio(r)
            if not clave:
                continue
            entrada = acum.setdefault(clave, {"ejemplos": 0, "request": None,
                                              "response": None})
            entrada["ejemplos"] += 1
            for lado, campo in (("request", "request_body"), ("response", "response_body")):
                cuerpo = _quizas_json(r.get(campo))
                if cuerpo is None:
                    continue
                entrada[lado] = fundir_esquemas(entrada[lado], inferir_esquema(cuerpo))
    return acum


def escribir_baseline(pasos, ruta):
    """Guarda (o actualiza) el baseline fundiendo lo que ya hubiera en disco."""
    nuevos = esquemas_de_corrida(pasos)
    previos = leer_baseline(ruta) or {}
    for clave, esq in nuevos.items():
        viejo = previos.get(clave)
        if viejo:
            esq = {
                "ejemplos": viejo.get("ejemplos", 0) + esq["ejemplos"],
                "request": fundir_esquemas(viejo.get("request"), esq["request"]),
                "response": fundir_esquemas(viejo.get("response"), esq["response"]),
            }
        previos[clave] = esq
    doc = {"generado": datetime.now(timezone.utc).isoformat(),
           "servicios": previos}
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2, sort_keys=True)
    return previos


def leer_baseline(ruta):
    if not ruta or not os.path.exists(ruta):
        return None
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f).get("servicios", {})
    except (json.JSONDecodeError, OSError):
        return None


# --- validacion (soft) -----------------------------------------------------
def _errores(instancia, esquema):
    """Todos los incumplimientos, no solo el primero: esto es un soft assert."""
    if Draft7Validator is None:
        return ["jsonschema no esta instalado (pip install jsonschema)"]
    out = []
    for e in sorted(Draft7Validator(esquema).iter_errors(instancia),
                    key=lambda x: list(x.absolute_path)):
        ruta = "/".join(str(p) for p in e.absolute_path) or "(raiz)"
        out.append("%s: %s" % (ruta, e.message))
    return out


def _validar_lado(cuerpo_txt, esquema):
    if esquema is None:
        return {"estado": "sin-esquema", "errores": []}
    cuerpo = _quizas_json(cuerpo_txt)
    if cuerpo is None:
        if cuerpo_txt:
            return {"estado": "no-json", "errores": []}
        return {"estado": "sin-cuerpo", "errores": []}
    errores = _errores(cuerpo, esquema)
    return {"estado": "falla" if errores else "ok", "errores": errores}


def validar(pasos, baseline):
    """Contrasta cada llamada capturada contra el baseline. Nunca lanza."""
    resultados = []
    for paso in pasos:
        for r in paso.get("requests", []):
            clave = clave_servicio(r)
            if not clave:
                continue
            esq = baseline.get(clave) or {}
            resultados.append({
                "servicio": clave,
                "paso": paso["idx"],
                "pantalla": paso.get("url", ""),
                "url": r.get("url", ""),
                "status": r.get("status"),
                "conocido": clave in baseline,
                "request": _validar_lado(r.get("request_body"), esq.get("request")),
                "response": _validar_lado(r.get("response_body"), esq.get("response")),
            })
    return resultados


def resumir(resultados):
    fallas = [x for x in resultados
              if x["request"]["estado"] == "falla" or x["response"]["estado"] == "falla"]
    nuevos = [x for x in resultados if not x["conocido"]]
    return {
        "total": len(resultados),
        "con_hallazgos": len(fallas),
        "servicios_sin_baseline": sorted({x["servicio"] for x in nuevos}),
        "hallazgos": sum(len(x["request"]["errores"]) + len(x["response"]["errores"])
                         for x in resultados),
    }


def imprimir(resultados, ruta_baseline):
    if not resultados:
        return
    res = resumir(resultados)
    print("\n--- validacion de esquemas (soft assert) ---")
    print("  baseline: %s" % (ruta_baseline or "(ninguno)"))
    for x in resultados:
        marcas = []
        for lado in ("request", "response"):
            if x[lado]["estado"] == "falla":
                marcas.append(lado)
        if not x["conocido"]:
            print("  ?   %-58s paso %d  (sin baseline)" % (x["servicio"], x["paso"]))
        elif marcas:
            print("  FAIL %-57s paso %d  (%s)"
                  % (x["servicio"], x["paso"], ", ".join(marcas)))
            for lado in marcas:
                for err in x[lado]["errores"][:6]:
                    print("        %s.%s" % (lado, err))
                sobran = len(x[lado]["errores"]) - 6
                if sobran > 0:
                    print("        ... y %d mas" % sobran)
        else:
            print("  ok   %-57s paso %d" % (x["servicio"], x["paso"]))
    print("  %d llamadas, %d con hallazgos, %d incumplimientos en total"
          % (res["total"], res["con_hallazgos"], res["hallazgos"]))
    if res["servicios_sin_baseline"]:
        print("  sin baseline (%d): %s"
              % (len(res["servicios_sin_baseline"]),
                 ", ".join(res["servicios_sin_baseline"])))


CSS = """
  .val { margin-bottom:24px; }
  .val h3 { font-size:14px; margin:0 0 8px; }
  .val h3 small { color:var(--mut); font-weight:400; margin-left:6px; }
  .val table { border-collapse:collapse; width:100%; font-size:12px; }
  .val td { padding:4px 8px; border-bottom:1px solid var(--bd); vertical-align:top; }
  .val .e { font-family:ui-monospace,Consolas,monospace; word-break:break-all; }
  .val .p { color:var(--mut); white-space:nowrap; width:1%; }
  .val .st { width:52px; font-weight:700; white-space:nowrap; }
  .val tr.ok .st { color:var(--ok); }
  .val tr.falla .st { color:var(--err); }
  .val tr.nuevo .st { color:var(--mut); }
  .val ul { margin:4px 0 0; padding-left:18px; color:var(--err); }
  .val li { font-family:ui-monospace,Consolas,monospace; font-size:11px; }
"""


def bloque_html(resultados, ruta_baseline, esc):
    """Seccion del reporte con el resultado del soft assert."""
    if not resultados:
        return ""
    res = resumir(resultados)
    filas = []
    for x in resultados:
        errores = []
        for lado in ("request", "response"):
            for err in x[lado]["errores"]:
                errores.append("%s.%s" % (lado, err))
        if errores:
            cls, etiqueta = "falla", "FALLA"
        elif not x["conocido"]:
            cls, etiqueta = "nuevo", "s/base"
        else:
            cls, etiqueta = "ok", "ok"
        lista = ("<ul>" + "".join("<li>" + esc(e) + "</li>" for e in errores) + "</ul>"
                 if errores else "")
        filas.append(
            '<tr class="' + cls + '">'
            '<td class="st">' + esc(etiqueta) + '</td>'
            '<td class="e">' + esc(x["servicio"]) + lista + '</td>'
            '<td class="p">paso ' + esc(x["paso"]) + '</td>'
            '<td class="p">' + esc(x["status"]) + '</td>'
            '</tr>')
    return ('<section class="val"><h3>Validacion de esquemas '
            '<small>' + esc(res["total"]) + ' llamadas &middot; '
            + esc(res["con_hallazgos"]) + ' con hallazgos &middot; baseline '
            + esc(os.path.basename(ruta_baseline) if ruta_baseline else "ninguno")
            + '</small></h3><table>' + "".join(filas) + '</table></section>')

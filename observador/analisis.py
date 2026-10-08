"""Lecturas sobre los pasos ya capturados. Sin estado ni Playwright: sirven
igual para una corrida en vivo que para una reconstruida desde disco."""
import json

from observador.config import SIN_RESPUESTA
from observador.endpoints import version_de, version_declarada


def es_fallo(r):
    """Status >= 400, o el navegador lo corto (CORS, red) / quedo sin respuesta."""
    return (r["status"] >= 400 or bool(r.get("fallo"))) and not r.get("sonda")


def etiqueta_fallo(r):
    """Marca corta para un request que el front nunca pudo leer."""
    fallo = r.get("fallo")
    if not fallo:
        return ""
    if r.get("cors"):
        return "CORS"
    if fallo == SIN_RESPUESTA:
        return "SIN RESPUESTA"
    if "ABORTED" in fallo.upper():
        return "ABORTADO"
    return "FALLO RED"


def endpoint_con_error(c):
    return any(not s or s >= 400 for s in c["statuses"]) or bool(c.get("fallos"))


def total_requests(pasos):
    """Lo que el front llamo: la sonda no es trafico del navegador."""
    return sum(1 for p in pasos for r in p["requests"] if not r.get("sonda"))


def total_fallos(pasos):
    return sum(1 for p in pasos for r in p["requests"] if es_fallo(r))


def linea_check(pasos):
    """Las respuestas de /request/check en orden: la historia del caso."""
    filas = []
    for paso in pasos:
        for r in paso["requests"]:
            if r.get("sonda") != "request/check":
                continue
            filas.append(dict(r.get("check") or {}, paso=paso["idx"],
                              pantalla=paso["url"], motivo=r.get("motivo"),
                              status=r["status"], ts=r["ts"]))
    return sorted(filas, key=lambda f: f["ts"])


def frames_socket(pasos):
    """Todos los frames del websocket en orden, con el paso en que cayeron."""
    return [dict(fr, paso=p["idx"], pantalla=p["url"])
            for p in pasos for fr in (p.get("sockets") or [])]


def quizas_json(txt):
    """Deja el cuerpo como objeto si es JSON; si no, como texto tal cual."""
    if not txt:
        return None
    try:
        return json.loads(txt)
    except (json.JSONDecodeError, TypeError):
        return txt


def cobertura_endpoints(pasos, endpoints):
    """Por cada endpoint rastreado: cuantas veces salio, en que pasos y con que status.

    Es lo que responde "el flujo si llamo a decision-engine?" de un vistazo,
    incluyendo los que NUNCA se vieron (que suele ser el hallazgo interesante).
    """
    cob = {e: {"endpoint": e, "veces": 0, "pasos": [], "statuses": [], "urls": [],
               "version_declarada": version_declarada(e), "versiones": [], "fallos": 0}
           for e in endpoints}
    for paso in pasos:
        for r in paso["requests"]:
            for e in r.get("rastreados", []):
                if e not in cob:
                    continue
                c = cob[e]
                c["veces"] += 1
                if paso["idx"] not in c["pasos"]:
                    c["pasos"].append(paso["idx"])
                if r["status"] not in c["statuses"]:
                    c["statuses"].append(r["status"])
                if r.get("fallo"):
                    c["fallos"] += 1
                if len(c["urls"]) < 5 and r["url"] not in c["urls"]:
                    c["urls"].append(r["url"])
                v = version_de(r["url"])
                if v and v not in c["versiones"]:
                    c["versiones"].append(v)
    return cob


def nota_version(c):
    """'v2 (declarado v1)' cuando la version que llego no es la esperada."""
    if not c["versiones"]:
        return ""
    visto = "/".join("v" + v for v in c["versiones"])
    esperado = c["version_declarada"]
    if esperado and esperado not in c["versiones"]:
        return "%s  <-- declarado v%s" % (visto, esperado)
    return visto


def imprimir_cobertura(cob):
    vistos = [c for c in cob.values() if c["veces"]]
    faltantes = [c for c in cob.values() if not c["veces"]]
    if not cob:
        return
    print("\n--- endpoints rastreados ---")
    for c in sorted(vistos, key=lambda x: -x["veces"]):
        malos = [s for s in c["statuses"] if not s or s >= 400]
        marca = "  <-- %s" % malos if malos else ""
        if c.get("fallos"):
            marca += "  <-- %d bloqueado(s)/sin respuesta" % c["fallos"]
        ver = nota_version(c)
        print("  %2dx  pasos %-12s %-58s %s%s"
              % (c["veces"], ",".join(str(p) for p in c["pasos"]), c["endpoint"],
                 ver, marca))
    if faltantes:
        print("  no aparecieron (%d):" % len(faltantes))
        for c in faltantes:
            print("       %s" % c["endpoint"])

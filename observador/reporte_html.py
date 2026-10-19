"""reporte.html: timeline de la corrida, pantalla y requests lado a lado.

La cabecera se arma con BLOQUES_CABECERA, en orden: un indice nuevo para el
reporte es una funcion mas en esa lista. Cada paso es una seccion (_html_paso)
y cada request una fila desplegable (_html_request).
"""
import html
import json
import os

import esquemas as esq
import sonda_check
from observador.analisis import (cobertura_endpoints, endpoint_con_error,
                                 etiqueta_fallo, es_fallo, linea_check,
                                 nota_version, total_fallos, total_requests)
from observador.config import MAX_BODY_HTML, SHOT_RESPUESTA_DEFAULT
from observador.pantallazos import (PREFIJO_RESPUESTA, etiqueta_shot,
                                    slug_disparador)
from observador.util import ahora_iso

CSS_REPORTE = """
  :root { --bg:#fff; --fg:#1a1a1a; --mut:#666; --bd:#e2e2e2; --card:#fafafa;
          --ok:#2e7d32; --err:#c62828; --acc:#CE4F3B; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#161616; --fg:#e8e8e8; --mut:#999; --bd:#333; --card:#1e1e1e;
            --ok:#81c784; --err:#ef9a9a; } }
  * { box-sizing:border-box; }
  body { margin:0; padding:24px; background:var(--bg); color:var(--fg);
         font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif; }
  header { border-bottom:3px solid var(--acc); padding-bottom:12px; margin-bottom:24px; }
  h1 { margin:0 0 4px; font-size:20px; }
  .resumen { color:var(--mut); font-size:13px; }
  .paso { display:flex; gap:20px; padding:20px 0; border-bottom:1px solid var(--bd);
          align-items:flex-start; }
  .shot { flex:0 0 300px; }
  .shot img { width:100%; border:1px solid var(--bd); border-radius:6px; }
  .info { flex:1; min-width:0; }
  .info h2 { margin:0 0 4px; font-size:16px; }
  .idx { background:var(--acc); color:#fff; padding:1px 7px; border-radius:4px;
         font-size:12px; margin-right:6px; }
  .url { margin:0 0 2px; color:var(--mut); font-size:12px; word-break:break-all; }
  .meta { margin:0 0 12px; color:var(--mut); font-size:12px; }
  .vacio { color:var(--mut); font-style:italic; }
  .req { background:var(--card); border:1px solid var(--bd); border-left:3px solid var(--ok);
         border-radius:4px; margin-bottom:6px; }
  .req.err { border-left-color:var(--err); }
  summary { cursor:pointer; padding:7px 10px; display:flex; gap:10px; align-items:center;
            font-size:12px; }
  .m { font-weight:700; min-width:52px; }
  .s { font-weight:700; min-width:34px; }
  .req.err .s { color:var(--err); }
  .req.ok .s { color:var(--ok); }
  .u { flex:1; word-break:break-all; font-family:ui-monospace,Consolas,monospace; }
  .d { color:var(--mut); white-space:nowrap; }
  .det { padding:0 12px 12px; }
  .det h5 { margin:10px 0 4px; font-size:11px; text-transform:uppercase; color:var(--mut); }
  pre { background:var(--bg); border:1px solid var(--bd); border-radius:4px; padding:8px;
        overflow-x:auto; font-size:11px; max-height:320px; margin:0; }
  .nota { color:var(--err); font-size:12px; }
  .ws { background:var(--card); border:1px solid var(--bd); border-left:3px solid var(--acc);
        border-radius:4px; margin-bottom:6px; }
  .ws summary { font-size:12px; }
  .ws .dir { font-weight:700; min-width:20px; }
  .ws .paso-st { font-weight:700; }
  .ws.fail { border-left-color:var(--err); }
  .ws.fail .paso-st { color:var(--err); }
  .ws.okk .paso-st { color:var(--ok); }
  .subt { margin:14px 0 6px; font-size:11px; text-transform:uppercase;
          color:var(--mut); letter-spacing:.4px; }
  .shot .cap { font-size:10px; color:var(--mut); margin:2px 0 0; }
  .shot img + a img { margin-top:6px; }
"""

CSS_ENDPOINTS = """
  .idx-ep { margin-bottom:24px; }
  .idx-ep h3 { font-size:14px; margin:0 0 8px; }
  .idx-ep h3 small { color:var(--mut); font-weight:400; margin-left:6px; }
  .idx-ep table { border-collapse:collapse; width:100%; font-size:12px; }
  .idx-ep td { padding:4px 8px; border-bottom:1px solid var(--bd); }
  .idx-ep .n { width:44px; text-align:right; font-weight:700; }
  .idx-ep .e { font-family:ui-monospace,Consolas,monospace; word-break:break-all; }
  .idx-ep .p, .idx-ep .st { color:var(--mut); white-space:nowrap; width:1%; }
  .idx-ep .ver { color:var(--mut); white-space:nowrap; width:1%; font-size:11px; }
  .idx-ep .ver.movida { color:var(--acc); font-weight:700; }
  .idx-ep tr.bueno .n { color:var(--ok); }
  .idx-ep tr.malo .n, .idx-ep tr.malo .st { color:var(--err); font-weight:700; }
  .idx-ep tr.ausente td { color:var(--mut); opacity:.65; }
  .tag { background:var(--acc); color:#fff; font-size:9px; font-weight:700;
         padding:1px 5px; border-radius:3px; letter-spacing:.4px; }
  .req.track { border-left-width:5px; }
  .req.track summary { background:color-mix(in srgb, var(--acc) 7%, transparent); }
  .tag.sonda { background:var(--mut); }
  .tag.fallo { background:var(--err); }
  .req.sonda { border-left:3px dashed var(--mut); }
  .req.sonda .s { color:var(--mut); }
  .nota-sonda { color:var(--mut); font-size:12px; }
  .idx-ep tr.cambio td { font-weight:700; }
  .idx-ep tr.cambio .e { color:var(--acc); }
"""


def esc(x):
    return html.escape(str(x) if x is not None else "")


def esc_cuerpo(txt):
    """El cuerpo completo vive en requests.jsonl; aqui solo un extracto.
    Si es JSON, lo formatea con indentacion; si no, lo deja como texto."""
    if not txt:
        return "(vacio)"
    # intentar parsear como JSON y formatear
    try:
        obj = json.loads(txt)
        formateado = json.dumps(obj, indent=2, ensure_ascii=False)
        txt_fmt = formateado
    except (json.JSONDecodeError, TypeError):
        txt_fmt = txt
    # truncar si es muy grande
    if len(txt_fmt) > MAX_BODY_HTML:
        return (html.escape(txt_fmt[:MAX_BODY_HTML])
                + "\n\n... [%d caracteres mas; el cuerpo completo esta en "
                  "requests.jsonl de este paso]" % (len(txt_fmt) - MAX_BODY_HTML))
    return html.escape(txt_fmt)


# --- cabecera ---------------------------------------------------------------
def _bloque_endpoints(cob, esc):
    """Indice de endpoints rastreados para la cabecera del reporte."""
    if not cob:
        return ""
    vistos = sorted([c for c in cob.values() if c["veces"]], key=lambda x: -x["veces"])
    faltan = [c for c in cob.values() if not c["veces"]]
    filas = []
    for c in vistos:
        cls = "malo" if endpoint_con_error(c) else "bueno"
        # una version distinta a la declarada no es un fallo, pero hay que verla
        esperado = c.get("version_declarada")
        movida = bool(esperado and c.get("versiones") and esperado not in c["versiones"])
        filas.append(
            '<tr class="' + cls + '">'
            '<td class="n">' + esc(c["veces"]) + '&times;</td>'
            '<td class="e">' + esc(c["endpoint"]) + '</td>'
            '<td class="ver' + (' movida' if movida else '') + '">'
            + esc(nota_version(c)) + '</td>'
            '<td class="p">paso ' + esc(", ".join(str(p) for p in c["pasos"])) + '</td>'
            '<td class="st">' + esc(", ".join(str(s) if s else "-" for s in c["statuses"]))
            + ((' &middot; ' + esc(c["fallos"]) + ' bloqueado(s)/sin respuesta')
               if c.get("fallos") else '') + '</td>'
            '</tr>')
    for c in faltan:
        filas.append(
            '<tr class="ausente">'
            '<td class="n">&mdash;</td>'
            '<td class="e">' + esc(c["endpoint"]) + '</td>'
            '<td class="p" colspan="3">no aparecio</td>'
            '</tr>')
    return ('<section class="idx-ep"><h3>Endpoints rastreados '
            '<small>' + esc(len(vistos)) + ' de ' + esc(len(cob)) + '</small></h3>'
            '<table>' + "".join(filas) + '</table></section>')


def _bloque_check(filas, esc):
    """Lo que habria respondido la retoma en cada pantalla. Se resaltan las
    filas donde cambio el estado o el paso pendiente, que es lo que se busca."""
    if not filas:
        return ""
    trs, previa = [], None
    for f in filas:
        clave = (f.get("estado"), f.get("pasoPendiente"), f.get("idCaso"))
        cls = "cambio" if previa is not None and clave != previa else ""
        previa = clave
        trs.append(
            '<tr class="' + cls + '">'
            '<td class="p">paso ' + esc("%02d" % f["paso"]) + '</td>'
            '<td class="p">' + esc(f["ts"][11:19]) + '</td>'
            '<td class="p">' + esc(f.get("motivo")) + '</td>'
            '<td class="st">' + esc(f["status"]) + '</td>'
            '<td class="e">' + esc(f.get("estado", "")) + '</td>'
            '<td class="e">' + esc(f.get("pasoPendiente", "")) + '</td>'
            '<td class="p">' + esc(("caso %s" % f["idCaso"]) if f.get("idCaso") else "")
            + '</td></tr>')
    return ('<section class="idx-ep"><h3>/request/check durante el flujo '
            '<small>lo que responderia la retoma en cada pantalla</small></h3>'
            '<table>' + "".join(trs) + '</table></section>')


def bloque_esquemas(obs):
    return esq.bloque_html(getattr(obs, "validacion", []),
                           getattr(obs, "ruta_esquemas", None), esc)


def bloque_endpoints(obs):
    return _bloque_endpoints(cobertura_endpoints(obs.pasos, obs.endpoints), esc)


def bloque_check(obs):
    return _bloque_check(linea_check(obs.pasos), esc)


# Lo que va entre el titulo y los pasos, en orden. Cada bloque recibe el
# observador (en vivo o reconstruido desde disco) y devuelve HTML, o "".
BLOQUES_CABECERA = [bloque_esquemas, bloque_endpoints, bloque_check]


# --- pasos ------------------------------------------------------------------
def _rango_disparador(nombre):
    """Ordena los pantallazos por el orden en que se declaro cada disparador.

    Alfabeticamente, modification-quota-amount le ganaba a request/offer y
    quedaba de principal una pantalla que no es la que retrata el paso.
    """
    slug = etiqueta_shot(nombre)
    patrones = [slug_disparador(x) for x in SHOT_RESPUESTA_DEFAULT.split(",")]
    return (patrones.index(slug) if slug in patrones else len(patrones), slug)


def _bloque_socket(frames, esc, esc_cuerpo):
    """Los frames del websocket del paso, con el step/stepStatus a la vista.

    Ese par es lo que dice si el flujo avanzo o se cayo, asi que se saca del
    payload y se pinta en el encabezado en vez de esconderlo en el JSON.
    """
    if not frames:
        return ""
    filas = []
    for fr in frames:
        paso_ws = est = ""
        try:
            d = json.loads(fr["payload"])
            paso_ws, est = d.get("step", ""), d.get("stepStatus", "")
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
        cls = "fail" if est.upper() in ("FAIL", "ERROR") else ("okk" if est else "")
        flecha = "&rarr;" if fr["direccion"] == "enviado" else "&larr;"
        etiqueta = (esc(paso_ws) + " " + esc(est)) if paso_ws else esc(fr["direccion"])
        filas.append(
            '<details class="ws ' + cls + '"><summary>'
            '<span class="dir">' + flecha + '</span>'
            '<span class="paso-st">' + etiqueta + '</span>'
            '<span class="d">' + esc(fr["ts"][11:19]) + '</span>'
            '</summary><div class="det"><pre>' + esc_cuerpo(fr["payload"]) + '</pre>'
            '<h5>Socket</h5><pre>' + esc(fr["url"]) + '</pre></div></details>')
    return '<p class="subt">WebSocket (' + esc(len(frames)) + ' mensajes)</p>' + "".join(filas)


def _html_request(r):
    clase = "err" if es_fallo(r) else "ok"
    nota = ("<p class='nota'>" + esc(r["nota"]) + "</p>") if r.get("nota") else ""
    tag = '<span class="tag">API</span>' if r.get("rastreados") else ''
    if r.get("rastreados"):
        clase += " track"
    if r.get("fallo"):
        tag += '<span class="tag fallo">' + esc(etiqueta_fallo(r)) + '</span>'
    if r.get("sonda"):
        clase = "sonda"
        tag = '<span class="tag sonda">SONDA</span>'
        nota = ("<p class='nota-sonda'>" + esc(sonda_check.linea(r.get("check") or {}))
                + " &middot; consultado por el observador (" + esc(r.get("motivo"))
                + "); el front lo llama desde su servidor, no desde el navegador.</p>")
    cuerpo_resp = esc_cuerpo(r["response_body"])
    if r.get("sonda") and r["response_body"] is None:
        cuerpo_resp = "null"   # un 404 sin caso: no hay cuerpo que mostrar
    return (
        '<details class="req ' + clase + '">'
        '<summary>' + tag +
        '<span class="m">' + esc(r["metodo"]) + '</span>'
        '<span class="s">' + (esc(r["status"]) if r["status"] else "&mdash;") + '</span>'
        '<span class="u">' + esc(r["url"]) + '</span>'
        '<span class="d">' + esc(r["duracion_ms"]) + ' ms</span>'
        '</summary>'
        '<div class="det">'
        '<h5>Request body</h5><pre>' + esc_cuerpo(r["request_body"]) + '</pre>'
        '<h5>Response body</h5><pre>' + cuerpo_resp + '</pre>'
        + nota +
        '</div></details>'
    )


def _imagenes_paso(paso):
    """[(src, leyenda)] del paso. El pantallazo disparado por la respuesta del
    servicio manda (es el estado real de la pantalla con datos), y el de la
    navegacion queda abajo como referencia."""
    base = "%02d_%s/" % (paso["idx"], paso["slug"])
    if os.path.isdir(paso["dir"]):
        onresp = sorted((f for f in os.listdir(paso["dir"])
                         if f.startswith(PREFIJO_RESPUESTA) and f.endswith(".png")),
                        key=_rango_disparador)
    else:
        onresp = []
    imgs = [(base + f, "al responder " + etiqueta_shot(f).replace("-", "/"))
            for f in onresp]
    if os.path.exists(os.path.join(paso["dir"], "screenshot.png")):
        imgs.append((base + "screenshot.png", "al entrar a la pantalla"))
    if os.path.exists(os.path.join(paso["dir"], "screenshot_2.png")):
        imgs.append((base + "screenshot_2.png", "pantallazo extra (mas tarde)"))
    return imgs


def _html_paso(paso, multi):
    reqs = [_html_request(r) for r in paso["requests"]]
    imgs = _imagenes_paso(paso)
    shot = esc(imgs[0][0]) if imgs else ""
    shot2 = "".join(
        '<a href="' + esc(src_) + '" target="_blank">'
        '<img src="' + esc(src_) + '" alt="' + esc(cap) + '"></a>'
        '<p class="cap">' + esc(cap) + '</p>'
        for src_, cap in imgs[1:])
    cuerpo = "".join(reqs) or '<p class="vacio">Sin requests al backend en este paso.</p>'
    cuerpo += _bloque_socket(paso.get("sockets") or [], esc, esc_cuerpo)
    return (
        '<section class="paso">'
        '<div class="shot">'
        + (('<a href="' + shot + '" target="_blank">'
            '<img src="' + shot + '" alt="paso ' + esc(paso["idx"]) + '"></a>'
            '<p class="cap">' + esc(imgs[0][1]) + '</p>') if shot else '')
        + shot2 + '</div>'
        '<div class="info">'
        '<h2><span class="idx">' + ("%02d" % paso["idx"]) + '</span> '
        + esc(paso["titulo"] or paso["slug"]) + '</h2>'
        '<p class="url">' + esc(paso["url"]) + '</p>'
        '<p class="meta">' + esc(len(paso["requests"])) + ' request(s) &middot; '
        + ('pestana ' + esc(paso.get("pestana", 0)) + ' &middot; ' if multi else '')
        + esc(paso["ts"]) + '</p>'
        + cuerpo +
        '</div></section>'
    )


def escribir_reporte(obs, flujo, ruta):
    # la sonda no es trafico del front: ni se cuenta como capturado ni su 404
    # (sin caso abierto) como fallo
    total = total_requests(obs.pasos)
    fallos = total_fallos(obs.pasos)
    n_sonda = len(linea_check(obs.pasos))
    multi = len({p.get("pestana", 0) for p in obs.pasos}) > 1

    doc = (
        '<!doctype html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Evidencia - ' + esc(flujo) + '</title>'
        '<style>' + CSS_REPORTE + CSS_ENDPOINTS + esq.CSS + '</style></head><body>'
        '<header><h1>Evidencia de flujo &mdash; ' + esc(flujo) + '</h1>'
        '<p class="resumen">' + esc(len(obs.pasos)) + ' pasos &middot; '
        + esc(total) + ' requests capturados &middot; '
        + esc(fallos) + ' con error (status &ge; 400, CORS o sin respuesta) &middot; '
        + ((esc(n_sonda) + ' consultas a /request/check &middot; ') if n_sonda else '')
        + 'generado ' + esc(ahora_iso()) + '</p>'
        '</header>'
        + "".join(bloque(obs) for bloque in BLOQUES_CABECERA)
        + "".join(_html_paso(paso, multi) for paso in obs.pasos) + '</body></html>'
    )
    with open(ruta, "w", encoding="utf-8") as f:
        f.write(doc)

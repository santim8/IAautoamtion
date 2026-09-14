#!/usr/bin/env python3
"""
Validador de eventos de analitica (dataLayer) contra los specs modelo_de_datos[*].

Estrategia:
  1. EXTRAER  : lee un reporte ExtentReports (.html), saca los bloques <pre>{...}</pre>,
                y filtra a los eventos de analitica (event == "interactivo" + eventName).
  2. ENRUTAR  : mapea cada evento a su entrada de spec (por eventName / seccion / etc.).
  3. VALIDAR  : compara campo a campo infiriendo el tipo desde la convencion del spec:
                  {{x}}            -> dinamico  (solo exige presencia / regex si es template)
                  modal_{{[a|b]}}  -> template  (regex: prefijo fijo + enum)
                  [a|b|c]          -> enum      (valor debe estar en la lista)
                  "texto fijo"     -> constante (match exacto)
                campos sensibles (numero_documento, email, celular, nit) -> Base64 valido.
  4. REPORTAR : PASS/FAIL por evento + resumen. Exit code != 0 si hay fallos (util en CI).

Uso:
  python validar_eventos.py [ruta_reporte.html] [--specs DIR] [--json salida.json] [--strict]

Sin argumentos usa el reporte por defecto y la carpeta del script como specs.
"""
import re, json, html, sys, base64, glob, os, argparse

DEFAULT_REPORT = r"C:/Users/santiago.correa03/IdeaProjects/colsubsidioFramework/target/Index.html"
SENSIBLES = {"numero_documento", "email", "celular", "nit"}
IGNORAR_EXTRA = {"utm_source", "utm_medium", "utm_campaign"}
META = {"evento", "variante"}  # claves del spec que no son campos del payload


# ----------------------------- 1. EXTRACCION -----------------------------
def extraer_eventos(ruta_html):
    raw = open(ruta_html, encoding="utf-8").read()
    bloques = re.findall(r"<pre>(\{.*?\})</pre>", raw, re.DOTALL)
    eventos = []
    for i, b in enumerate(bloques, 1):
        try:
            obj = json.loads(html.unescape(b))
        except json.JSONDecodeError:
            continue
        if obj.get("event") == "interactivo" and obj.get("eventName"):
            eventos.append((i, obj))
    return eventos


# ------------------------- 2. CARGA DE SPECS + ROUTER --------------------
def cargar_specs(carpeta):
    specs = {}
    for f in glob.glob(os.path.join(carpeta, "modelo_de_datos[[]*")):
        clave = re.search(r"\[(.+?)\]", os.path.basename(f)).group(1)
        specs[clave] = json.load(open(f, encoding="utf-8"))
    return specs


def _por(entradas, **criterios):
    for e in entradas:
        if all(e.get(k) == v for k, v in criterios.items()):
            return e
    return None


def _por_seccion(entradas, seccion):
    return _por(entradas, seccion=seccion)


def _es_dinamico(valor):
    """Un campo del spec que no sirve para discriminar: plantilla o enum."""
    if not isinstance(valor, str):
        return True
    return "{{" in valor or bool(re.match(r"^\[.+\]$", valor.strip()))


def _puntaje(ev, entrada):
    """Cuantos literales del spec coinciden con el evento; None si contradice.

    Solo cuentan los campos con valor fijo: son los unicos que identifican de
    que evento se trata. Un {{campo}} o un [a|b] encaja con cualquier cosa.
    """
    puntos = 0
    for k, v in entrada.items():
        if k in META or _es_dinamico(v):
            continue
        if k not in ev or str(ev[k]) != str(v):
            return None
        puntos += 1
    return puntos


def enrutar_por_datos(ev, specs):
    """Busca en TODOS los specs la entrada cuyos literales case mejor.

    Es lo que hace que agregar o editar una entrada en los JSON alcance para
    que un evento nuevo se valide, sin tocar el codigo del router.
    """
    mejor, mejor_pts = (None, None), 0
    for nombre, entradas in specs.items():
        if not isinstance(entradas, list):
            entradas = [entradas]
        for entrada in entradas:
            if not isinstance(entrada, dict):
                continue
            pts = _puntaje(ev, entrada)
            if pts is not None and pts > mejor_pts:
                mejor, mejor_pts = (nombre, entrada), pts
    return mejor


def enrutar(ev, specs):
    """Devuelve (nombre_spec, entrada_spec) o (None, None) si no matchea."""
    en = ev.get("eventName")
    sec = ev.get("seccion", "") or ""
    variante = "novedad" if "tipo_novedad" in ev and "tipo_campana" not in ev else "campaña"

    if en == "login" and "validaciones" in specs:
        return "validaciones", _por_seccion(specs["validaciones"], "login")
    if en == "validaciones_caja" and "validaciones" in specs:
        return "validaciones", _por_seccion(specs["validaciones"], sec)
    if en == "virtual_page" and "modales" in specs:
        # Solo los modales; el virtual_page de una pantalla normal (login,
        # onboarding) no tiene nada que ver con Solicitud Cupo 1B y forzarlo
        # ahi producia fallos inventados.
        texto = "%s %s" % (ev.get("title", ""), ev.get("url", ""))
        if "modal_" in texto:
            return "modales", _por(specs["modales"], eventName="virtual_page",
                                   variante=variante)
    if en == "cupo_credito":
        if sec.startswith("modal_") and "modales" in specs:
            return "modales", _por(specs["modales"], eventName="cupo_credito", variante=variante)
        if "numero_paso" in ev and "personal_information" in specs:
            return "personal_information", specs["personal_information"][0]  # 2A y 2B misma forma
        if sec.lower().startswith("politica") and "politicas" in specs:
            ents = specs["politicas"]
            entrada = _por(ents, evento="Políticas 1A") if "label" in ev else _por(ents, evento="Políticas 1B")
            return "politicas", (entrada or ents[0])
    # Nada casó a mano: que decidan los JSON.
    return enrutar_por_datos(ev, specs)


# ----------------------------- 3. VALIDACION -----------------------------
def _template_a_regex(t):
    partes = re.split(r"(\{\{.*?\}\})", t)
    out = ""
    for p in partes:
        if p.startswith("{{") and p.endswith("}}"):
            inner = p[2:-2].strip()
            m = re.match(r"^\[(.+)\]$", inner)
            if m:
                opts = [re.escape(o.strip()) for o in re.split(r"\|+", m.group(1))]
                out += "(?:" + "|".join(opts) + ")"
            else:
                out += ".+"
        else:
            out += re.escape(p)
    return "^" + out + "$"


def _tipo_campo(spec_val):
    if isinstance(spec_val, str):
        if "{{" in spec_val:
            return ("template", _template_a_regex(spec_val))
        m = re.match(r"^\[(.+)\]$", spec_val.strip())
        if m and "|" in m.group(1):
            return ("enum", [o.strip() for o in re.split(r"\|+", m.group(1))])
    return ("constante", spec_val)


def _b64_ok(v):
    try:
        d = base64.b64decode(v).decode("utf-8")
        return base64.b64encode(d.encode()).decode() == v
    except Exception:
        return False


def validar(ev, spec, strict=False):
    errores, avisos = [], []
    campos_spec = {k: v for k, v in spec.items() if k not in META}

    for campo, spec_val in campos_spec.items():
        if campo not in ev:
            errores.append(f"falta campo requerido '{campo}'")
            continue
        val = ev[campo]
        tipo, ref = _tipo_campo(spec_val)
        if tipo == "constante" and val != ref:
            errores.append(f"'{campo}': esperado {ref!r}, llego {val!r}")
        elif tipo == "enum" and val not in ref:
            errores.append(f"'{campo}': {val!r} no esta en {ref}")
        elif tipo == "template" and not re.match(ref, str(val)):
            errores.append(f"'{campo}': {val!r} no cumple patron {spec_val!r}")
        elif tipo == "dynamic" and (val is None or val == ""):
            avisos.append(f"'{campo}' vacio")
        if campo in SENSIBLES and not _b64_ok(str(val)):
            errores.append(f"'{campo}': no es Base64 valido ({val!r})")

    extras = [k for k in ev if k not in campos_spec and k not in IGNORAR_EXTRA]
    for k in extras:
        (errores if strict else avisos).append(f"campo extra '{k}' no esta en el spec")

    return errores, avisos


# ----------------------------- 4. REPORTE --------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("reporte", nargs="?", default=DEFAULT_REPORT)
    ap.add_argument("--specs", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--json", default=None)
    ap.add_argument("--strict", action="store_true", help="campos extra cuentan como error")
    args = ap.parse_args()

    specs = cargar_specs(args.specs)
    eventos = extraer_eventos(args.reporte)
    print(f"Reporte: {args.reporte}")
    print(f"Specs cargados: {sorted(specs)}")
    print(f"Eventos de analitica detectados: {len(eventos)}\n")

    resultados, n_pass, n_fail, n_sin_ruta = [], 0, 0, 0
    for idx, ev in eventos:
        nombre_spec, entrada = enrutar(ev, specs)
        etiqueta = f"#{idx} {ev.get('eventName')} / {ev.get('seccion','')}".strip()
        if entrada is None:
            n_sin_ruta += 1
            print(f"[SIN RUTA] {etiqueta}  -> ningun spec matchea")
            resultados.append({"idx": idx, "estado": "SIN_RUTA", "evento": etiqueta})
            continue
        errores, avisos = validar(ev, entrada, strict=args.strict)
        estado = "PASS" if not errores else "FAIL"
        n_pass += estado == "PASS"
        n_fail += estado == "FAIL"
        print(f"[{estado}] {etiqueta}  -> {nombre_spec} :: {entrada.get('evento')}")
        for e in errores:
            print(f"        ERROR  {e}")
        for a in avisos:
            print(f"        aviso  {a}")
        resultados.append({"idx": idx, "estado": estado, "evento": etiqueta,
                           "spec": f"{nombre_spec}::{entrada.get('evento')}",
                           "errores": errores, "avisos": avisos})

    print(f"\nRESUMEN  PASS={n_pass}  FAIL={n_fail}  SIN_RUTA={n_sin_ruta}  total={len(eventos)}")
    if args.json:
        json.dump(resultados, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"Detalle escrito en {args.json}")
    sys.exit(1 if n_fail else 0)


if __name__ == "__main__":
    main()

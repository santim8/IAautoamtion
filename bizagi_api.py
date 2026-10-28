#!/usr/bin/env python3
"""Bizagi de pruebas por su API REST, sin navegador y sin llenar el login.

    python bizagi_api.py login [--cookie "a=b; c=d"]   abre sesion y la guarda en ~/.panel_qa
    python bizagi_api.py estado                       dice si la sesion guardada sigue viva
    python bizagi_api.py solicitudes [CE] <documento> GCR_Solicitudes - Promotor por documento
    python bizagi_api.py json <idCaso>                GCR_Solicitudes - Analista operativo (fila en JSON)
    python bizagi_api.py caso <idCaso>                buscador superior: proceso, actividad, fechas
    python bizagi_api.py admin <idCaso>               Administracion de procesos (casos en curso)
    python bizagi_api.py consultas                    consultas de entidad que ve el usuario
    python bizagi_api.py cancelar <idCaso> --confirmar   cancela el caso (Rest/Cases/Abort)
    python bizagi_api.py navegador                    abre Chromium ya logueado con la sesion

Es lo mismo que hacen bizagi_cancel_case.py, bizagi_consultar_caso.py y
bizagi_consultar_json.py, pero pegandole a los servicios que llama el portal
en vez de hacer clic: una consulta tarda un par de segundos y no depende de
selectores.

La sesion sale de POST /Api/Authentication/User con BIZAGI_USER y
BIZAGI_PASSWORD (las mismas variables de entorno de los otros scripts), o de
una cookie .BZAUTH copiada del navegador con `login --cookie`. Bizagi la
vence a los 20 minutos sin uso; si se vencio y hay credenciales en el entorno,
el script la renueva solo. Todo lo que no es `cancelar` es lectura.

Para otros scripts de Playwright: `with sync_playwright() as p:
browser, ctx = abrir(p)` da un contexto que entra al portal sin formulario.
"""
import argparse
import json
import os
import sys
import time
import unicodedata
from datetime import datetime
from http.cookiejar import Cookie, CookieJar
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener

from rutas import DIR_DATOS

SITIO = "https://test-procesosdigitales-colsubsidio.bizagi.com"
HOST = SITIO.split("//", 1)[1]
DOMINIO = "colsubsidio"
SESION = os.path.join(DIR_DATOS, "bizagi_sesion.json")

CONSULTA_PROMOTOR = "GCR_Solicitudes - Promotor"
CONSULTA_ANALISTA = "GCR_Solicitudes - Analista operativo"
TIPO_DOCUMENTO = {"CC": "Cédula de Ciudadanía", "CE": "Cédula de Extranjería"}

# Formato de fecha con que Bizagi devuelve las filas de las consultas.
FORMATO_FECHA = "%m/%d/%Y %H:%M:%S"


class SesionVencida(Exception):
    pass


def _sin_tildes(texto):
    texto = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in texto if not unicodedata.combining(c)).lower().strip()


def _decodificar(crudo):
    """Bizagi manda algunas respuestas en cp1252 aunque diga utf-8 (las
    tildes de los nombres de consulta salen rotas si se lee a ciegas)."""
    try:
        return crudo.decode("utf-8")
    except UnicodeDecodeError:
        return crudo.decode("cp1252", errors="replace")


class Bizagi:
    def __init__(self):
        self.cookies = CookieJar()
        self.http = build_opener(HTTPCookieProcessor(self.cookies))
        self.xsrf = ""
        self.usuario = None
        self._cargar()

    # --- sesion -----------------------------------------------------------

    def _cargar(self):
        if not os.path.exists(SESION):
            return
        with open(SESION, encoding="utf-8") as f:
            datos = json.load(f)
        for c in datos.get("cookies", []):
            self._poner_cookie(c["name"], c["value"], c.get("path", "/"))
        self.xsrf = datos.get("xsrf", "")
        self.usuario = datos.get("usuario")

    def _guardar(self):
        os.makedirs(DIR_DATOS, exist_ok=True)
        datos = {"usuario": self.usuario, "xsrf": self.xsrf,
                 "guardada": datetime.now().isoformat(timespec="seconds"),
                 "cookies": self.cookies_playwright()}
        with open(SESION, "w", encoding="utf-8") as f:
            json.dump(datos, f, ensure_ascii=False, indent=1)

    def _poner_cookie(self, nombre, valor, ruta="/"):
        self.cookies.set_cookie(Cookie(
            0, nombre, valor, None, False, HOST, False, False, ruta, True,
            True, None, False, None, None, {}))

    def cookies_playwright(self):
        return [{"name": c.name, "value": c.value, "domain": HOST,
                 "path": c.path or "/", "secure": True} for c in self.cookies]

    def login(self):
        usuario = os.environ.get("BIZAGI_USER")
        clave = os.environ.get("BIZAGI_PASSWORD")
        if not usuario or not clave:
            raise SystemExit(
                "Faltan BIZAGI_USER / BIZAGI_PASSWORD en el entorno.\n"
                "Configuralas una vez en PowerShell (setx) o entra con:\n"
                '  python bizagi_api.py login --cookie ".BZAUTH=..."')
        self.cookies.clear()
        self.xsrf = ""
        # El GET deja las cookies de afinidad del Application Gateway: sin
        # ellas el login puede caer en otro nodo que no conoce la sesion.
        self._pedir("GET", "/")
        _, r = self._pedir("POST", "/Api/Authentication/User", datos={
            "user": usuario, "password": clave, "domain": DOMINIO,
            "loginOption": "alwaysAsk", "type": "", "oAuth2InternalState": ""})
        if not isinstance(r, dict) or r.get("status") != "SUCCESS":
            detalle = r.get("message") if isinstance(r, dict) else str(r)[:200]
            raise SystemExit("Bizagi no acepto el login: %s" % detalle)
        if not self._leer_xsrf():
            raise SystemExit("Bizagi acepto el login pero no entrego el token XSRF.")
        self._guardar()

    def login_cookie(self, cadena):
        """Sesion a partir del valor del header Cookie del navegador (lo que
        trae `-b` en un curl copiado de DevTools); basta con .BZAUTH."""
        self.cookies.clear()
        for par in cadena.split(";"):
            if "=" in par:
                nombre, valor = par.strip().split("=", 1)
                self._poner_cookie(nombre, valor)
        if not self._leer_xsrf():
            raise SystemExit("Con esa cookie Bizagi no reconoce ninguna sesion "
                             "(falta .BZAUTH o ya se vencio).")
        self._guardar()

    def _leer_xsrf(self):
        """El token anti-CSRF que el portal manda en X-BZXSRF-TOKEN; sin el,
        las consultas responden 401. Lo trae CurrentUserGuid (el portal lo
        lee de ReadUserCookies, pero ahi solo sale si el login se hizo con
        'recordar clave')."""
        try:
            _, r = self._pedir("GET", "/Rest/Users/CurrentUserGuid")
        except SesionVencida:
            return False
        if not isinstance(r, dict) or not r.get("XSRFToken"):
            return False
        self.xsrf = r["XSRFToken"]
        self.usuario = r.get("user")
        return True

    def viva(self):
        try:
            _, r = self._pedir("GET", "/Rest/Users/CurrentUserGuid")
        except SesionVencida:
            return False
        return isinstance(r, dict) and bool(r.get("userName"))

    def asegurar(self):
        if not self.viva():
            self.login()

    # --- HTTP -------------------------------------------------------------

    def _pedir(self, metodo, ruta, params=None, datos=None):
        url = SITIO + ruta
        if params:
            url += "?" + urlencode(params)
        cuerpo = urlencode(datos).encode("utf-8") if datos is not None else None
        req = Request(url, data=cuerpo, method=metodo, headers={
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
            "X-BZXSRF-TOKEN": self.xsrf,
            "Origin": SITIO, "Referer": SITIO + "/",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 Chrome/141.0 Safari/537.36"})
        try:
            with self.http.open(req, timeout=60) as resp:
                estado, texto = resp.status, _decodificar(resp.read())
        except HTTPError as e:
            estado, texto = e.code, _decodificar(e.read())
        if estado in (401, 403):
            raise SesionVencida("%s %s -> %s" % (metodo, ruta, estado))
        if estado >= 400:
            raise RuntimeError("%s %s -> HTTP %s: %s" % (metodo, ruta, estado, texto[:300]))
        try:
            return estado, json.loads(texto)
        except ValueError:
            return estado, texto

    def pedir(self, metodo, ruta, params=None, datos=None):
        """Como _pedir, pero si la sesion se vencio en el camino la renueva y
        reintenta una vez."""
        try:
            return self._pedir(metodo, ruta, params, datos)[1]
        except SesionVencida:
            self.login()
            return self._pedir(metodo, ruta, params, datos)[1]

    # --- consultas de entidad (menu Consultas > Otras entidades) -----------

    def consultas(self):
        """{nombre: {"form", "entidad"}} de las consultas con formulario."""
        arbol = self.pedir("GET", "/Rest/Queries/Definitions")
        encontradas = {}

        def recorrer(nodos):
            for n in nodos:
                if n.get("guidForm", "").strip("0-"):
                    encontradas[n["queryDisplayName"].strip()] = {
                        "form": n["guidForm"], "entidad": n["guidContext"],
                        "tipo": n.get("queryType")}
                recorrer(n.get("nodes", []))
        recorrer(arbol.get("query", []))
        return encontradas

    def _controles(self, guid_form):
        forma = self.pedir("POST", "/Rest/Handlers/Render", datos={
            "h_action": "QUERYFORM", "h_contexttype": "entity", "h_idForm": guid_form})
        controles = []

        def recorrer(nodo):
            if isinstance(nodo, dict):
                if "render" in nodo:
                    controles.append(nodo["render"]["properties"])
                for v in nodo.values():
                    recorrer(v)
            elif isinstance(nodo, list):
                for v in nodo:
                    recorrer(v)
        recorrer(forma)
        return controles

    @staticmethod
    def _parametro(control, filtros):
        """Arma cada parametro como lo arma el portal con 'Incluir todo'
        marcado: los controles visibles van incluidos en el resultado, los
        ocultos con su valor por defecto (p. ej. Tipo Tramite = Gestion de
        credito) filtran sin salir en la tabla."""
        rango = (control.get("rangeQuery") or "").upper()
        tipo_busqueda = (control.get("typeSearch") or "").upper()
        p = {"value": [] if control["type"] == "queryMultiSelect" else None,
             "included": control.get("visible", True) is not False,
             "xpath": control["xpath"],
             "searchType": rango if rango in ("FROM", "TO") else (tipo_busqueda or "NONE"),
             "orderType": "NONE", "renderId": control["id"], "displayHeader": None}
        if control.get("displayXpath"):
            p["displayXpath"] = control["displayXpath"]
        if control.get("visible") is False and control.get("defaultValue"):
            p["value"] = control["defaultValue"][0]["id"]
            p["included"] = False

        campo = control["xpath"].rsplit(".", 1)[-1]
        if campo in filtros:
            valor = filtros[campo]
            # En los combos se puede mandar el texto que se ve en pantalla.
            if control.get("data") and not isinstance(valor, int):
                opcion = next((o for o in control["data"]
                               if _sin_tildes(o["value"]) == _sin_tildes(valor)), None)
                if opcion is None:
                    raise SystemExit("'%s' no es una opcion de %s: %s" % (
                        valor, control.get("displayName"),
                        ", ".join(o["value"] for o in control["data"])))
                valor = opcion["id"]
            p["value"] = valor
        return p

    def buscar(self, nombre_consulta, filtros, filas=100):
        """Corre una consulta de entidad y devuelve las filas como dicts.

        `filtros` va por el ultimo segmento del xpath del control
        ({"sNumeroIdentificacion": "123", "kpT_Identificacion": "Cedula de
        Ciudadania"}). Las llaves de cada fila son el ultimo segmento del
        xpath de la columna, igual que en bizagi_consultar_json.py. Cuando
        varias columnas terminan igual (el estado y la campana son las dos
        'sDescripcion') llevan tambien el segmento padre, kpEstado.sDescripcion,
        en vez de pisarse como pasa en la tabla del portal.
        """
        consultas = self.consultas()
        if nombre_consulta not in consultas:
            raise SystemExit("El usuario no ve la consulta '%s'." % nombre_consulta)
        consulta = consultas[nombre_consulta]
        controles = self._controles(consulta["form"])
        conocidos = {c["xpath"].rsplit(".", 1)[-1] for c in controles}
        sobran = set(filtros) - conocidos
        if sobran:
            raise SystemExit("La consulta no tiene los campos: %s" % ", ".join(sorted(sobran)))
        r = self.pedir("POST", "/Rest/Queries/Search", datos={
            "queryFormGuid": consulta["form"], "numberOfRows": filas, "pageNumber": 1,
            "entityGuid": consulta["entidad"], "type": "ENTITIES",
            "includeAllUsers": "false", "onlyLocalResults": "true",
            "parameters": json.dumps([self._parametro(c, filtros) for c in controles],
                                     ensure_ascii=False)})
        rutas = [(h.get("xpath") or h.get("fieldName")).split(".")
                 for h in r.get("header", [])]
        cortas = [ruta[-1] for ruta in rutas]
        llaves = []
        for ruta in rutas:
            llave = ruta[-1] if cortas.count(ruta[-1]) == 1 else ".".join(ruta[-2:])
            base, n = llave, 2
            while llave in llaves:
                llave = "%s_%d" % (base, n)
                n += 1
            llaves.append(llave)
        return [dict(zip(llaves, fila)) for fila in r.get("rows", [])]

    def solicitudes(self, tipo_documento, numero):
        """Solicitudes del documento en GCR_Solicitudes - Promotor, la mas
        reciente primero. El filtro de Bizagi es aproximado (LIKE), asi que
        se dejan solo las del numero exacto."""
        filas = self.buscar(CONSULTA_PROMOTOR, {
            "kpT_Identificacion": TIPO_DOCUMENTO[tipo_documento],
            "sNumeroIdentificacion": numero})
        filas = [f for f in filas if str(f.get("sNumeroIdentificacion", "")).strip() == numero]
        return sorted(filas, key=lambda f: _fecha(f.get("dFechaCreacion")), reverse=True)

    def registro(self, id_caso):
        """La fila del caso en GCR_Solicitudes - Analista operativo (lo mismo
        que imprime bizagi_consultar_json.py)."""
        filas = self.buscar(CONSULTA_ANALISTA, {"sNumeroCaso": str(id_caso)})
        return next((f for f in filas if str(f.get("sNumeroCaso")) == str(id_caso)), None)

    # --- casos (buscador superior y Administracion de procesos) ----------

    def caso(self, id_caso):
        """Lo que muestra el buscador superior (#menuQuery) para el numero."""
        r = self.pedir("GET", "/Rest/Processes/CustomizedColumnsData", params={
            "pageSize": 10, "page": 1, "orderFieldName": "", "orderType": 0,
            "order": "", "taskState": "all", "radNumber": id_caso})
        datos = r.get("cases", {})
        titulos = [c["displayName"] for c in datos.get("columnTitle", [])]
        salida = []
        for fila in datos.get("rows", []):
            item = {"idCase": fila.get("id"), "isAborted": fila.get("isAborted"),
                    "taskState": fila.get("taskState")}
            for titulo, valor in zip(titulos, fila.get("fields", [])):
                if isinstance(valor, dict) and "workitems" in valor:
                    valor = [w.get("TaskName") for w in valor["workitems"] if w.get("TaskName")]
                elif isinstance(valor, dict):
                    valor = next(iter(valor.values()), None)
                item[titulo] = valor
            salida.append(item)
        return salida

    def casos_admin(self, id_caso, estado="Running"):
        """Busqueda de Administracion de procesos > Casos. Solo lista casos en
        curso (Running): uno cerrado o ya cancelado no sale, que es lo que el
        script de cancelar reporta como NO ENCONTRADO. Cada fila trae el
        idCase interno, que es el que se cancela: un mismo numero de caso
        agrupa el proceso principal y sus subprocesos, cada uno con el suyo."""
        r = self.pedir("GET", "/Rest/Queries/SearchCases", params={
            "h_action": "getCases", "I_ProcessState": estado, "h_idApp": "",
            "I_Users": "ALL", "eventAsTask": "true", "orderType": 1, "order": "",
            "orderField": "", "group": "", "I_radNumber": id_caso, "I_idWFClass": "",
            "I_USERNAME": "", "I_USERFULLNAME": "", "I_USERPOSITION": "",
            "I_From__CreationDate": "", "I_To__CreationDate": "", "h_idWFClassAuth": "",
            "I_idCategory": "", "I_idApplication": "", "PageSize": 10, "Page": 1})
        filas = r.get("rows", [])
        if id_caso:
            filas = [f for f in filas if str(f.get("radNumber")) == str(id_caso)]
        return [{"idCase": f.get("idCase"), "radNumber": f.get("radNumber"),
                 "subproceso": f.get("isSubprocess"),
                 "proceso": (f.get("data") or [None, None])[1],
                 "actividades": [{"actividad": t.get("taskName"),
                                  "asignado": t.get("assigneeFullName")}
                                 for t in ((f.get("data") or [])[2:3] or [[]])[0]
                                 if isinstance(t, dict)]}
                for f in filas]

    def cancelar(self, id_case, motivo=""):
        """Lo que hace el boton Cancelar de Administracion de procesos con la
        casilla del caso marcada (admin.desktop: invalidateCases). Recibe el
        idCase interno de casos_admin, no el numero que se ve en pantalla."""
        return self.pedir("POST", "/Rest/Cases/Abort", datos={
            "action": "abort", "reason": motivo,
            "cases": json.dumps({"cases": [{"idCase": int(id_case)}]})})


def _fecha(texto):
    try:
        return datetime.strptime(texto or "", FORMATO_FECHA)
    except ValueError:
        return datetime.min


def abrir(p, headless=True):
    """Navegador y contexto de Playwright que entran al portal ya logueados
    (las cookies de la sesion van inyectadas, no se toca el formulario)."""
    bz = Bizagi()
    bz.asegurar()
    browser = p.chromium.launch(headless=headless)
    context = browser.new_context(viewport={"width": 1920, "height": 1080})
    context.add_cookies(bz.cookies_playwright())
    return browser, context


def _imprimir(titulo, datos):
    print("\n=== %s ===" % titulo)
    print(json.dumps(datos, ensure_ascii=False, indent=2))
    print("=== FIN ===\n")


def _parse_documento(tokens):
    tokens = [t for a in tokens for t in a.replace("-", " ").split() if t]
    if len(tokens) == 1:
        return "CC", tokens[0]
    return ("CE" if tokens[0].upper() == "CE" else "CC"), tokens[1]


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("login")
    s.add_argument("--cookie", help="header Cookie del navegador con .BZAUTH")
    sub.add_parser("estado")
    s = sub.add_parser("solicitudes")
    s.add_argument("documento", nargs="+", help="[CE] numero")
    for nombre in ("json", "caso", "admin"):
        sub.add_parser(nombre).add_argument("id_caso")
    sub.add_parser("consultas")
    s = sub.add_parser("cancelar")
    s.add_argument("id_caso")
    s.add_argument("--motivo", default="")
    s.add_argument("--confirmar", action="store_true",
                   help="sin esto solo dice que caso cancelaria")
    sub.add_parser("navegador")
    a = ap.parse_args()

    bz = Bizagi()
    if a.cmd == "login":
        bz.login_cookie(a.cookie) if a.cookie else bz.login()
        print("Sesion abierta como %s, guardada en %s" % (bz.usuario, SESION))
        return
    if a.cmd == "estado":
        if not os.path.exists(SESION):
            print("No hay sesion guardada. Corre: python bizagi_api.py login")
        elif bz.viva():
            print("Sesion viva (%s)" % bz.usuario)
        else:
            print("Sesion vencida; la proxima consulta la renueva sola si "
                  "BIZAGI_USER/BIZAGI_PASSWORD estan en el entorno.")
        return

    inicio = time.time()
    bz.asegurar()
    if a.cmd == "solicitudes":
        tipo, numero = _parse_documento(a.documento)
        filas = bz.solicitudes(tipo, numero)
        columnas = {"caso": "sNumeroCaso", "creado": "dFechaCreacion",
                    "canal": "sNombreTipoSolicitud", "producto": "sTipoProducto",
                    "estado": "kpEstado.sDescripcion",
                    "campana": "kpCampania.sDescripcion"}
        resumen = [{k: f.get(v) for k, v in columnas.items()} for f in filas]
        _imprimir("SOLICITUDES %s %s (%d)" % (tipo, numero, len(filas)), resumen)
        if filas:
            print("Ultima solicitud: %s" % filas[0]["sNumeroCaso"])
        else:
            print("El documento %s no tiene solicitudes en Bizagi." % numero)
    elif a.cmd == "json":
        fila = bz.registro(a.id_caso)
        if fila:
            _imprimir("JSON", fila)
        else:
            print("No se encontraron registros para el caso %s" % a.id_caso)
    elif a.cmd == "caso":
        _imprimir("CASO %s" % a.id_caso, bz.caso(a.id_caso) or "sin resultados")
    elif a.cmd == "admin":
        filas = bz.casos_admin(a.id_caso)
        _imprimir("ADMINISTRACION DE PROCESOS %s" % a.id_caso, filas)
        print("En curso, se puede cancelar." if filas else
              "No aparece entre los casos en curso: no hay nada que cancelar.")
    elif a.cmd == "consultas":
        _imprimir("CONSULTAS", sorted(bz.consultas()))
    elif a.cmd == "cancelar":
        principal = next((f for f in bz.casos_admin(a.id_caso)
                          if not f["subproceso"]), None)
        if principal is None:
            print("[CASO NO ENCONTRADO] %s no esta en curso en Administracion "
                  "de procesos; no se cancelo nada." % a.id_caso)
            return
        if not a.confirmar:
            _imprimir("SE CANCELARIA", principal)
            print("El caso %s esta en curso. Para cancelarlo de verdad agrega "
                  "--confirmar." % a.id_caso)
            return
        _imprimir("CANCELAR %s" % a.id_caso, bz.cancelar(principal["idCase"], a.motivo))
        sigue = bz.casos_admin(a.id_caso)
        print("[CASO CANCELADO] %s" % a.id_caso if not sigue else
              "[CANCELACION FALLIDA] %s sigue en curso" % a.id_caso)
    elif a.cmd == "navegador":
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser, ctx = abrir(p, headless=False)
            page = ctx.new_page()
            page.goto(SITIO + "/#", wait_until="load")
            print("Bizagi abierto con la sesion de %s. Cierra la ventana para terminar." % bz.usuario)
            page.wait_for_event("close", timeout=0)
            browser.close()
        return
    print("(%.1f s)" % (time.time() - inicio))


if __name__ == "__main__":
    main()

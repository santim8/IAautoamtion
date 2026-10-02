#!/usr/bin/env python3
"""Flujo de solicitud de cupo de credito de punta a punta, solo por API.

Reproduce la secuencia de servicios que llama el front (sacada del HAR del
observador, corrida login-credito_2026-09-25_115230), sin navegador:

  1. validaciones       affiliation-validations v2, card-validations v2,
                        product-validations (SIIF)
  2. validate-request   crea el caso en Bizagi        -> espera VALIDATION
  3. request-data       contacto + datos financieros  -> espera REQUEST_DATA
  4. decision-engine    arranca el motor              -> espera OFFER_RESULT
  5. oferta             GET offer/{idCaso}
  6. offer-config       acepta la primera opcion      -> espera BIOMETRY_START
  7. biometria          los 3 pasos de biometria_api  -> espera BIOMETRY_RESULT

Bizagi responde asincrono (el front se entera por websocket). Aqui no hay
socket: entre paso y paso se consulta POST /request/check hasta que cambie
pasoPendiente, o hasta --espera segundos.

Todos los servicios externos van con el token CIAM de la identidad dummy
(validaciones_api.token_ciam): el documento lo toma cada servicio del body.
Biometria va con la x-api-key interna. No se usa ninguna clave de usuario.

Crea casos reales en Bizagi CERT. Con --cancelar el caso se cancela al
terminar (o al fallar); sin el, queda vivo.

Uso:
    python api_flujo_creditos.py CC:1032410060
    python api_flujo_creditos.py CC:1032410060 --hasta oferta --cancelar
    python api_flujo_creditos.py CC:1032410060 --cancelar-previo
"""
import argparse
import datetime
import html
import json
import os
import sys
import time

import biometria_api
import rutas
import validaciones_api as api

BASE_REQ = api.BASE_EXT + "/loans/req-mgr/external/v1/product/2/request"
BASE_ELIG = api.BASE_EXT + "/loans/eligibility/external"
BASE_OFERTA = api.BASE_EXT + "/loans/loan-offer/external/v1/product/2/request"

PASOS = ["validaciones", "validate-request", "request-data", "decision-engine",
         "oferta", "offer-config", "biometria"]

TIPOS_SOLICITUD = {1: "ORIGINACION", 2: "AUMENTO", 3: "REACTIVACION"}


class FlujoFallido(Exception):
    pass


class Flujo:
    def __init__(self, tipo, numero, args):
        self.tipo_doc = api.DOC_TYPE_SERVICES[tipo]
        self.numero = numero
        self.args = args
        self.doc = {"tipo": self.tipo_doc, "numero": numero}
        self.llamadas = []      # cada request/response, en orden
        self.esperas = []       # cada sondeo de /request/check
        self.id_caso = None
        self.tipo_afiliacion = None
        self.tipo_solicitud = None
        self.oferta = None
        self.inicio = time.time()

    # --- HTTP ---------------------------------------------------------------
    def llamar(self, paso, metodo, url, body=None, esperado=(200,), auth="ciam"):
        if auth == "ciam":
            headers = {"Authorization": api.token_ciam()}
        else:
            headers = {"x-api-key": biometria_api._api_key()}
        t0 = time.time()
        status, cuerpo = api._curl(metodo, url, headers=headers, body=body,
                                   timeout=self.args.timeout)
        ms = int((time.time() - t0) * 1000)
        ok = status in esperado
        self.llamadas.append({
            "paso": paso, "metodo": metodo, "url": url, "status": status,
            "ms": ms, "ok": ok, "request": body, "response": cuerpo})
        print("  %s %-4s %s %s (%d ms)" % ("OK  " if ok else "FAIL", metodo, status,
                                          url.replace(api.BASE_EXT, ""), ms))
        if not ok:
            raise FlujoFallido("%s: HTTP %s, se esperaba %s -> %s"
                               % (paso, status, "/".join(map(str, esperado)),
                                  _corto(cuerpo)))
        return cuerpo

    def check(self):
        """Estado del caso del documento, o None si no hay caso (404)."""
        status, cuerpo = api._curl("POST", BASE_REQ + "/check",
                                   headers={"Authorization": api.token_ciam()},
                                   body=self.doc, timeout=self.args.timeout)
        caso = cuerpo.get("consultarCaso") if isinstance(cuerpo, dict) else None
        return status, caso

    def esperar(self, paso, desde):
        """Sondea /request/check hasta que pasoPendiente deje de ser `desde`."""
        limite = time.time() + self.args.espera
        ultimo = None
        while time.time() < limite:
            status, caso = self.check()
            actual = (caso or {}).get("pasoPendiente")
            estado = (caso or {}).get("estado")
            if (actual, estado) != ultimo:
                self.esperas.append({"paso": paso, "t": round(time.time() - self.inicio, 1),
                                     "status": status, "estado": estado,
                                     "pasoPendiente": actual})
                print("    check: %s / %s" % (estado, actual))
                ultimo = (actual, estado)
            if caso and estado != "IN_PROGRESS":
                raise FlujoFallido("%s: el caso quedo en estado %s (paso %s)"
                                   % (paso, estado, actual))
            if caso and actual != desde:
                return caso
            time.sleep(self.args.intervalo)
        raise FlujoFallido("%s: pasoPendiente sigue en %s despues de %ds"
                           % (paso, desde, self.args.espera))

    # --- los pasos ------------------------------------------------------------
    def precondicion(self):
        status, caso = self.check()
        if not caso:
            print("  sin caso abierto (HTTP %s)" % status)
            return
        print("  ya hay caso %s: %s / %s" % (caso.get("idCaso"), caso.get("estado"),
                                             caso.get("pasoPendiente")))
        if not self.args.cancelar_previo:
            raise FlujoFallido("el documento ya tiene el caso %s abierto; usar "
                               "--cancelar-previo o otra cedula" % caso.get("idCaso"))
        self.llamar("precondicion", "POST", BASE_REQ + "/cancel-request",
                    {"idCaso": caso["idCaso"]})

    def validaciones(self):
        body = {"documento": self.doc}
        r = self.llamar("validaciones", "POST", BASE_ELIG + "/v2/affiliation-validations", body)
        res = r.get("resultadoValidacion") or {}
        if res.get("estado") != "OK":
            raise FlujoFallido("afiliacion: %s" % _corto(res))
        self.tipo_afiliacion = (res.get("datosAdicionales") or {}).get("tipoAfiliacion")

        r = self.llamar("validaciones", "POST", BASE_ELIG + "/v2/card-validations", body)
        res = r.get("resultadoValidacion") or {}
        if res.get("estado") != "OK":
            raise FlujoFallido("tarjeta: %s" % _corto(res.get("datosError") or res))
        self.tipo_solicitud = res.get("tipoSolicitud") or 1

        r = self.llamar("validaciones", "POST", BASE_ELIG + "/v1/product-validations", body)
        res = r.get("resultadoValidacion") or {}
        if res.get("estado") != "OK":
            raise FlujoFallido("SIIF: %s" % _corto(res))
        print("    afiliacion %s, tipoSolicitud %s (%s)"
              % (self.tipo_afiliacion, self.tipo_solicitud,
                 TIPOS_SOLICITUD.get(self.tipo_solicitud, "?")))

    def validate_request(self):
        r = self.llamar("validate-request", "POST", BASE_REQ + "/validate-request",
                        {"canalOrigen": "WEB", "documento": self.doc,
                         "tipoSolicitud": str(self.tipo_solicitud)}, esperado=(200, 202))
        self.id_caso = (r.get("crearCaso") or {}).get("idCaso")
        if not self.id_caso:
            raise FlujoFallido("validate-request no devolvio idCaso: %s" % _corto(r))
        print("    caso %s" % self.id_caso)
        self.esperar("validate-request", desde="VALIDATION")

    def request_data(self):
        persona = {
            "contacto": {"correo": self.args.correo, "telefono": self.args.telefono},
            "datosPersonales": {"estadoCivil": {"codigo": "C02", "descripcion": "Casado(a)"}},
        }
        # Mismo body que manda el front hoy. Sin salario responde 400
        # (LRMGR0004 con D, LRMGR0006 con I); hasta el 2026-09-25 los
        # independientes mandaban {"totalIngresos": n} y pasaba.
        if self.tipo_solicitud == 1:
            persona["datosFinancieros"] = {"salario": self.args.ingresos,
                                           "otrosIngresosLaborales": None,
                                           "ingresosAdicionales": None}
        self.llamar("request-data", "POST", BASE_REQ + "/request-data",
                    {"idCaso": self.id_caso, "tipoSolicitud": str(self.tipo_solicitud),
                     "documento": self.doc, "tipoAfiliacion": self.tipo_afiliacion,
                     "datosPersona": persona}, esperado=(202,))
        self.esperar("request-data", desde="REQUEST_DATA")

    def decision_engine(self):
        antes = (self.check()[1] or {}).get("pasoPendiente")
        self.llamar("decision-engine", "POST", BASE_REQ + "/decision-engine/start",
                    {"idCaso": self.id_caso}, esperado=(202,))
        self.esperar("decision-engine", desde=antes)

    def obtener_oferta(self):
        r = self.llamar("oferta", "GET", BASE_OFERTA + "/offer/%s" % self.id_caso)
        self.oferta = r.get("obtenerOfertaCredito") or {}
        opciones = self.oferta.get("opcionesPago") or []
        if not opciones:
            raise FlujoFallido("la oferta no trae opcionesPago: %s" % _corto(r))
        print("    monto aprobado %s, %d opcion(es) de pago"
              % (self.oferta.get("montoAprobado"), len(opciones)))

    def offer_config(self):
        opciones = self.oferta["opcionesPago"]
        opcion = next((o for o in opciones if o.get("tipoPago") == self.args.opcion), opciones[0])
        monto = self.oferta.get("montoAprobado")
        ciclos = opcion.get("cicloFacturacion") or ["1"]
        antes = (self.check()[1] or {}).get("pasoPendiente")
        self.llamar("offer-config", "POST", BASE_REQ + "/offer-config", {
            "cicloFacturacion": ciclos[-1], "idCaso": self.id_caso,
            "tipoSolicitud": str(self.tipo_solicitud),
            "montoCuota": opcion.get("monto"), "opcionPago": opcion.get("tipoPago"),
            "idProducto": opcion.get("idProducto"), "montoOferta": monto,
            "nombreProducto": opcion.get("nombreProducto"), "montoCupo": monto,
            "montoModificado": False, "montoMinimo": self.args.monto_minimo,
            "manejaRecursosPublicos": False, "ejercePoderPolitico": False,
            "reconocimientoPublico": False}, esperado=(202,))
        self.esperar("offer-config", desde=antes)

    def biometria(self):
        antes = (self.check()[1] or {}).get("pasoPendiente")
        t0 = time.time()
        ok, paso, detalle = biometria_api.biometry_flow(self.id_caso, self.numero)
        self.llamadas.append({"paso": "biometria", "metodo": "-",
                              "url": "biometria_api.biometry_flow (3 llamadas internas)",
                              "status": None, "ms": int((time.time() - t0) * 1000),
                              "ok": ok, "request": None,
                              "response": None if ok else "paso %s: %s" % (paso, detalle)})
        if not ok:
            raise FlujoFallido("biometria fallo en el paso %s: %s" % (paso, detalle))
        self.esperar("biometria", desde=antes)

    def cancelar(self):
        if not self.id_caso:
            return
        try:
            self.llamar("cancelar", "POST", BASE_REQ + "/cancel-request", {"idCaso": self.id_caso})
        except FlujoFallido as e:
            print("! no se pudo cancelar el caso %s: %s" % (self.id_caso, e))

    # --- correr ------------------------------------------------------------
    def correr(self):
        metodos = {"validaciones": self.validaciones, "validate-request": self.validate_request,
                   "request-data": self.request_data, "decision-engine": self.decision_engine,
                   "oferta": self.obtener_oferta, "offer-config": self.offer_config,
                   "biometria": self.biometria}
        hasta = PASOS.index(self.args.hasta)
        error = None
        try:
            print("> precondicion")
            self.precondicion()
            for nombre in PASOS[:hasta + 1]:
                print("> %s" % nombre)
                metodos[nombre]()
        except (FlujoFallido, RuntimeError) as e:
            error = str(e)
            print("! %s" % error)
        if self.args.cancelar:
            print("> cancelar")
            self.cancelar()
        _, final = self.check()
        return error, final


def _corto(valor, n=300):
    txt = valor if isinstance(valor, str) else json.dumps(valor, ensure_ascii=False)
    return txt if len(txt) <= n else txt[:n] + "..."


def escribir_evidencia(flujo, error, final, directorio):
    os.makedirs(directorio, exist_ok=True)
    datos = {"documento": flujo.doc, "idCaso": flujo.id_caso,
             "tipoAfiliacion": flujo.tipo_afiliacion, "tipoSolicitud": flujo.tipo_solicitud,
             "hasta": flujo.args.hasta, "resultado": "FAIL" if error else "PASS",
             "error": error, "estadoFinal": final,
             "duracion_s": round(time.time() - flujo.inicio, 1),
             "llamadas": flujo.llamadas, "esperas": flujo.esperas}
    with open(os.path.join(directorio, "flujo.json"), "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)

    filas = "".join(
        "<tr class='%s'><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
        "<td><details><summary>ver</summary><pre>%s</pre><pre>%s</pre></details></td></tr>"
        % ("ok" if c["ok"] else "ko", html.escape(c["paso"]), c["metodo"],
           html.escape(c["url"].replace(api.BASE_EXT, "")), c["status"], c["ms"],
           html.escape(json.dumps(c["request"], ensure_ascii=False, indent=1)),
           html.escape(_corto(c["response"], 4000)))
        for c in flujo.llamadas)
    esperas = "".join("<tr><td>%s</td><td>%ss</td><td>%s</td><td>%s</td></tr>"
                      % (html.escape(e["paso"]), e["t"], e["estado"], e["pasoPendiente"])
                      for e in flujo.esperas)
    pagina = """<!doctype html><meta charset="utf-8"><title>Flujo API credito</title>
<style>body{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#222}
table{border-collapse:collapse;width:100%%;margin-bottom:24px;font-size:13px}
td,th{border:1px solid #ddd;padding:6px;text-align:left;vertical-align:top}
tr.ok td:first-child{border-left:4px solid #2e7d32}tr.ko td:first-child{border-left:4px solid #c62828}
pre{white-space:pre-wrap;max-height:300px;overflow:auto;background:#f6f6f6;padding:6px}
.res{font-size:18px;font-weight:600;color:%s}</style>
<h1>Flujo API credito: %s %s</h1>
<p class="res">%s</p>
<p>Caso %s, afiliacion %s, tipoSolicitud %s, hasta <b>%s</b>, %ss. Estado final: %s</p>
<h2>Llamadas</h2><table><tr><th>Paso</th><th>Metodo</th><th>URL</th><th>HTTP</th><th>ms</th><th>Detalle</th></tr>%s</table>
<h2>Sondeo de /request/check</h2><table><tr><th>Paso</th><th>t</th><th>estado</th><th>pasoPendiente</th></tr>%s</table>
""" % ("#c62828" if error else "#2e7d32", flujo.tipo_doc, flujo.numero,
       html.escape("FAIL: " + error) if error else "PASS", flujo.id_caso,
       flujo.tipo_afiliacion, flujo.tipo_solicitud, flujo.args.hasta, datos["duracion_s"],
       html.escape(_corto(final)), filas, esperas)
    with open(os.path.join(directorio, "reporte.html"), "w", encoding="utf-8") as f:
        f.write(pagina)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("documento", type=api._parse_doc, help="TIPO:NUMERO, ej. CC:1032410060")
    ap.add_argument("--hasta", choices=PASOS, default="biometria",
                    help="ultimo paso a ejecutar (default: biometria, el flujo completo)")
    ap.add_argument("--cancelar", action="store_true",
                    help="cancelar el caso al terminar (pase o falle)")
    ap.add_argument("--cancelar-previo", action="store_true",
                    help="si el documento ya tiene caso abierto, cancelarlo y seguir")
    ap.add_argument("--ingresos", type=int, default=3000000)
    ap.add_argument("--correo", default="sss@gmail.com")
    ap.add_argument("--telefono", default="3000000000")
    ap.add_argument("--opcion", default="CUOTA_FIJA", help="tipoPago a elegir en la oferta")
    ap.add_argument("--monto-minimo", type=int, default=700000)
    ap.add_argument("--espera", type=int, default=120,
                    help="segundos maximos esperando a Bizagi en cada paso")
    ap.add_argument("--intervalo", type=float, default=4, help="segundos entre /request/check")
    ap.add_argument("--timeout", type=int, default=45, help="timeout por llamada HTTP")
    ap.add_argument("--salida", help="carpeta de evidencias (default evidences/api-flujo_...)")
    args = ap.parse_args(argv if argv is not None else sys.argv[1:])

    tipo, numero = args.documento
    if tipo not in api.DOC_TYPE_SERVICES:
        print("! tipo de documento no soportado: %s (solo CC/CE)" % tipo)
        return 2
    try:
        api.token_ciam()
    except RuntimeError as e:
        print("! %s" % e)
        return 2

    flujo = Flujo(tipo, numero, args)
    error, final = flujo.correr()
    sello = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    directorio = args.salida or rutas.dato("evidences", "api-flujo_%s_%s" % (numero, sello))
    escribir_evidencia(flujo, error, final, directorio)
    print("%s - caso %s - %s" % ("FAIL" if error else "PASS", flujo.id_caso, directorio))
    return 1 if error else 0


if __name__ == "__main__":
    sys.exit(main())

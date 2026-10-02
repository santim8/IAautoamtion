#!/usr/bin/env python3
"""Consulta /request/check mientras el observador mira el flujo.

El front no llama a /request/check desde el navegador: lo llama su middleware
de Next.js (onCheckRequestStatus) en el servidor, cuando se pide una pagina.
Por eso el observador, que escucha a Chrome por CDP, nunca lo ve. Esta sonda
lo pregunta ella misma dos veces por corrida, y deja en la evidencia lo que
responderia la retoma si el afiliado saliera y volviera a entrar en ese punto
(estado, pasoPendiente, idCaso).

Usa el token CIAM de validaciones_api.py, que sale de la identidad dummy fija,
igual que en la coleccion Bruno: el servicio toma el documento del body, no del
token. Por eso hace falta token.txt; sin el, la sonda avisa y se apaga sin
afectar la captura.

Cada llamada tarda entre 3 y 16 s, asi que corre en un hilo aparte: el loop del
observador no puede quedarse esperandola sin perder pantallazos. El hilo solo
hace HTTP; lo que responde lo escribe a disco el loop (volcar_sonda), que es
quien ya escribe la evidencia.
"""
import json
import queue
import threading
import time
from datetime import datetime, timezone

URL = ("https://platform-test-external.colsubsidio.com"
       "/loans/req-mgr/external/v1/product/2/request/check")

# Solo dos consultas por corrida: al detectar el documento (antes de que exista
# el caso, normalmente 404) y al llegar a esta pantalla, cuando el caso ya se
# creo (VALIDATION OK por el socket) y la retoma lo debe ver.
PANTALLA_CASO = "informacion-personal"

# Solo esos dos tipos existen en los servicios de credito.
TIPOS = {"CC": "CO1C", "CE": "CO1E", "CO1C": "CO1C", "CO1E": "CO1E"}

# Lo que necesita validaciones_api.token_ciam(). Se revisa sin red al arrancar
# para avisar de una vez si falta algo en token.txt.
SECRETOS = ("apigee_client_id", "apigee_client_secret",
            "ciam_token_api_key", "ciam_gigya_api_key")


def parse_documento(texto):
    """'CC:52961647' o 'CO1C:52961647' -> ('CO1C', '52961647')."""
    tipo, _, numero = (texto or "").partition(":")
    tipo = TIPOS.get(tipo.strip().upper())
    numero = numero.strip()
    if not tipo or not numero.isdigit():
        raise ValueError("documento esperado TIPO:NUMERO (CC, CE, CO1C o CO1E), "
                         "recibido %r" % texto)
    return tipo, numero


def documento_de(cuerpo_txt):
    """El {"documento": {"tipo", "numero"}} que el front manda a eligibility y
    a req-mgr desde la pantalla de validaciones. None si el body no lo trae."""
    try:
        d = json.loads(cuerpo_txt)
    except (TypeError, ValueError):
        return None
    doc = d.get("documento") if isinstance(d, dict) else None
    if not isinstance(doc, dict):
        return None
    tipo = TIPOS.get(str(doc.get("tipo", "")).upper())
    numero = str(doc.get("numero", "")).strip()
    return (tipo, numero) if tipo and numero.isdigit() else None


def resumir(status, cuerpo):
    """Lo que se mira de un vistazo: estado, paso pendiente, caso y novedad."""
    if status == 404:
        # Llega como la pagina HTML de 404 del gateway, sin JSON. Lo visto en
        # QA: un documento sin caso abierto en Bizagi responde asi.
        return {"estado": "SIN_CASO (404)"}
    caso = cuerpo.get("consultarCaso") if isinstance(cuerpo, dict) else None
    if not isinstance(caso, dict):
        return {"estado": "HTTP %s" % status if status else "SIN_RESPUESTA"}
    return {k: caso.get(k) for k in ("estado", "pasoPendiente", "idCaso", "noveltyType")
            if caso.get(k) not in (None, "")}


def linea(check):
    """'IN_PROGRESS | pasoPendiente REQUEST_DATA | caso 314502'"""
    partes = [check.get("estado", "?")]
    if check.get("pasoPendiente"):
        partes.append("pasoPendiente " + check["pasoPendiente"])
    if check.get("idCaso"):
        partes.append("caso %s" % check["idCaso"])
    return " | ".join(partes)


class SondaCheck:
    def __init__(self, documento=None):
        self.doc = documento        # (tipo, numero); si es None se toma del trafico
        self.activa = True
        self.va = None              # validaciones_api, importado al arrancar
        self.pedidos = set()        # pasos ya consultados
        self.motivos = set()        # consultas que solo se hacen una vez por corrida
        self.cola = queue.Queue()
        self.listos = []            # [(paso, reg)] que el loop escribe a disco
        self.en_vuelo = 0
        self.lock = threading.Lock()

    def arrancar(self):
        """False si token.txt no alcanza. Si alcanza, el token CIAM se pide en
        el hilo, para que la primera consulta no tenga que esperarlo."""
        import validaciones_api as va
        faltan = [c for c in SECRETOS if not va._SECRETOS.get(c)]
        if faltan:
            print("! /request/check apagado: falta %s en token.txt"
                  % ", ".join(faltan))
            self.activa = False
            return False
        self.va = va
        threading.Thread(target=self._trabajar, daemon=True).start()
        return True

    def aprender(self, cuerpo_txt):
        """True si este body trae un documento distinto al que se venia usando."""
        doc = documento_de(cuerpo_txt)
        if doc is None or doc == self.doc:
            return False
        self.doc = doc
        print(">> Documento del flujo: %s %s (lo uso para /request/check)" % doc)
        return True

    def pedir(self, paso, motivo, forzar=False, una_vez=False):
        """Encola una consulta, en cuanto se conoce el documento. una_vez: el
        motivo no se repite en la corrida (p. ej. recargar informacion personal)."""
        if not self.activa or self.doc is None or paso is None:
            return
        if paso["idx"] in self.pedidos and not forzar:
            return
        if una_vez and motivo in self.motivos:
            return
        self.pedidos.add(paso["idx"])
        self.motivos.add(motivo)
        with self.lock:
            self.en_vuelo += 1
        self.cola.put((paso, motivo, self.doc))

    def recoger(self):
        with self.lock:
            listos, self.listos = self.listos, []
        return listos

    def cerrar(self, paso, espera=30):
        """Espera lo que siga en vuelo (con tope). No consulta de nuevo: solo
        hay dos consultas por corrida, al inicio y en informacion personal."""
        if not self.activa or self.doc is None:
            return
        with self.lock:
            if not self.en_vuelo:
                return
        print("   esperando /request/check (hasta %d s)..." % espera)
        limite = time.time() + espera
        while time.time() < limite and self.activa:
            with self.lock:
                if not self.en_vuelo:
                    return
            time.sleep(0.2)

    # -- hilo
    def _trabajar(self):
        try:
            self.va.token_ciam()
        except RuntimeError as e:
            print("! /request/check apagado: %s" % e, flush=True)
            self.activa = False
            return
        while True:
            paso, motivo, doc = self.cola.get()
            try:
                reg = self._consultar(doc, motivo)
            except Exception as e:      # el hilo no puede morir con la cola llena
                reg = None
                print("! /request/check fallo: %s" % e, flush=True)
            with self.lock:
                if reg is not None:
                    self.listos.append((paso, reg))
                self.en_vuelo -= 1

    def _consultar(self, doc, motivo):
        tipo, numero = doc
        body = {"tipo": tipo, "numero": numero}
        ts = datetime.now(timezone.utc).isoformat()
        t0 = time.time()
        try:
            status, cuerpo = self.va._curl(
                "POST", URL, headers={"Authorization": self.va.token_ciam()},
                body=body, timeout=30)
        except RuntimeError as e:
            status, cuerpo = None, str(e)
        return {
            "ts": ts,
            "metodo": "POST",
            "url": URL,
            "tipo": "sonda",
            "status": status or 0,
            "duracion_ms": round((time.time() - t0) * 1000),
            # el token es el dummy de CIAM, no del usuario: nunca va a la evidencia
            "request_headers": {"authorization": "<REDACTED>",
                                "content-type": "application/json"},
            "request_body": json.dumps(body),
            "response_headers": {},
            "response_body": (cuerpo if isinstance(cuerpo, str)
                              else json.dumps(cuerpo, ensure_ascii=False)),
            "sonda": "request/check",
            "motivo": motivo,
            "check": resumir(status, cuerpo),
        }

"""E2E con validador: recorre la solicitud como un afiliado, valida cada
pantalla y sus servicios, y deja el reporte del observador con el veredicto
arriba. Es el que corre Claude cuando le piden validar un despliegue o una
cedula de punta a punta.

  python -m colsubsidio_flow e2e --documento CC:52335676 [--slug mujeres | --entrada cupo]
                                 [--hasta politicas] [--rapido] [--headless]

El front decide a donde va y el validador reacciona a la ruta en que cae:
  onboarding -> sesion -> validaciones -> politicas -> informacion-personal
  -> personalizacion-oferta -> datos-adicionales -> biometria -> fin
Asi una retoma (caso en curso) sigue desde la pantalla a la que lleve.

--hasta PANTALLA: se detiene al llegar a ella, sin tocar nada ahi. Default
politicas: el ambiente no pasa de ahi (28/10) y su "Continuar" crea el caso en
Bizagi. Mas alla de politicas pulsa Continuar (CREA EL CASO) y sigue; en
biometria la completa por API (biometria_api) salvo --sin-biometria.

--dejar-abierto: al detenerse deja la ventana en esa pantalla con el
observador grabando; lo que el QA haga a mano entra al reporte, que se
escribe al cerrar la ventana (o con Enter en la consola).

Que valida, por seccion del reporte:
  validaciones  lo de validaciones-225425: request, contrato, orden y corte
                SAP -> ASCARD -> SIIF, pantalla y el esperado de la cedula
  politicas     lo de politicas-225427: contenido igual a Drupal, enlaces,
                diseno, accesibilidad y reglas de las casillas. Con --rapido
                solo que cargue y que Continuar se habilite con todo marcado
  las demas     que se pueda llenar y avanzar, que llame su servicio con el
                status esperado y que Bizagi confirme su paso por el socket
  servicios     al cerrar: ningun servicio con 5xx, CORS o sin respuesta y
                ningun stepStatus FAIL en el socket
Los FAIL que ya son defectos reportados (CONOCIDOS) quedan como CONOCIDO y no
tumban el veredicto: PASA, PASA CON CONOCIDOS o FALLA.

Evidencia: evidences/e2e_<producto>_<numero>_<fecha>/ con el reporte.html del
observador (el validador va arriba), validador.json, final.png (donde se
detuvo) y lo de siempre (servicios.json, requests.jsonl, pantallazos).

Las pantallas despues de politicas se armaron con la corrida de Cupo del 15/10
en qa (evidences/login-credito_2026-10-15_120527) y los locators de Java: no se
han podido correr con este script porque el ambiente no pasa de politicas.

No esta en Java: es nuevo.
"""
import json
import os
import re
import threading
import time
from collections import Counter
from urllib.parse import urlsplit

from .. import _rutas  # noqa: F401
from ..core import reporte as log
from ..pages import PoliciesPage
from . import hasta_politicas_test as hp
from . import politicas_225427_test as p27
from . import validaciones_225425_test as v25

import validaciones_api as va  # noqa: E402  (raiz del repo, via _rutas)
from observador.config import SELECTOR_MENSAJE  # noqa: E402

NOMBRE = "E2E"
TEST_ID = "e2e"
AUTORES = "Santiago Correa"
CATEGORIAS = ("E2E",)
DATA_PROVIDER = "e2e"
URL = hp.URL
MANEJA_HASTA_LOGIN = True
MANEJA_DEJAR_ABIERTO = True

# El ultimo tramo de la ruta de cada pantalla, en el orden del flujo.
PANTALLAS = ("validaciones", "politicas", "informacion-personal", "personalizacion-oferta",
             "datos-adicionales", "biometria", "fin")
# Lo que cada pantalla llama al avanzar: (metodo, fragmento de URL, status
# buenos). politicas no esta: su validate lo revisa politicas-225427.
SERVICIOS = {
    "informacion-personal": [("POST", "/request/request-data", (202,))],
    "personalizacion-oferta": [("POST", "/decision-engine/start", (202,)),
                               ("GET", "/request/offer/", (200,))],
    "datos-adicionales": [("POST", "/request/offer-config", (202,))],
}
# El paso que Bizagi confirma por socket antes de que el front avance.
SOCKET = {
    "politicas": ("VALIDATION",),
    "informacion-personal": ("REQUEST_DATA",),
    "personalizacion-oferta": ("OFFER_RESULT",),
    "datos-adicionales": ("OFFER_CONFIG_RESULT", "BIOMETRY_START"),
    "biometria": ("BIOMETRY_RESULT",),
}
VALIDACIONES = tuple(ruta for _clave, ruta, _nombre in v25.SERVICIOS)
# 4xx que el front tolera: sin campana vigente, y la oferta que se consulta
# hasta que el motor la deja lista.
TOLERADOS_4XX = ("/campaigns/", "/request/offer/")

# FAIL que ya son defectos reportados: (patron sobre el mensaje, referencia).
# Quedan CONOCIDO y no tumban el veredicto. Quitar la fila cuando se corrija.
CONOCIDOS = [
    (r"^Casilla \d+ tiene nombre accesible", "225427: casillas sin label ni aria-label (24/10)"),
    (r"^Si/No exponen cual esta elegida", "225427: Si/No sin aria-pressed ni radio (24/10)"),
    (r"el texto de la declaracion marca la casilla", "225427: el texto no marca la casilla (24/10)"),
    (r"Reglamento del producto' sin enlace", "234206: Reglamento del producto sin enlace"),
]

# Datos con que se llena un formulario: (patron sobre la etiqueta, dato). Los
# opcionales se dejan vacios sin avisar.
CAMPOS = [
    (r"secundario|opcional", "opcional"),
    (r"correo|e-?mail", "correo"),
    (r"celular|tel[eé]fono|m[oó]vil|n[uú]mero", "celular"),
    (r"ingreso|salario|valor|monto|\$", "ingreso"),
]
# Botones con que se avanza, y los que nunca se tocan (salen del flujo o
# cambian la oferta).
AVANZAR = re.compile(r"^\s*(Continuar|Aceptar\b.*|Entendido)\s*$", re.I)
NUNCA = re.compile(r"Abandonar|Volver|Ajustar|Salir|Cancelar", re.I)
ESPERA_PANTALLA_S = 120     # el motor de decision tarda en dejar la oferta
MAX_CLICS = 5
DESHABILITADO_S = 15

JS_ETIQUETA = """e => {
  const partes = [e.getAttribute('aria-label'), e.placeholder, e.name, e.id];
  for (const l of (e.labels || [])) partes.push(l.innerText);
  for (let n = e, i = 0; n && i < 4; n = n.parentElement, i++) {
    const previo = n.previousElementSibling;
    if (previo && previo.innerText) { partes.push(previo.innerText); break; }
  }
  return partes.filter(Boolean).join(' | ');
}"""
# Campo controlado por React que no tomo el fill (feedback_react_selenium).
JS_VALOR_NATIVO = """(e, v) => {
  Object.getOwnPropertyDescriptor(Object.getPrototypeOf(e), 'value').set.call(e, v);
  e.dispatchEvent(new Event('input', {bubbles: true}));
  e.dispatchEvent(new Event('change', {bubbles: true}));
}"""

FILAS = []          # una por cedula, para al_terminar


def necesita_clave(opciones):
    return hp.necesita_clave(opciones)


def url_inicial(opciones):
    return hp.url_inicial(opciones)


def check(ok, nombre, detalle=""):
    (log.pass_ if ok else log.fail)(nombre + (" -- " + detalle if detalle else ""))
    return ok


def meta(opciones):
    return opciones.get("hasta") or "politicas"


def pantalla_de(url, opciones):
    """Ultimo tramo de la ruta (politicas, fin...), o None fuera del front."""
    limpia = url.split("?")[0].split("#")[0].rstrip("/")
    base = hp.base_de(opciones)
    return limpia.rsplit("/", 1)[-1] if limpia.startswith(base) else None


def conocido(mensaje):
    return next((ref for patron, ref in CONOCIDOS if re.search(patron, mensaje)), None)


# -- lo capturado
def frames(obs):
    """(step, stepStatus) de lo que mando Bizagi por el socket, en orden."""
    vistos = []
    for paso in obs.pasos:
        for fr in paso.get("sockets") or []:
            datos = v25.leer(fr.get("payload")) or {}
            if isinstance(datos, dict) and datos.get("step"):
                vistos.append((datos["step"], str(datos.get("stepStatus") or "")))
    return vistos


def id_caso(obs):
    for paso in obs.pasos:
        for r in paso["requests"]:
            if "/request/validate" in r["url"]:
                m = re.search(r'"idCaso"\s*:\s*"?(\d+)', r.get("response_body") or "")
                if m:
                    return m.group(1)
        for fr in paso.get("sockets") or []:
            m = re.search(r'"idCase"\s*:\s*"?(\d+)', fr.get("payload") or "")
            if m:
                return m.group(1)
    return None


def corto(texto, n=160):
    return re.sub(r"\s+", " ", texto or "").strip()[:n]


# -- la pagina
def mensaje_visible(driver):
    try:
        return driver.page.locator(SELECTOR_MENSAJE).count() > 0
    except Exception:
        return False


def esperar_cambio(driver, obs, opciones, desde, segundos, texto_antes=None):
    """Hasta que la ruta deje de ser `desde`, salga un mensaje o (con
    texto_antes) cambie lo que se ve: "ruta", "mensaje", "contenido" o None."""
    fin = time.time() + segundos
    while time.time() < fin:
        hp.esperar(driver, obs, 0.5)
        if pantalla_de(driver.page.url, opciones) != desde:
            return "ruta"
        if mensaje_visible(driver):
            hp.esperar(driver, obs, 4)    # el texto llega despues de Drupal
            return "mensaje"
        if texto_antes is not None and hp.texto_pantalla(driver) != texto_antes:
            return "contenido"
    return None


def boton_avanzar(page):
    """(boton, texto) del boton visible con que se avanza; dentro del modal si
    hay uno abierto."""
    modal = page.locator("[role='dialog']")
    ambito = modal.last if modal.count() and modal.last.is_visible() else page
    for boton in ambito.locator("button").all():
        try:
            if not boton.is_visible():
                continue
            texto = re.sub(r"\s+", " ", boton.inner_text()).strip()
        except Exception:
            continue
        if AVANZAR.match(texto) and not NUNCA.search(texto):
            return boton, texto
    return None, None


def dato_para(etiqueta, usuario):
    """El dato para ese campo, "" si es opcional o None si no se sabe."""
    valores = {"celular": "3001234567", "correo": "test%s@example.com" % usuario.numero[-4:],
               "ingreso": "3000000", "opcional": ""}
    for patron, clave in CAMPOS:
        if re.search(patron, etiqueta, re.I):
            return valores[clave]
    return None


def llenar_campos(page, usuario):
    """Los campos de texto visibles y vacios, en orden. La confirmacion se
    habilita con el blur del anterior: por eso Tab y otra vuelta."""
    llenos, sin_dato = [], []
    for _vuelta in range(3):
        nuevos = 0
        for campo in page.locator("input:not([type=checkbox]):not([type=radio])"
                                  ":not([type=hidden]), textarea").all():
            try:
                if not (campo.is_visible() and campo.is_editable()) or campo.input_value():
                    continue
                etiqueta = corto(campo.evaluate(JS_ETIQUETA), 80)
            except Exception:
                continue
            valor = dato_para(etiqueta, usuario)
            if valor == "":
                continue
            if valor is None:
                if etiqueta not in sin_dato:
                    sin_dato.append(etiqueta)
                continue
            try:
                campo.fill(valor, timeout=5000)
            except Exception:
                pass
            if re.sub(r"\D", "", campo.input_value()) != re.sub(r"\D", "", valor) \
                    and campo.input_value() != valor:
                campo.evaluate(JS_VALOR_NATIVO, valor)
            campo.press("Tab")
            page.wait_for_timeout(300)
            llenos.append("%s=%s" % (etiqueta, valor))
            nuevos += 1
        if not nuevos:
            break
    return llenos, sin_dato


def responder_no(page):
    """Preguntas Si/No sin respuesta (las PEP de datos adicionales): 'No'."""
    hechas = []
    nombres = page.locator("button[data-name]").evaluate_all(
        "els => [...new Set(els.filter(b => b.offsetWidth || b.offsetHeight)"
        ".map(b => b.dataset.name))]")
    for nombre in nombres:
        grupo = page.locator("button[data-name=%s]" % json.dumps(nombre))
        if grupo.evaluate_all("els => els.some(b => b.classList.contains('selected'))"):
            continue
        no = grupo.filter(has_text=re.compile(r"^\s*No\s*$"))
        if no.count():
            no.first.click()
            hechas.append(nombre)
    return hechas


def elegir_radios(page):
    """En cada grupo de radios sin elegir: la cuota fija si esta, si no el primero."""
    elegidos = []
    for nombre in page.locator("input[type=radio]").evaluate_all(
            "els => [...new Set(els.map(e => e.name || ''))]"):
        radios = page.locator("input[type=radio][name=%s]" % json.dumps(nombre) if nombre
                              else "input[type=radio]:not([name]), input[type=radio][name='']")
        if not radios.count() or radios.evaluate_all("els => els.some(e => e.checked)"):
            continue
        fija = radios.evaluate_all(
            "els => els.findIndex(e => /fija/i.test(e.id + ' ' + [...(e.labels || [])]"
            ".map(l => l.innerText).join(' ')))")
        radio = radios.nth(max(fija, 0))
        try:
            radio.check(force=True, timeout=5000)
        except Exception:
            radio.evaluate("e => e.click()")
        elegidos.append(radio.get_attribute("id") or nombre or "radio")
    return elegidos


def marcar_casillas(page):
    marcadas = 0
    for casilla in page.locator("input[type=checkbox]").all():
        try:
            if casilla.is_visible() and not casilla.is_checked():
                casilla.check(force=True, timeout=5000)
                marcadas += 1
        except Exception:
            pass
    return marcadas


# -- pantallas
def completar(driver, obs, usuario, opciones, pantalla):
    """Llena lo que pida la pantalla y pulsa avanzar hasta que cambie de ruta.
    Una ruta puede tener varios tramos (las preguntas y luego los terminos):
    cada vez que cambia lo que se ve se vuelve a llenar. Devuelve "ruta",
    "mensaje" o None (se quedo)."""
    page = driver.page
    fin = time.time() + (opciones.get("espera") or ESPERA_PANTALLA_S)
    clics, deshabilitado = 0, None
    while time.time() < fin and clics < MAX_CLICS:
        if pantalla_de(page.url, opciones) != pantalla:
            return "ruta"
        if mensaje_visible(driver):
            return "mensaje"
        boton, texto = boton_avanzar(page)
        if boton is None:
            hp.esperar(driver, obs, 1)      # cargando (la oferta tarda)
            continue
        llenos, sin_dato = llenar_campos(page, usuario)
        respondidas = responder_no(page)
        radios = elegir_radios(page)
        casillas = marcar_casillas(page)
        if llenos or respondidas or radios or casillas:
            log.info("Llena: %s" % "; ".join(
                llenos + ["'No' en %s" % ", ".join(respondidas)] * bool(respondidas)
                + ["radio %s" % ", ".join(radios)] * bool(radios)
                + ["%d casilla(s)" % casillas] * bool(casillas)))
        if sin_dato:
            log.warning("Campos sin dato conocido (quedan vacios): %s" % " / ".join(sin_dato))
        hp.esperar(driver, obs, 0.3)
        if not boton.is_enabled():
            deshabilitado = deshabilitado or time.time()
            if time.time() - deshabilitado > DESHABILITADO_S:
                log.fail("'%s' sigue deshabilitado tras llenar la pantalla%s"
                         % (texto, "; campos vacios: " + " / ".join(sin_dato) if sin_dato else ""))
                return None
            hp.esperar(driver, obs, 1)
            continue
        deshabilitado = None
        antes = hp.texto_pantalla(driver)
        log.info("Clic en '%s'" % texto)
        boton.click()
        clics += 1
        cambio = esperar_cambio(driver, obs, opciones, pantalla, max(5, fin - time.time()), antes)
        if cambio != "contenido":
            return cambio
    return None


def politicas(driver, obs, usuario, opciones, seguir):
    """Lo de politicas-225427 (o lo minimo con --rapido); con seguir pulsa
    Continuar, que crea el caso."""
    producto = "cupo" if "/cupo-de-credito/" in driver.page.url else "consumo"
    if not opciones.get("rapido"):
        p27.probar_politicas(driver, obs, dict(opciones, continuar=seguir))
        return
    pagina = PoliciesPage(driver).wait_loaded()
    respuesta_si = producto == "consumo" and opciones.get("respuesta") == "si"
    if respuesta_si:
        pagina.select_option(pagina.get_options()[0][0])     # Si va a la izquierda
    for i in range(len(pagina.get_checkboxes())):
        pagina.set_checkbox(i, True)
    check(pagina.continue_enabled(), "Con todo marcado Continuar se habilita")
    if seguir:
        p27.continuar(pagina, driver, obs, producto, respuesta_si)


def biometria(driver, obs, usuario, opciones):
    """Pasa las instrucciones y completa la biometria por API con el caso
    real (como LoginCreditoTest); el front se entera por el socket."""
    check("Verifica tu identidad" in hp.texto_pantalla(driver), "Pantalla de verificacion de "
          "identidad", corto(hp.texto_pantalla(driver)))
    boton, texto = boton_avanzar(driver.page)
    if boton is not None and boton.is_enabled():
        log.info("Clic en '%s'" % texto)
        boton.click()
        hp.esperar(driver, obs, 3)
    caso = id_caso(obs)
    if opciones.get("sin_biometria") or not caso:
        log.warning("Biometria por API omitida (%s)" % ("--sin-biometria" if caso else "sin idCaso"))
        return esperar_cambio(driver, obs, opciones, "biometria", 30)
    import biometria_api
    resultado = {}
    hilo = threading.Thread(target=lambda: resultado.update(
        r=biometria_api.biometry_flow(caso, usuario.numero)))
    hilo.start()
    while hilo.is_alive():
        hp.esperar(driver, obs, 0.5)
    ok, paso, detalle = resultado.get("r") or (False, None, "sin respuesta")
    check(ok, "Biometria por API del caso %s" % caso, "fallo el paso %s: %s" % (paso, detalle)
          if not ok else "")
    return esperar_cambio(driver, obs, opciones, "biometria",
                          opciones.get("espera") or ESPERA_PANTALLA_S)


def fin(driver, obs):
    hp.esperar(driver, obs, 3)
    texto = hp.texto_pantalla(driver)
    check("Application error" not in texto, "La Thank You Page carga sin error del cliente",
          corto(texto))
    log.info("Pantalla: %s" % corto(texto, 400))


def validar_pantalla(obs, pantalla):
    """Los servicios de la pantalla y su paso en el socket."""
    for metodo, fragmento, buenos in SERVICIOS.get(pantalla, ()):
        regs = [r for p in obs.pasos for r in p["requests"]
                if fragmento in r["url"] and r["metodo"] == metodo]
        if not regs:
            log.fail("No se llamo %s %s" % (metodo, fragmento))
            continue
        statuses = [r.get("status") or r.get("fallo") for r in regs]
        ultimo = regs[-1]
        check(any(r.get("status") in buenos for r in regs),
              "%s %s responde %s" % (metodo, fragmento, "/".join(map(str, buenos))),
              "%s %s" % (statuses, corto(ultimo.get("response_body") or ultimo.get("nota"))))
    vistos = frames(obs)
    for step in SOCKET.get(pantalla, ()):
        estados = [st for s, st in vistos if s == step]
        if not estados:
            log.fail("Bizagi no confirmo %s por el socket (el front espera ese mensaje para "
                     "avanzar)" % step)
        else:
            check(all(st.upper() == "OK" for st in estados), "Socket %s %s" % (step, "/".join(estados)))


def url_check(opciones):
    """/request/check del back que usa el front: el de dev esta detras del
    mismo cloudfront; qa (dev.colsubsidio.com) usa el de CERT."""
    partes = urlsplit(hp.base_de(opciones))
    back = ("%s://%s" % (partes.scheme, partes.netloc) if "cloudfront.net" in partes.netloc
            else va.BASE_EXT)
    return back + "/loans/req-mgr/external/v1/product/%d/request/check" % (
        2 if opciones.get("entrada") == "cupo" else 1)


def caso_en_curso(usuario, opciones, estado):
    """Antes de entrar: con un caso abierto el front hace retoma y no pasa
    por validaciones ni politicas."""
    try:
        status, cuerpo = va._curl("POST", url_check(opciones),
                                  headers={"Authorization": va.token_ciam()},
                                  body={"tipo": v25.TIPO_FRONT[usuario.tipo],
                                        "numero": usuario.numero})
    except Exception as e:
        log.warning("/request/check no respondio: %s" % e)
        return
    caso = cuerpo.get("consultarCaso") if isinstance(cuerpo, dict) else None
    if status == 200 and caso:
        estado["caso_previo"] = caso
        log.warning("Caso en curso %s (%s / %s): el front va a retomar en vez de pasar por "
                    "validaciones" % (caso.get("idCaso"), caso.get("estado"),
                                      caso.get("pasoPendiente")))
    elif status == 404:
        log.pass_("Sin caso en curso (/request/check 404)")
    else:
        log.warning("/request/check respondio %s: %s" % (status, corto(str(cuerpo))))


def validar_validaciones(driver, obs, usuario, opciones, desenlace, estado):
    """Lo de validaciones-225425. True si el flujo sigue."""
    if opciones.get("directo"):
        log.warning("--directo: se salto validaciones, no hay servicios que revisar")
        return desenlace == "politicas"
    regs = {clave: v25.llamada(obs, ruta) for clave, ruta, _ in v25.SERVICIOS}
    res = {clave: v25.resultado(reg) for clave, reg in regs.items()}
    pantalla = pantalla_de(driver.page.url, opciones)
    if all(r == v25.NO_LLAMADO for r in res.values()) and pantalla in PANTALLAS[1:]:
        caso = estado.get("caso_previo") or {}
        log.warning("Retoma%s: el front llevo a %s sin pasar por validaciones"
                    % (" del caso %s" % caso["idCaso"] if caso.get("idCaso") else "", pantalla))
        estado["retoma"] = pantalla
        return True
    estado["revisados"].update(VALIDACIONES)
    log.info("SAP=%s | ASCARD=%s | SIIF=%s | pantalla=%s"
             % (res["sap"], res["ascard"], res["siif"], desenlace))
    v25.probar_requests(regs, usuario, opciones)
    v25.probar_respuestas(regs, res)
    v25.probar_orden(regs, res)
    if desenlace != "otra pantalla":
        v25.probar_pantalla(driver, res, desenlace, hp.texto_pantalla(driver), opciones)
    v25.probar_esperado(usuario, res, desenlace)
    if desenlace in ("politicas", "otra pantalla"):
        return True
    if (usuario.esperado or {}).get("pantalla") == desenlace:
        log.pass_("Se detiene en validaciones como se esperaba (%s)" % desenlace)
        estado["cumplido"] = True
    else:
        log.fail("No llega a %s: se detuvo en validaciones (%s)" % (meta(opciones), desenlace))
    return False


def recorrer(driver, obs, usuario, opciones, estado):
    objetivo = meta(opciones)
    log.seccion("sesion")
    caso_en_curso(usuario, opciones, estado)
    desenlace = hp.llegar_a_politicas(driver, obs, usuario, opciones)
    if desenlace is None:
        log.fail("No se inicio sesion")
        return
    estado["camino"].append("validaciones")
    log.seccion("validaciones")
    if not validar_validaciones(driver, obs, usuario, opciones, desenlace, estado):
        return
    while True:
        pantalla = pantalla_de(driver.page.url, opciones)
        if pantalla is None:
            log.seccion("fuera del front")
            log.fail("El front llevo a otro sitio: %s" % driver.page.url)
            return
        log.seccion(pantalla)
        if pantalla not in PANTALLAS:
            log.fail("Pantalla que el validador no conoce: %s" % hp.ruta(driver.page.url, opciones))
            return
        if pantalla in estado["camino"]:
            log.fail("Volvio a %s: el flujo no avanza" % pantalla)
            return
        estado["camino"].append(pantalla)
        de_largo = PANTALLAS.index(pantalla) > PANTALLAS.index(objetivo)
        if de_largo:
            log.fail("No llega a %s: el front llevo a %s%s"
                     % (objetivo, pantalla, " (retoma del caso en curso)"
                        if estado.get("retoma") == pantalla else ""))
        if mensaje_visible(driver):
            log.fail("Mensaje en %s: %s" % (pantalla, corto(hp.texto_pantalla(driver), 300)))
            return
        if de_largo:
            return
        seguir = pantalla != objetivo
        if pantalla == "politicas":
            politicas(driver, obs, usuario, opciones, seguir)
            estado["revisados"].add("/request/validate")
        elif pantalla == "fin":
            fin(driver, obs)
        if not seguir:
            estado["cumplido"] = check(True, "Llega a %s" % objetivo)
            return
        if pantalla == "politicas":
            cambio = esperar_cambio(driver, obs, opciones, pantalla,
                                    opciones.get("espera") or ESPERA_PANTALLA_S)
        elif pantalla == "biometria":
            cambio = biometria(driver, obs, usuario, opciones)
        else:
            cambio = completar(driver, obs, usuario, opciones, pantalla)
        estado["revisados"].update(f for _m, f, _b in SERVICIOS.get(pantalla, ()))
        validar_pantalla(obs, pantalla)
        if cambio == "mensaje":
            log.fail("Mensaje en %s: %s" % (pantalla, corto(hp.texto_pantalla(driver), 300)))
            return
        if cambio != "ruta":
            log.fail("Se quedo en %s: %s" % (pantalla, corto(hp.texto_pantalla(driver), 200)))
            return


def mantener_abierto(driver, obs, opciones):
    """La ventana se queda donde se detuvo, con el observador grabando, hasta
    que el QA la cierre o de Enter en la consola."""
    log.seccion("a mano")
    log.info("Pantalla abierta en %s: sigue en el navegador si quieres, el observador sigue "
             "grabando. Cierra la ventana (o Enter en la consola) para terminar y escribir el "
             "reporte." % hp.ruta(driver.page.url, opciones))
    print("\n>>> Pantalla abierta. Cierra la ventana o da Enter para terminar.", flush=True)
    enter = threading.Event()

    def leer():
        try:
            input()
            enter.set()
        except (EOFError, OSError):
            pass        # sin consola: se termina cerrando la ventana

    threading.Thread(target=leer, daemon=True).start()
    inicio, desde = time.time(), len(obs.pasos)
    while not enter.is_set():
        try:
            if driver.page.is_closed():
                break
            hp.esperar(driver, obs, 0.5)
        except Exception:
            break       # se cerro el navegador
    a_mano = [pantalla_de(p["url"], opciones) or p["url"] for p in obs.pasos[desde:]]
    log.info("Fin de la parte a mano tras %d s (%s)%s"
             % (time.time() - inicio, "Enter" if enter.is_set() else "ventana cerrada",
                "; paso por " + " -> ".join(a_mano) if a_mano else "; sin cambiar de pantalla"))
    if enter.is_set():
        try:
            driver.page.screenshot(path=os.path.join(obs.dir, "final_a_mano.png"), full_page=True)
        except Exception:
            pass


# -- al cerrar
def validar_servicios(obs, estado):
    """Lo que no reviso ninguna pantalla: 5xx, CORS y sin respuesta, y los
    FAIL del socket."""
    log.seccion("servicios")
    malos = 0
    for paso in obs.pasos:
        for r in paso["requests"]:
            if not r.get("rastreados") or r.get("sonda") \
                    or any(f in r["url"] for f in estado["revisados"]):
                continue
            status = r.get("status") or 0
            etiqueta = "%s %s (paso %02d)" % (r["metodo"], r["url"].split("?")[0], paso["idx"])
            if r.get("fallo") or status >= 500:
                log.fail("%s -> %s %s" % (etiqueta, status or r.get("fallo"),
                                         corto(r.get("response_body") or r.get("nota"), 200)))
                malos += 1
            elif status >= 400 and not any(t in r["url"] for t in TOLERADOS_4XX):
                log.warning("%s -> %s" % (etiqueta, status))
    for step, st in frames(obs):
        if st.upper() in ("FAIL", "ERROR"):
            log.fail("Socket %s %s" % (step, st))
            malos += 1
    if not malos:
        log.pass_("Ningun otro servicio con 5xx, CORS o sin respuesta, ni FAIL en el socket")


def armar_validador(obs, usuario, opciones, estado):
    rep = log.actual()
    lineas = []
    for linea in rep.lineas:
        linea = dict(linea)
        ref = conocido(linea["mensaje"]) if linea["marca"] == "FAIL" else None
        if ref:
            linea.update(marca="CONOCIDO", conocido=ref)
        lineas.append(linea)
    # las conocidas no cuentan como fallas del test
    rep.fallas = [f for f in rep.fallas if not conocido(f)]
    conteo = Counter(linea["marca"] for linea in lineas)
    if conteo["FAIL"] or not estado["cumplido"]:
        veredicto = "FALLA"
    else:
        veredicto = "PASA CON CONOCIDOS" if conteo["CONOCIDO"] else "PASA"
    fotos = sorted((f for f in os.listdir(obs.dir) if f.endswith(".png")),
                   key=lambda f: (f != "final.png", f))
    obs.validador = {
        "test": "e2e", "documento": usuario.documento, "nota": usuario.nota,
        "producto": hp.producto(opciones), "base": hp.base_de(opciones),
        "sesion": opciones.get("sesion") or "token", "hasta": meta(opciones),
        "llego_a": estado["camino"][-1] if estado["camino"] else None,
        "camino": estado["camino"], "caso": id_caso(obs),
        "caso_previo": (estado.get("caso_previo") or {}).get("idCaso"), "veredicto": veredicto,
        "conteo": dict(conteo), "duracion_s": round(rep.duracion()),
        "inicio": rep.lineas[0]["ts"] if rep.lineas else None, "fotos": fotos,
        "lineas": lineas,
    }


def imprimir_veredicto(v, directorio):
    print("\n=== Validador: %s  (%s %s, hasta %s, llego a %s%s)"
          % (v["veredicto"], v["producto"], v["documento"], v["hasta"], v["llego_a"],
             ", caso %s" % v["caso"] if v["caso"] else ""))
    print("  %s" % "  ".join("%s %d" % (m, v["conteo"].get(m, 0))
                             for m in ("PASS", "FAIL", "CONOCIDO", "WARN")))
    for linea in v["lineas"]:
        if linea["marca"] in ("FAIL", "CONOCIDO"):
            print("  [%s] %s: %s%s" % (linea["marca"], linea["seccion"], linea["mensaje"],
                                       "  <- %s" % linea["conocido"] if linea.get("conocido") else ""))
    print("  Reporte: %s" % os.path.join(directorio, "reporte.html"))


def run(driver, usuario, opciones):
    estado = {"camino": [], "cumplido": False, "revisados": set()}
    capturado = {}

    def pasos(obs):
        capturado["obs"] = obs
        try:
            recorrer(driver, obs, usuario, opciones, estado)
        except Exception as e:
            log.fail("Excepcion en %s: %s" % (log.actual().seccion or "inicio",
                                              str(e).strip().split("\n")[0]))
        finally:
            try:
                driver.page.screenshot(path=os.path.join(obs.dir, "final.png"), full_page=True)
            except Exception:
                pass
        if opciones.get("dejar_abierto"):
            mantener_abierto(driver, obs, opciones)

    def al_parar(obs):
        validar_servicios(obs, estado)
        armar_validador(obs, usuario, opciones, estado)

    hp.capturar(driver, usuario, opciones, "e2e", pasos, al_parar)
    obs = capturado.get("obs")
    v = getattr(obs, "validador", None)
    if v:
        imprimir_veredicto(v, obs.dir)
        FILAS.append(dict({k: v[k] for k in ("documento", "veredicto", "llego_a", "caso", "conteo")},
                          reporte=os.path.join(obs.dir, "reporte.html")))


def al_terminar(_opciones):
    if len(FILAS) < 2:
        return
    print("\n=== Validador por cedula")
    for f in FILAS:
        print("  %-14s %-20s llego a %-24s %s  %s"
              % (f["documento"], f["veredicto"], f["llego_a"], f["caso"] or "-", f["reporte"]))

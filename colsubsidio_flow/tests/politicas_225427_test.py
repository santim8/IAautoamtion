"""HU 225427: pantalla de politicas de Libre Inversion (y regresion de Cupo,
que comparte la vista). Compara la pantalla con Drupal y prueba las reglas del
diseno final (Figma 4.1):
  - titulo, documentos y enlaces iguales a Drupal; cada enlace responde
  - pregunta de salud con "No" marcado por defecto
  - la declaracion cambia de texto con Si/No y se desmarca al cambiar
  - Continuar deshabilitado hasta marcar todas las casillas
  - Si/No y casillas se manejan con teclado

Llega a politicas como hasta-politicas (token o clave), o se engancha con
--conectar PUERTO a una sesion ya abierta (la que deja hasta-politicas --cdp).
No pulsa Continuar salvo con --continuar, que CREA EL CASO: ahi revisa el body
de validate (politicasConsumo) y la respuesta.

No esta en Java: es nuevo.
"""
import html
import json
import os
import re

from ..core import datalayer
from ..core import reporte as log
from ..pages import PoliciesPage
from ..pages.login_credito_page import decode_jwt
from . import hasta_politicas_test as hp

NOMBRE = "Politicas225427"
TEST_ID = "225427"
AUTORES = "Santiago Correa"
CATEGORIAS = ("REGRESSION",)
DATA_PROVIDER = "hasta_politicas"
URL = hp.BASE + "/consumo/libre-inversion/politicas"
MANEJA_HASTA_LOGIN = True

# DRUPAL_URL del front de dev (consume el Drupal de CERT).
DRUPAL = ("https://platform-test-external.colsubsidio.com/loans-cert-admin-solicitud"
          "/api_creditos/parametros")
CONTENIDO = {"consumo": "politicas/consumo", "cupo": "politicas/cupo_credito"}
FORMULARIO = {"consumo": "v2/forms/politicas_consumo", "cupo": "v2/forms/politicas_cupo"}
# El switch pregunta_<x> es duenio de check_afirmativo_<x> y check_negativo_<x>
# (policiesContentMapper.ts).
SI, NO = "true", "false"
# Tamano de lo que se toca, en px CSS: 44 es lo recomendado (WCAG 2.5.5; Android
# pide 48 dp) y 24 el minimo de WCAG 2.2 AA (2.5.8).
TOQUE_RECOMENDADO = 44
TOQUE_MINIMO = 24
LETRA_MINIMA = 12


def necesita_clave(opciones):
    return hp.necesita_clave(opciones) and not opciones.get("conectar")


def url_inicial(opciones):
    return hp.url_inicial(opciones)


def check(ok, nombre, detalle=""):
    (log.pass_ if ok else log.fail)(nombre + (" -- " + detalle if detalle else ""))
    return ok


# -- lo esperado, desde Drupal
def get_json(driver, ruta):
    respuesta = driver.context.request.get("%s/%s" % (DRUPAL, ruta), timeout=20000)
    if not respuesta.ok:
        raise AssertionError("Drupal %s respondio %s" % (ruta, respuesta.status))
    return respuesta.json()


def partir_politicas(politicas):
    """Como parsePolicies del front: Drupal no escapa las comillas del rich
    text, asi que el arreglo casi nunca es JSON valido."""
    try:
        lista = json.loads(politicas)
    except (TypeError, ValueError):
        lista = re.sub(r'"\]$', "", re.sub(r'^\["', "", (politicas or "").strip())).split('","')
    return [p for p in lista if isinstance(p, str) and p.strip()]


def documento_de(rich_text):
    enlace = re.search(r'href="([^"]+)"', rich_text)
    texto = html.unescape(re.sub(r"<[^>]+>", " ", rich_text))
    return re.sub(r"\s+", " ", texto).strip(), enlace.group(1) if enlace else None


def contenido_drupal(driver, producto):
    contenido = get_json(driver, CONTENIDO[producto])
    contenido = contenido[0] if isinstance(contenido, list) else contenido
    campos = get_json(driver, FORMULARIO[producto])
    por_id = {c["id"]: c for c in campos}
    esp = {"titulo": contenido.get("titulo", "").strip(),
           "documentos": [documento_de(p) for p in partir_politicas(contenido.get("politicas"))],
           "pregunta": None}
    condicionales = set()
    for campo in campos:
        if campo.get("type") != "switch":
            continue
        nombre = campo["id"].replace("pregunta_", "", 1)
        condicionales |= {"check_afirmativo_" + nombre, "check_negativo_" + nombre}
        lista = {o["code"]: o["desc"] for o in get_json(driver, "v2/listas/" + campo["values"])}
        esp.update(pregunta=campo["label"].strip(), opciones=list(lista.values()),
                   si=lista.get(SI), no=lista.get(NO),
                   declaracion_si=por_id.get("check_afirmativo_" + nombre, {}).get("label", ""),
                   declaracion_no=por_id.get("check_negativo_" + nombre, {}).get("label", ""))
    esp["aceptaciones"] = [c["label"].strip() for c in campos
                           if c.get("type") == "checkbox" and c["id"] not in condicionales]
    return esp


def estado_enlace(driver, href):
    try:
        return driver.context.request.get(href, timeout=20000).status
    except Exception:
        return None


# -- las pruebas
def probar_contenido(pagina, driver, esp):
    titulo = pagina.get_title()
    check(titulo == esp["titulo"], "Titulo igual a Drupal", repr(titulo))
    docs = pagina.get_documents()
    check(len(docs) == len(esp["documentos"]), "Documentos: %d en pantalla, %d en Drupal"
          % (len(docs), len(esp["documentos"])))
    for (texto, href), (texto_d, href_d) in zip(docs, esp["documentos"]):
        check((texto, href) == (texto_d, href_d), "Documento '%s' igual a Drupal" % texto,
              "" if (texto, href) == (texto_d, href_d) else "Drupal: %r %r" % (texto_d, href_d))
        if not href:
            log.fail("Documento '%s' sin enlace" % texto)
            continue
        status = estado_enlace(driver, href)
        check(status is not None and status < 400, "Enlace de '%s' responde" % texto,
              "%s %s" % (status, href))


def estado_navegacion(pagina_nueva):
    """Status del documento que cargo la pestana (Navigation Timing)."""
    try:
        return pagina_nueva.evaluate(
            "() => (performance.getEntriesByType('navigation')[0] || {}).responseStatus || null")
    except Exception:
        return None


def probar_enlaces_clic(pagina, driver, producto):
    """Clic (toque en movil) de verdad en cada documento: debe abrir el
    documento en una pestana nueva y dejar el evento 1A en el dataLayer."""
    for enlace in pagina.document_links():
        texto = re.sub(r"\s+", " ", enlace.inner_text()).strip()
        href = enlace.get_attribute("href")
        destino = enlace.get_attribute("target")
        check(destino == "_blank", "'%s' abre en pestana nueva (target=_blank)" % texto,
              "target=%r%s" % (destino, ": todos los documentos se abren en la misma pestana "
                               "secundaria" if destino == "about:blank" else ""))
        with driver.context.expect_page(timeout=10000) as info:
            pagina.pulsar(enlace)
        nueva = info.value
        try:
            nueva.wait_for_load_state("load", timeout=20000)
        except Exception:
            pass
        status = estado_navegacion(nueva)
        abre = nueva.url.split("?")[0] == href.split("?")[0]
        check(abre and (status is None or status < 400), "Clic en '%s' abre el documento en "
              "pestana nueva" % texto, "%s %s" % (status, nueva.url[:100]))
        nueva.close()
        eventos = [e["payload"] for e in datalayer.get_events(driver)
                   if isinstance(e.get("payload"), dict) and e["payload"].get("link_text") == texto]
        if check(bool(eventos), "Analitica 1A del clic en '%s'" % texto):
            ultimo = eventos[-1]
            check(ultimo.get("producto") == producto, "1A con producto %s" % producto,
                  "eventName=%s producto=%s" % (ultimo.get("eventName"), ultimo.get("producto")))


def retratar(driver, obs, nombre):
    ruta = os.path.join(obs.dir, "diseno_%s.png" % nombre)
    driver.page.screenshot(path=ruta, full_page=True)
    log.info("Pantallazo: %s" % ruta)


def probar_diseno(pagina, driver, obs):
    """Que la pantalla quepa y se pueda tocar en el ancho del dispositivo."""
    m = pagina.layout()
    check(m["scrollAncho"] <= m["ancho"], "Sin scroll horizontal",
          "contenido %d px en %d px de pantalla" % (m["scrollAncho"], m["ancho"]))
    fuera = [n for n, c in m["elementos"] if c["x"] < -1 or c["r"] > m["ancho"] + 1]
    check(not fuera, "Todo cabe a lo ancho (%d px)" % m["ancho"], ", ".join(fuera))
    check(m["letraMinima"] >= LETRA_MINIMA, "Letra minima %.0f px (>= %d)"
          % (m["letraMinima"], LETRA_MINIMA))
    continuar = [c for n, c in m["elementos"] if n == "Continuar"]
    check(len(continuar) == 1, "Se ve un solo boton Continuar", "%d visibles" % len(continuar))
    if driver.dispositivo:
        for nombre, c in m["elementos"]:
            if not nombre.startswith(("opcion", "casilla", "Continuar")):
                continue
            lado = min(c["w"], c["h"])
            medida = "%s mide %.0fx%.0f px" % (nombre, c["w"], c["h"])
            if lado < TOQUE_MINIMO:
                log.fail("Tamano para tocar: %s (minimo %d)" % (medida, TOQUE_MINIMO))
            elif lado < TOQUE_RECOMENDADO:
                log.warning("Tamano para tocar: %s, menos de los %d recomendados"
                            % (medida, TOQUE_RECOMENDADO))
            else:
                log.pass_("Tamano para tocar: %s" % medida)
    retratar(driver, obs, "al_entrar")


def probar_accesibilidad(pagina, driver):
    """Lo que no se ve: nombre de las casillas, estado de Si/No y que el
    texto de la casilla tambien la marque."""
    a = pagina.accessibility()
    for i, c in enumerate(a["casillas"]):
        check(bool(c["etiquetas"] or c["ariaLabel"] or c["ariaLabelledby"]),
              "Casilla %d tiene nombre accesible (label o aria-label; WCAG 4.1.2)" % (i + 1), str(c))
    con_estado = [o["texto"] for o in a["opciones"]
                  if o["ariaPressed"] is not None or o["ariaChecked"] is not None]
    check(len(con_estado) == len(a["opciones"]), "Si/No exponen cual esta elegida "
          "(aria-pressed o radio; WCAG 4.1.2)", "%s" % a["opciones"])
    pagina.pulsar(pagina.checkbox_text(0))
    driver.page.wait_for_timeout(300)
    marcada = pagina.get_checkboxes()[0][1]
    check(marcada, "%s el texto de la declaracion marca la casilla"
          % ("Tocar" if driver.dispositivo else "Clic en"))
    if marcada:
        pagina.set_checkbox(0, False)


def probar_habilitacion(pagina, momento):
    """Continuar se habilita solo con todas las casillas marcadas."""
    n = len(pagina.get_checkboxes())
    for i in range(n):
        for j in range(n):
            pagina.set_checkbox(j, j == i)
        if n > 1:
            check(not pagina.continue_enabled(), "%s: Continuar sigue deshabilitado con solo "
                  "la casilla %d marcada" % (momento, i + 1))
    for j in range(n):
        pagina.set_checkbox(j, True)
    check(pagina.continue_enabled(), "%s: Continuar se habilita con las %d casillas marcadas"
          % (momento, n))


def probar_cambio_respuesta(pagina, esp):
    """Al cambiar Si/No cambia la declaracion y se desmarca (solo ella)."""
    for opcion, declaracion in ((esp["si"], esp["declaracion_si"]),
                                (esp["no"], esp["declaracion_no"])):
        pagina.select_option(opcion)
        elegidas = [t for t, sel in pagina.get_options() if sel]
        check(elegidas == [opcion], "Queda marcada solo '%s'" % opcion, "marcadas=%s" % elegidas)
        casillas = pagina.get_checkboxes()
        check(casillas[0][0] == declaracion, "Con '%s' la declaracion es la de Drupal" % opcion,
              repr(casillas[0][0]))
        check(not casillas[0][1], "Con '%s' la declaracion queda desmarcada" % opcion)
        check(all(m for _, m in casillas[1:]), "Con '%s' la aceptacion de politicas sigue "
              "marcada" % opcion)
        check(not pagina.continue_enabled(), "Con '%s' Continuar vuelve a deshabilitarse" % opcion)
        pagina.set_checkbox(0, True)
        check(pagina.continue_enabled(), "Con '%s' y todo marcado, Continuar se habilita" % opcion)


def probar_teclado(pagina, driver, esp):
    teclado = driver.page.keyboard
    pagina.option(esp["si"]).first.focus()
    teclado.press("Enter")
    driver.page.wait_for_timeout(300)
    elegidas = [t for t, sel in pagina.get_options() if sel]
    check(elegidas == [esp["si"]], "Teclado: Enter sobre '%s' la elige" % esp["si"],
          "marcadas=%s" % elegidas)
    pagina.checkbox(0).focus()
    teclado.press("Space")
    driver.page.wait_for_timeout(300)
    check(pagina.get_checkboxes()[0][1], "Teclado: Espacio marca la declaracion")
    pagina.option(esp["no"]).first.focus()
    teclado.press("Enter")
    driver.page.wait_for_timeout(300)
    elegidas = [t for t, sel in pagina.get_options() if sel]
    check(elegidas == [esp["no"]], "Teclado: Enter sobre '%s' la elige" % esp["no"],
          "marcadas=%s" % elegidas)


def continuar(pagina, driver, obs, producto, respuesta_si):
    with driver.page.expect_response(
            lambda r: "/request/validate" in r.url and r.request.method == "POST",
            timeout=60000) as info:
        pagina.click_continue()
    respuesta = info.value
    body = respuesta.request.post_data_json or {}
    log.info("Request %s: %s" % (respuesta.url, json.dumps(body, ensure_ascii=False)))
    if producto == "consumo":
        esperado = {"preguntaDeclaracionAsegurabilidad": respuesta_si,
                    "aceptacionDeclaracionAsegurabilidad": True, "aceptacionPoliticas": True}
        check(body.get("politicasConsumo") == esperado, "politicasConsumo del request",
              json.dumps(body.get("politicasConsumo")))
        check(body.get("grupoProducto") == "CONSUMO", "grupoProducto CONSUMO",
              repr(body.get("grupoProducto")))
    else:
        check(body.get("grupoProducto") == "CUPO" and bool(body.get("tipoSolicitud")),
              "Cupo: grupoProducto CUPO con tipoSolicitud",
              "grupoProducto=%r tipoSolicitud=%r" % (body.get("grupoProducto"),
                                                    body.get("tipoSolicitud")))
    # el cuerpo se toma de lo que registra el observador: respuesta.text()
    # espera al ultimo byte y con los 500 de dev se quedaba minutos colgado
    hp.esperar(driver, obs, 12)
    reg = next((r for paso in reversed(obs.pasos) for r in reversed(paso["requests"])
                if "/request/validate" in r["url"]), {})
    texto = reg.get("response_body") or ""
    check(respuesta.status == 202, "validate responde 202",
          "%s %s" % (respuesta.status, texto[:500] or reg.get("nota") or ""))
    caso = re.search(r'"idCaso"\s*:\s*"?(\d+)', texto)
    if caso:
        log.warning("Se creo el caso %s en Bizagi (cancelarlo si no se va a seguir)" % caso.group(1))
    log.info("Despues de Continuar: %s | %s"
             % (driver.page.url, hp.texto_pantalla(driver)[:300]))


def probar_politicas(driver, obs, opciones):
    producto = "cupo" if "/cupo-de-credito/" in driver.page.url else "consumo"
    pagina = PoliciesPage(driver).wait_loaded()
    datalayer.install(driver)
    hp.esperar(driver, obs, 1)
    esp = contenido_drupal(driver, producto)
    log.info("Dispositivo: %s" % (driver.dispositivo or "escritorio"))

    probar_contenido(pagina, driver, esp)
    probar_enlaces_clic(pagina, driver, producto)
    probar_diseno(pagina, driver, obs)
    probar_accesibilidad(pagina, driver)
    if esp["pregunta"]:
        check(pagina.get_question() == esp["pregunta"], "Pregunta igual a Drupal",
              repr(pagina.get_question()))
        opciones_ui = pagina.get_options()
        check([t for t, _ in opciones_ui] == esp["opciones"], "Opciones iguales a Drupal",
              "%s" % [t for t, _ in opciones_ui])
        check([t for t, sel in opciones_ui if sel] == [esp["no"]],
              "'%s' marcada por defecto" % esp["no"])
    casillas = pagina.get_checkboxes()
    esperadas = ([esp["declaracion_no"]] if esp["pregunta"] else []) + esp["aceptaciones"]
    check([t for t, _ in casillas] == esperadas, "Casillas con los textos de Drupal",
          "%s" % [t for t, _ in casillas])
    check(not any(m for _, m in casillas), "Casillas sin marcar al entrar")
    check(not pagina.continue_enabled(), "Continuar deshabilitado al entrar")
    log.info("Botones Continuar (visible, habilitado): %s" % pagina.get_continue_buttons())

    probar_habilitacion(pagina, "Respuesta por defecto")
    if esp["pregunta"]:
        probar_cambio_respuesta(pagina, esp)
        if driver.dispositivo:
            log.info("Teclado: no aplica en movil (se prueba en escritorio)")
        else:
            probar_teclado(pagina, driver, esp)
        pagina.select_option(esp["si"])
        for i in range(len(pagina.get_checkboxes())):
            pagina.set_checkbox(i, True)
        retratar(driver, obs, "si_todo_marcado")

    # queda listo para Continuar con la respuesta pedida
    respuesta_si = bool(esp["pregunta"]) and opciones.get("respuesta") == "si"
    if esp["pregunta"]:
        pagina.select_option(esp["si"] if respuesta_si else esp["no"])
    for i in range(len(pagina.get_checkboxes())):
        pagina.set_checkbox(i, True)
    check(pagina.continue_enabled(), "Formulario listo para Continuar (respuesta %s)"
          % ("Si" if respuesta_si else "No"))
    retratar(driver, obs, "listo_para_continuar")
    if opciones.get("continuar"):
        continuar(pagina, driver, obs, producto, respuesta_si)
    else:
        log.info("Sin --continuar: no se pulsa Continuar (crearia el caso)")


def identificar_sesion(driver, usuario, opciones):
    """Con --conectar: el documento y el producto salen de la sesion abierta."""
    token = driver.cookies().get("userToken")
    cliente = (decode_jwt(token).get("customer") or {}) if token else {}
    if cliente.get("documentNumber"):
        usuario.tipo = {2: "CC", 3: "CE"}.get(cliente.get("documentType"), usuario.tipo)
        usuario.numero = str(cliente["documentNumber"])
        log.info("Sesion abierta de %s en %s" % (usuario.documento, driver.page.url))
    else:
        log.warning("La sesion abierta no tiene cookie userToken")
    m = re.search(r"/consumo/([^/]+)/", driver.page.url)
    if m:
        opciones.update(entrada="consumo", slug=m.group(1))
    elif "/cupo-de-credito/" in driver.page.url:
        opciones.update(entrada="cupo")


def run(driver, usuario, opciones):
    if opciones.get("conectar"):
        identificar_sesion(driver, usuario, opciones)

    def pasos(obs):
        if opciones.get("conectar"):
            if not driver.page.url.split("?")[0].rstrip("/").endswith("/politicas"):
                log.fail("La sesion del puerto %d no esta en politicas: %s"
                         % (opciones["conectar"], driver.page.url))
                return
        elif hp.llegar_a_politicas(driver, obs, usuario, opciones) != "politicas":
            return
        probar_politicas(driver, obs, opciones)

    hp.capturar(driver, usuario, opciones, "politicas-225427", pasos)

"""Runner: hace lo de las suites testng-*.xml + BaseTest.

  python -m colsubsidio_flow tests
  python -m colsubsidio_flow cedulas listar [GRUPO]
  python -m colsubsidio_flow cedulas agregar GRUPO CC:123 [--nota "..."]
  python -m colsubsidio_flow cedulas quitar GRUPO CC:123
  python -m colsubsidio_flow login-credito-light [--documento CC:123] [--capturas DIR]
  python -m colsubsidio_flow consumo-225423 [--documento CC:123] [--entrada cupo] [--hasta-login]
  python -m colsubsidio_flow hasta-politicas [--documento CC:123] [--slug mujeres|--entrada cupo]
                                             [--sesion clave [--clave X]] [--cdp 9333] [--headless]
  python -m colsubsidio_flow politicas-225427 [--documento CC:123 | --conectar 9333]
                                              [--respuesta si] [--continuar] [--directo]
                                              [--dispositivo "Pixel 7"]
  python -m colsubsidio_flow e2e [--documento CC:123] [--slug mujeres|--entrada cupo]
                                [--hasta politicas|informacion-personal|...|fin] [--rapido]
                                [--dejar-abierto] [--lento 500]

Sin --documento corre todas las cedulas del data provider del test (o del
--grupo indicado), una tras otra, cada una con su navegador. La clave sale de
--clave, del panel (~/.panel_qa/usuarios_prueba.json) o de COLS_CLAVE; si no
esta, se pide por consola y no se muestra.

--cdp deja el navegador abierto y expuesto en ese puerto al terminar, y
--conectar corre el test sobre ese navegador sin abrir otro: uno se loguea
con su clave (hasta-politicas --sesion clave --cdp 9333) y otro proceso prueba
politicas sobre la misma sesion (politicas-225427 --conectar 9333).
"""
import argparse
import getpass
import json
import sys

from .core import reporte
from .core.driver import Driver
from .data import data_provider as dp
from .pages import LoginCreditoPage
from .tests import TESTS
from .tests.e2e_test import PANTALLAS as PANTALLAS_E2E


def parse_documento(texto):
    tipo, _, numero = (texto or "").partition(":")
    tipo = {"CO1C": "CC", "CO1E": "CE"}.get(tipo.strip().upper(), tipo.strip().upper())
    if tipo not in dp.TIPOS or not numero.strip().isdigit():
        raise argparse.ArgumentTypeError("se espera TIPO:NUMERO (CC o CE), llego %r" % texto)
    return dp.Usuario(tipo, numero.strip())


def cmd_tests(_args):
    for nombre, modulo in TESTS.items():
        print("%-22s testID %-7s data provider: %-15s %s"
              % (nombre, modulo.TEST_ID, modulo.DATA_PROVIDER, modulo.URL))


def cmd_cedulas(args):
    if args.accion == "agregar":
        u = parse_documento(args.documento)
        dp.agregar(args.grupo, u.tipo, u.numero, args.nota or "",
                   json.loads(args.esperado) if args.esperado else None)
        print("Agregada %s a '%s'" % (u.documento, args.grupo))
        return 0
    if args.accion == "quitar":
        u = parse_documento(args.documento)
        n = dp.quitar(args.grupo, u.tipo, u.numero)
        print("Quitadas %d filas de '%s'" % (n, args.grupo))
        return 0
    for nombre in ([args.grupo] if args.grupo else dp.grupos()):
        usuarios = dp.con_claves(dp.grupo(nombre))
        print("\n%s (%d)" % (nombre, len(usuarios)))
        for u in usuarios:
            print("  %-14s clave:%-3s %s%s" % (u.documento, "si" if u.clave else "no", u.nota,
                                              "  esperado=%s" % json.dumps(u.esperado)
                                              if u.esperado else ""))
    return 0


def pedir_claves(usuarios, clave=None):
    for u in dp.con_claves(usuarios):
        u.clave = clave or u.clave
        if not u.clave:
            u.clave = getpass.getpass("Clave de %s (no se muestra): " % u.documento)
    return usuarios


def esperar_enter():
    try:
        input("Enter para cerrar el navegador...")
    except EOFError:
        pass             # sin consola (stdin cerrado): se cierra de una


def cmd_correr(args):
    modulo = TESTS[args.test]
    if args.conectar and not args.documento:
        # el documento es el de la sesion abierta; el test lo lee del token
        usuarios = [dp.Usuario("CC", "sesion", "sesion del puerto %d" % args.conectar)]
    else:
        usuarios = args.documento or dp.grupo(args.grupo or modulo.DATA_PROVIDER)
        if args.documento:
            # la nota y el esperado salen del data provider si la cedula esta ahi
            try:
                conocidas = {u.documento: u for u in dp.grupo(args.grupo or modulo.DATA_PROVIDER)}
            except KeyError:
                conocidas = {}
            for u in usuarios:
                if u.documento in conocidas:
                    u.nota, u.esperado = conocidas[u.documento].nota, conocidas[u.documento].esperado
    if not usuarios:
        print("El data provider no tiene cedulas.")
        return 2
    opciones = {"hasta_login": args.hasta_login, "entrada": args.entrada, "slug": args.slug,
                "base": args.base, "espera": args.espera, "sin_biometria": args.sin_biometria,
                "sesion": args.sesion, "conectar": args.conectar, "respuesta": args.respuesta,
                "continuar": args.continuar, "directo": args.directo, "hasta": args.hasta,
                "rapido": args.rapido, "dejar_abierto": args.dejar_abierto}
    necesita_clave = getattr(modulo, "necesita_clave", lambda _o: True)
    if not args.hasta_login and necesita_clave(opciones):
        pedir_claves(usuarios, args.clave)

    url = args.url or (modulo.url_inicial(opciones) if hasattr(modulo, "url_inicial")
                       else modulo.URL)
    resultados = []
    for u in usuarios:
        print("\n=== %s | %s | %s" % (modulo.NOMBRE, u.documento, url))
        rep = reporte.iniciar("%s %s" % (modulo.NOMBRE, u.documento))
        driver = Driver(headless=args.headless, capturas=args.capturas, cdp=args.cdp,
                        conectar=args.conectar, dispositivo=args.dispositivo, lento=args.lento)
        try:
            driver.init_driver(url)
            if args.hasta_login and not getattr(modulo, "MANEJA_HASTA_LOGIN", False):
                LoginCreditoPage(driver).wait_form_visible()
            else:
                modulo.run(driver, u, opciones)
        except AssertionError as e:
            reporte.fail(str(e))
        except Exception as e:
            reporte.fail("Excepcion: %s" % str(e).strip().split("\n")[0])
        finally:
            if args.cdp:
                print("\nNavegador abierto en el puerto %d. Para seguir sobre esta sesion:"
                      % args.cdp)
                print("  python -m colsubsidio_flow politicas-225427 --conectar %d" % args.cdp)
                esperar_enter()
            elif (args.dejar_abierto and not args.headless
                  and not getattr(modulo, "MANEJA_DEJAR_ABIERTO", False)):
                esperar_enter()
            driver.quit_driver()
            rep.terminar()
        resultados.append((u, rep))

    if hasattr(modulo, "al_terminar"):
        modulo.al_terminar(opciones)
    print("\n=== Resumen %s" % modulo.NOMBRE)
    for u, rep in resultados:
        print("  %-14s %-5s %2d fallas  %5.0fs  %s"
              % (u.documento, "OK" if rep.ok else "FALLA", len(rep.fallas), rep.duracion(), u.nota))
        for f in rep.fallas:
            print("      - %s" % f)
    return 0 if all(rep.ok for _, rep in resultados) else 1


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m colsubsidio_flow",
                                 description="Tests UI de solicitud de credito (puerto de colsubsidioFramework)")
    sub = ap.add_subparsers(dest="comando", required=True)

    sub.add_parser("tests", help="lista los tests disponibles")

    ced = sub.add_parser("cedulas", help="ver o editar las cedulas de los data providers")
    ced.add_argument("accion", nargs="?", default="listar", choices=("listar", "agregar", "quitar"))
    ced.add_argument("grupo", nargs="?", help="data provider (ej. login_credito)")
    ced.add_argument("documento", nargs="?", help="TIPO:NUMERO, para agregar/quitar")
    ced.add_argument("--nota", help="nota al agregar")
    ced.add_argument("--esperado", metavar="JSON",
                     help='resultado esperado al agregar, p. ej. \'{"sap": "OK", "pantalla": "politicas"}\'')

    for nombre, modulo in TESTS.items():
        p = sub.add_parser(nombre, help=(modulo.__doc__ or "").strip().split("\n")[0])
        p.set_defaults(test=nombre)
        p.add_argument("--documento", action="append", type=parse_documento,
                       help="TIPO:NUMERO; se puede repetir. Sin esto usa el data provider")
        p.add_argument("--grupo", help="otro data provider de cedulas.json")
        p.add_argument("--url", help="URL inicial (default: la del test)")
        p.add_argument("--headless", action="store_true")
        p.add_argument("--dispositivo", metavar="NOMBRE",
                       help="emula ese telefono de Playwright, p. ej. \"Pixel 7\", \"Galaxy S24\", "
                            "\"Galaxy S9+\" (Chrome de Android emulado)")
        p.add_argument("--lento", type=int, metavar="MS",
                       help="milisegundos de pausa antes de cada accion (clic, escribir, ir a "
                            "una URL), para seguirlo en vivo; p. ej. 500")
        p.add_argument("--capturas", metavar="DIR", help="guardar pantallazos en DIR")
        p.add_argument("--hasta-login", action="store_true",
                       help="se detiene en el formulario de login (no pide clave)")
        p.add_argument("--dejar-abierto", action="store_true",
                       help="espera Enter antes de cerrar el navegador. e2e: deja la pantalla "
                            "donde se detuvo con el observador grabando; el reporte se escribe "
                            "al cerrar la ventana (o con Enter)")
        p.add_argument("--entrada", choices=("consumo", "cupo"), default="consumo",
                       help="consumo-225423/hasta-politicas: por que Onboarding entrar")
        p.add_argument("--slug", default="libre-inversion",
                       help="consumo-225423/hasta-politicas: subproducto")
        p.add_argument("--base", help="consumo-225423/hasta-politicas: URL base del front")
        p.add_argument("--espera", type=int,
                       help="segundos de espera tras el login: que se asiente la pantalla "
                            "(consumo-225423, 40) o que llegue a politicas (hasta-politicas, 90)")
        p.add_argument("--sesion", choices=("token", "clave"), default="token",
                       help="hasta-politicas/politicas-225427: token = sin clave, JWT de "
                            "token/ciam guardado como lo hace el front; clave = login de Gigya")
        p.add_argument("--clave", help="clave del usuario (si no: panel, COLS_CLAVE o se "
                                       "pide). Queda en el historial de la consola")
        p.add_argument("--cdp", type=int, metavar="PUERTO",
                       help="al terminar deja el navegador abierto y expuesto en ese puerto, "
                            "para que otro test siga con --conectar")
        p.add_argument("--conectar", type=int, metavar="PUERTO",
                       help="no abre navegador: corre sobre la sesion abierta en ese puerto")
        p.add_argument("--respuesta", choices=("no", "si"), default="no",
                       help="politicas-225427: respuesta de salud con la que queda el formulario")
        p.add_argument("--continuar", action="store_true",
                       help="politicas-225427: pulsa Continuar al final (CREA EL CASO en Bizagi)")
        p.add_argument("--directo", action="store_true",
                       help="politicas-225427 con --sesion token: entra a politicas sin pasar "
                            "por validaciones (cookie validationsSuccess)")
        p.add_argument("--sin-biometria", action="store_true",
                       help="login-credito/e2e: no llamar biometria por API")
        p.add_argument("--hasta", choices=PANTALLAS_E2E[1:], default="politicas",
                       help="e2e: pantalla donde se detiene, sin tocar nada en ella. Mas alla "
                            "de politicas pulsa Continuar (CREA EL CASO en Bizagi)")
        p.add_argument("--rapido", action="store_true",
                       help="e2e: en politicas solo marca y sigue (sin las pruebas de 225427)")

    args = ap.parse_args(argv)
    if args.comando == "tests":
        return cmd_tests(args)
    if args.comando == "cedulas":
        if args.accion != "listar":
            if not (args.grupo and args.documento):
                ap.error("cedulas %s necesita GRUPO y TIPO:NUMERO" % args.accion)
            try:
                parse_documento(args.documento)
            except argparse.ArgumentTypeError as e:
                ap.error(str(e))
        return cmd_cedulas(args)
    return cmd_correr(args)


if __name__ == "__main__":
    sys.exit(main())

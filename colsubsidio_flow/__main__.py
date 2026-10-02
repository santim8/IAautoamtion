"""Runner: hace lo de las suites testng-*.xml + BaseTest.

  python -m colsubsidio_flow tests
  python -m colsubsidio_flow cedulas listar [GRUPO]
  python -m colsubsidio_flow cedulas agregar GRUPO CC:123 [--nota "..."]
  python -m colsubsidio_flow cedulas quitar GRUPO CC:123
  python -m colsubsidio_flow login-credito-light [--documento CC:123] [--capturas DIR]
  python -m colsubsidio_flow consumo-225423 [--documento CC:123] [--entrada cupo] [--hasta-login]

Sin --documento corre todas las cedulas del data provider del test (o del
--grupo indicado), una tras otra, cada una con su navegador. La clave sale del
panel (~/.panel_qa/usuarios_prueba.json) o de COLS_CLAVE; si no esta, se pide
por consola y no se muestra.
"""
import argparse
import getpass
import sys

from .core import reporte
from .core.driver import Driver
from .data import data_provider as dp
from .pages import LoginCreditoPage
from .tests import TESTS


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
        dp.agregar(args.grupo, u.tipo, u.numero, args.nota or "")
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
            print("  %-14s clave:%-3s %s" % (u.documento, "si" if u.clave else "no", u.nota))
    return 0


def pedir_claves(usuarios):
    for u in dp.con_claves(usuarios):
        if not u.clave:
            u.clave = getpass.getpass("Clave de %s (no se muestra): " % u.documento)
    return usuarios


def cmd_correr(args):
    modulo = TESTS[args.test]
    usuarios = args.documento or dp.grupo(args.grupo or modulo.DATA_PROVIDER)
    if not usuarios:
        print("El data provider no tiene cedulas.")
        return 2
    if not args.hasta_login:
        pedir_claves(usuarios)

    opciones = {"hasta_login": args.hasta_login, "entrada": args.entrada, "slug": args.slug,
                "base": args.base, "espera": args.espera, "sin_biometria": args.sin_biometria}
    url = args.url or (modulo.url_inicial(opciones) if hasattr(modulo, "url_inicial")
                       else modulo.URL)
    resultados = []
    for u in usuarios:
        print("\n=== %s | %s | %s" % (modulo.NOMBRE, u.documento, url))
        rep = reporte.iniciar("%s %s" % (modulo.NOMBRE, u.documento))
        driver = Driver(headless=args.headless, capturas=args.capturas)
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
            if args.dejar_abierto and not args.headless:
                input("Enter para cerrar el navegador...")
            driver.quit_driver()
        resultados.append((u, rep))

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

    for nombre, modulo in TESTS.items():
        p = sub.add_parser(nombre, help=(modulo.__doc__ or "").strip().split("\n")[0])
        p.set_defaults(test=nombre)
        p.add_argument("--documento", action="append", type=parse_documento,
                       help="TIPO:NUMERO; se puede repetir. Sin esto usa el data provider")
        p.add_argument("--grupo", help="otro data provider de cedulas.json")
        p.add_argument("--url", help="URL inicial (default: la del test)")
        p.add_argument("--headless", action="store_true")
        p.add_argument("--capturas", metavar="DIR", help="guardar pantallazos en DIR")
        p.add_argument("--hasta-login", action="store_true",
                       help="se detiene en el formulario de login (no pide clave)")
        p.add_argument("--dejar-abierto", action="store_true",
                       help="espera Enter antes de cerrar el navegador")
        p.add_argument("--entrada", choices=("consumo", "cupo"), default="consumo",
                       help="consumo-225423: por que Onboarding entrar")
        p.add_argument("--slug", default="libre-inversion", help="consumo-225423: subproducto")
        p.add_argument("--base", help="consumo-225423: URL base del front")
        p.add_argument("--espera", type=int, default=40,
                       help="consumo-225423: segundos para que se asiente la pantalla post-login")
        p.add_argument("--sin-biometria", action="store_true",
                       help="login-credito: no llamar biometria por API al final")

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

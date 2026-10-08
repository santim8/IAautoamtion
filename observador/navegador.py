"""El Chrome de QA: lanzarlo con CDP y dejarlo como recien abierto."""
import os
import subprocess

from observador.config import SCRIPT
from observador.util import es_url_real


def lanzar_chrome(puerto):
    """Abre Chrome con puerto de depuracion y perfil aparte (el login persiste)."""
    candidatos = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]
    exe = next((c for c in candidatos if os.path.exists(c)), None)
    if not exe:
        print("No encontre chrome.exe. Lanzalo a mano con:")
        print(f'  chrome.exe --remote-debugging-port={puerto} '
              r'--user-data-dir="%USERPROFILE%\.chrome-qa-debug"')
        return 1
    perfil = os.path.join(os.path.expanduser("~"), ".chrome-qa-debug")
    os.makedirs(perfil, exist_ok=True)
    subprocess.Popen([exe, f"--remote-debugging-port={puerto}",
                      f"--user-data-dir={perfil}", "--no-first-run",
                      "--no-default-browser-check"])
    print(f"Chrome lanzado en el puerto {puerto} con perfil {perfil}")
    print("Es un perfil aparte: la primera vez toca loguearte de nuevo.")
    print("\nEste script ya termino; Chrome queda abierto. Ahora:")
    print(f"  python {SCRIPT} --flujo \"mi-flujo\"")
    return 0


def origenes_app(hosts, paginas):
    """Origenes cuyo almacenamiento hay que vaciar.

    Los hosts del backend mas el de la pestana que este abierta: la sesion no
    vive solo en la app, tambien en el proveedor de SSO que la autentica.
    """
    origenes = {"https://%s" % h for h in hosts if "." in h}
    for pg in paginas:
        try:
            partes = (pg.url or "").split("/")
            if len(partes) > 2 and partes[0].startswith("http"):
                origenes.add("%s//%s" % (partes[0], partes[2]))
        except Exception:
            continue
    return sorted(origenes)


def limpiar_navegador(browser, paginas, hosts):
    """Deja el navegador como recien abierto: sin cookies, cache ni storage.

    Es el equivalente a abrir una ventana de incognito, pero sobre el Chrome que
    ya esta conectado: crear un contexto de incognito por CDP no es algo que
    Playwright permita sobre un navegador al que solo se engancho.
    """
    if not paginas:
        return
    pagina = paginas[0]
    borrados = []
    try:
        sesion = pagina.context.new_cdp_session(pagina)
    except Exception as e:
        print("! No pude abrir sesion CDP para limpiar: %s" % e)
        return
    for comando in ("Network.clearBrowserCookies", "Network.clearBrowserCache"):
        try:
            sesion.send(comando)
            borrados.append(comando.split(".")[1])
        except Exception as e:
            print("! %s fallo: %s" % (comando, e))
    n = 0
    for origen in origenes_app(hosts, paginas):
        try:
            sesion.send("Storage.clearDataForOrigin",
                        {"origin": origen, "storageTypes": "all"})
            n += 1
        except Exception:
            continue          # origen que Chrome no reconoce: no es un problema
    # sessionStorage es por pestana, no por origen: Storage.clearDataForOrigin
    # no lo toca y sobrevivia a la limpieza. Hay que vaciarlo desde la pagina.
    vaciadas = 0
    for pg in paginas:
        try:
            if not es_url_real(pg.url):
                continue
            pg.evaluate("() => { try { sessionStorage.clear(); } catch (e) {}"
                        " try { localStorage.clear(); } catch (e) {} }")
            vaciadas += 1
        except Exception:
            continue
    print("Limpieza: %s, storage de %d origen(es), %d pestana(s) vaciadas."
          % (", ".join(borrados) or "nada", n, vaciadas))
    # sin recargar, la pagina sigue con la sesion viva en memoria
    for pg in paginas:
        try:
            if es_url_real(pg.url):
                pg.reload(wait_until="domcontentloaded", timeout=15000)
        except Exception:
            continue

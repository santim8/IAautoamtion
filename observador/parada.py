"""Parar desde afuera: el centinela del panel (--stop-file) y el cierre de
emergencia cuando el loop no contesta."""
import os
import sys
import time

from observador.cierre import cerrar, ya_cerrado

# Lo que el panel escribe en el centinela para parar SIN generar el reporte.
SIN_REPORTE = "sin-reporte"


def modo_parada(stop_file):
    """Que pidio quien escribio el centinela: parar y reportar, o solo parar."""
    try:
        with open(stop_file, encoding="utf-8") as f:
            return f.read().strip().lower()
    except OSError:
        return ""


def avisar_pendiente(obs):
    """Corrida detenida a proposito sin reporte: la evidencia cruda ya esta."""
    try:
        obs.pantallazos.volcar()
    except (AttributeError, OSError):
        pass
    print("\nDetenido sin generar el reporte.")
    print("Evidencia: " + os.path.abspath(obs.dir))
    print("Cuando quieras el reporte:  --rehacer-reporte \"%s\""
          % os.path.abspath(obs.dir))


def vigilar_parada(obs, flujo, ruta_esquemas, generar, stop_file, gracia=20):
    """Escribe el reporte aunque el loop no conteste al centinela.

    Playwright puede quedarse leyendo el cuerpo de una respuesta que nunca
    termina, o hablando con una pestana que se colgo. En ese caso el loop no
    vuelve a mirar el centinela y la corrida se quedaria sin reporte pese a
    tener toda la evidencia ya escrita en disco. Este hilo espera un margen y,
    si nadie atendio, cierra el mismo y sale.
    """
    while True:
        time.sleep(1)
        if not os.path.exists(stop_file):
            continue
        limite = time.time() + gracia
        while os.path.exists(stop_file) and time.time() < limite:
            time.sleep(0.5)
        if not os.path.exists(stop_file) or ya_cerrado():
            return                       # el loop lo atendio; todo normal
        if modo_parada(stop_file) == SIN_REPORTE:
            obs.sin_reporte = True
        print("\n! El navegador no responde tras %d s. Salgo%s."
              % (gracia, "" if getattr(obs, "sin_reporte", False)
                 else " y genero el reporte con lo capturado"))
        try:
            os.remove(stop_file)
        except OSError:
            pass
        try:
            if getattr(obs, "sin_reporte", False):
                avisar_pendiente(obs)
            else:
                cerrar(obs, flujo, ruta_esquemas=ruta_esquemas, generar=generar)
        except Exception as e:
            print("! el cierre fallo: %s" % e)
        sys.stdout.flush()
        os._exit(0)     # sin cleanup de Playwright: es justo lo que esta colgado

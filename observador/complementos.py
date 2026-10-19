"""Lo que se suma a la captura sin tocar el nucleo.

Un complemento reacciona a lo que pasa en el flujo (se abrio una pantalla,
respondio un servicio) y puede dejar sus propios registros en la evidencia. La
sonda de /request/check es el primero: el front llama ese endpoint desde su
servidor, asi que el navegador nunca lo ve y hay que preguntarlo aparte.

Para agregar otro: una subclase de Complemento con los ganchos que necesite, y
armarla en cli.armar_complementos. Los ganchos corren en el loop principal
(salvo cerrar y volcar, que tambien corren al cerrar y NO deben tocar
Playwright).
"""
import sonda_check
from observador.config import LOGIN_GIGYA
from observador.endpoints import casan


class Complemento:
    def describir(self):
        """Linea para el banner de arranque, o None."""
        return None

    def paso_abierto(self, obs, paso):
        """Se abrio una pantalla nueva."""

    def respuesta_leida(self, obs, meta, cuerpo):
        """Respondio un request capturado. meta y cuerpo van crudos, sin
        redactar; todavia no se sabe en que paso cae."""

    def respuesta_guardada(self, obs, paso):
        """El ultimo request leido ya quedo guardado en este paso (o None)."""

    def volcar(self, obs):
        """Escribe a la evidencia lo que tenga listo. Corre en cada vuelta del
        loop y al cerrar."""

    def cerrar(self, obs):
        """La captura paro: espera lo que tenga en vuelo (con tope)."""


class ComplementoSonda(Complemento):
    """Consulta /request/check en el login, al detectar el documento y al
    llegar a informacion personal (ver sonda_check.py)."""

    def __init__(self, sonda):
        self.sonda = sonda           # sonda_check.SondaCheck ya arrancada
        self._doc_nuevo = False
        self._doc_login = False

    def describir(self):
        return ("/request/check: al inicio y en informacion personal, con %s"
                % ("%s %s" % self.sonda.doc if self.sonda.doc
                   else "el documento que aparezca en el trafico"))

    def paso_abierto(self, obs, paso):
        if sonda_check.PANTALLA_CASO in paso["url"]:
            # aqui el caso ya existe: es la segunda y ultima consulta
            self.sonda.pedir(paso, "informacion personal", una_vez=True)
        elif not self.sonda.motivos:
            # con --documento no hay "documento detectado": el inicio va aqui
            self.sonda.pedir(paso, "inicio", una_vez=True)

    def respuesta_leida(self, obs, meta, cuerpo):
        # se lee antes de redactar, sobre el body crudo
        self._doc_nuevo = self.sonda.aprender(meta["request_body"])
        self._doc_login = (bool(casan([LOGIN_GIGYA], meta["url"]))
                           and self.sonda.aprender_login(cuerpo))

    def respuesta_guardada(self, obs, paso):
        if self._doc_login:
            # apenas se loguea: si no hay solicitud que retomar responde 404
            self.sonda.pedir(paso, "login", forzar=True)
        if self._doc_nuevo:
            # la pantalla donde aparecio el documento no alcanzo a consultarse
            self.sonda.pedir(paso, "documento detectado", forzar=True)
        self._doc_nuevo = self._doc_login = False

    def volcar(self, obs):
        """Escribe lo que respondio /request/check en el paso que lo pidio.

        Desde el loop, igual que el resto de la evidencia: el hilo de la sonda
        solo hace la llamada HTTP.
        """
        for paso, reg in self.sonda.recoger():
            obs.anotar(paso, reg)
            print("[paso %02d] /request/check (%s) -> %s  %s  [%d ms]"
                  % (paso["idx"], reg["motivo"], reg["status"],
                     sonda_check.linea(reg["check"]), reg["duracion_ms"]))

    def cerrar(self, obs):
        # no toca Playwright: solo HTTP y disco. No hay consulta final: solo
        # se espera lo que siga en vuelo y se guarda lo que respondio.
        if not obs.sin_reporte:
            self.sonda.cerrar(obs.paso_actual())


def armar_sonda(request_check, documento):
    """La sonda de /request/check si se pidio, o None. ValueError si el
    documento no se entiende."""
    if not (request_check or documento):
        return None
    doc = sonda_check.parse_documento(documento) if documento else None
    sonda = sonda_check.SondaCheck(doc)
    if not sonda.arrancar():
        return None          # sin token.txt: se captura igual, sin la sonda
    return ComplementoSonda(sonda)


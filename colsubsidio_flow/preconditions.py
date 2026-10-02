"""TestPreconditions: segmenta el test segun card-validations v2.

Pide el servicio una sola vez por usuario (perezoso) y deja preguntar por el
tipoSolicitud (originacion, aumento, reactivacion) y el estado. Usa el token
CIAM dummy de validaciones_api.py, como el resto de scripts del repo.
"""
from . import _rutas  # noqa: F401
from .core import reporte as log
from .core.enums import TipoSolicitud

import validaciones_api as va  # noqa: E402  (raiz del repo, via _rutas)

URL_V2 = va.BASE_EXT + "/loans/eligibility/external/v2/card-validations"


class TestPreconditions:
    def __init__(self, tipo, numero):
        self.tipo = tipo
        self.numero = numero
        self._resultado = None
        self._consultado = False

    @classmethod
    def for_user(cls, tipo, numero):
        return cls(tipo, numero)

    def resultado(self):
        if not self._consultado:
            self._consultado = True
            try:
                status, cuerpo = va._curl(
                    "POST", URL_V2, headers={"Authorization": va.token_ciam()},
                    body={"documento": {"tipo": va.DOC_TYPE_SERVICES.get(self.tipo.upper(),
                                                                         self.tipo),
                                        "numero": self.numero}})
                if status == 200 and isinstance(cuerpo, dict):
                    self._resultado = cuerpo.get("resultadoValidacion") or {}
                    log.info("Precondition (v2) loaded: estado=%s tipoSolicitud=%s"
                             % (self._resultado.get("estado"),
                                self._resultado.get("tipoSolicitud")))
                else:
                    log.warning("Precondition (v2): non-200 response (%s)" % status)
            except Exception as e:
                log.warning("Precondition (v2) failed: %s" % e)
        return self._resultado or {}

    def get_tipo_solicitud(self):
        return TipoSolicitud.from_codigo(self.resultado().get("tipoSolicitud"))

    def is_tipo_solicitud(self, *tipos):
        return self.get_tipo_solicitud() in tipos

    def is_originacion(self):
        return self.get_tipo_solicitud() == TipoSolicitud.ORIGINACION

    def is_aumento(self):
        return self.get_tipo_solicitud() == TipoSolicitud.AUMENTO

    def is_reactivacion(self):
        return self.get_tipo_solicitud() == TipoSolicitud.REACTIVACION

    def is_v2_estado_ok(self):
        return str(self.resultado().get("estado", "")).upper() == "OK"

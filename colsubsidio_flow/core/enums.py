"""Enums del framework (execution/core/enums)."""
from enum import Enum


class WaitStrategy(Enum):
    CLICKABLE = "CLICKABLE"
    PRESENCE = "PRESENCE"
    VISIBLE = "VISIBLE"
    INVISIBLE = "INVISIBLE"
    NONE = "NONE"


class CategoryType(Enum):
    SMOKE = "SMOKE"
    REGRESSION = "REGRESSION"


class EnumDocumentType(Enum):
    """Codigos del dropdown de tipo de documento del login viejo (ng-value)."""
    CEDULA_CIUDADANIA = "2"
    TARJETA_IDENTIDAD = "4"
    REGISTRO_CIVIL = "5"
    CEDULA_EXTRANJERIA = "3"
    CARNE_DIPLOMATICO = "6"
    PASAPORTE = "7"
    PERMISO_ESPECIAL_PERMANENCIA = "8"
    PERMISO_PROTECCION_TEMPORAL = "9"

    @staticmethod
    def get_code(tipo):
        return CODE_MAP.get(tipo)


CODE_MAP = {
    "CC": EnumDocumentType.CEDULA_CIUDADANIA,
    "TI": EnumDocumentType.TARJETA_IDENTIDAD,
    "RC": EnumDocumentType.REGISTRO_CIVIL,
    "CE": EnumDocumentType.CEDULA_EXTRANJERIA,
    "CD": EnumDocumentType.CARNE_DIPLOMATICO,
    "PA": EnumDocumentType.PASAPORTE,
    "PE": EnumDocumentType.PERMISO_ESPECIAL_PERMANENCIA,
    "PT": EnumDocumentType.PERMISO_PROTECCION_TEMPORAL,
}


class EnumsDropdowns(Enum):
    SOLTERO = "Soltero(a)"
    CASADO = "Casado(a)"
    DIVORCIDO = "Divorciado(a)"
    VIUDO = "Viudo(a)"
    UNION_LIBRE = "Unión Libre"
    PRIMARIA = "Primaria"
    BACHILLERATO = "Bachillerato"
    TECNICO = "Técnico"
    TECNOLOGO = "Tecnólogo"
    UNIVERSITARIO = "Universitario"


class TipoSolicitud(Enum):
    """tipoSolicitud del servicio card-validations v2 (ASCARD-TMS-CUPO)."""
    ORIGINACION = 1
    AUMENTO = 2
    REACTIVACION = 3
    DESCONOCIDO = None

    @staticmethod
    def from_codigo(codigo):
        for tipo in TipoSolicitud:
            if codigo is not None and tipo.value == codigo:
                return tipo
        return TipoSolicitud.DESCONOCIDO

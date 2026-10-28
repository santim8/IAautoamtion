"""Registro de tests: nombre de comando -> modulo.

Cada modulo define NOMBRE, TEST_ID, DATA_PROVIDER (grupo de cedulas.json),
URL (la del testng-*.xml de Java) y run(driver, usuario, opciones).
"""
from . import (ciam_login_datalayer_test, consumo_puntos_entrada_test, e2e_test,
               hasta_politicas_test, login_credito_light_test, login_credito_test,
               politicas_225427_test, validaciones_225425_test)

TESTS = {
    "login-credito": login_credito_test,
    "login-credito-light": login_credito_light_test,
    "ciam-login-datalayer": ciam_login_datalayer_test,
    "consumo-225423": consumo_puntos_entrada_test,
    "hasta-politicas": hasta_politicas_test,
    "politicas-225427": politicas_225427_test,
    "validaciones-225425": validaciones_225425_test,
    "e2e": e2e_test,
}

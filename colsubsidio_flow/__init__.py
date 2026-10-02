"""Puerto a Python (Playwright) de la capa UI de colsubsidioFramework.

Lo que se tradujo, archivo por archivo:

  Java (colsubsidioFramework/src/test/java)          Python (colsubsidio_flow)
  -------------------------------------------------  -----------------------------------
  core/enums/*.java (WaitStrategy, EnumDocumentType,  core/enums.py
    EnumsDropdowns, TipoSolicitud, CategoryType)
  reports/ExtentLogger.java                           core/reporte.py  (consola, sin Extent)
  core/driver/Driver, DriverFactory, DriverManager    core/driver.py
  core/network/NetworkInterceptorManager.java         core/network.py
  utils/DataLayerMonitor.java                         core/datalayer.py
  utils/basePage/BasePage.java + ExplicitWaitFactory  base_page.py
  pages/pagesLoginCredito/LoginCreditoPage.java       pages/login_credito_page.py
  pages/pagesLoginCredito/TermsAndConditionsPage      pages/terms_and_conditions_page.py
  pages/pagesQuotaCredit/requestFlow/RequestCredit..  pages/request_credit_step1.py
  pages/pagesQuotaCredit/SolicitudCreditoOnboarding*  pages/onboarding_page.py (Onboarding actual)
  preconditions/TestPreconditions.java                preconditions.py
  data/DataProviderUtil.java                          data/data_provider.py + data/cedulas.json
  tests/LoginCreditoTest, LoginCreditoLightTest,      tests/*.py
    CiamLoginDataLayerTest
  testng-*.xml + BaseTest                             __main__.py (runner)

Lo que NO se tradujo porque ya tiene equivalente en el repo o no aplica a la UI:
API (ApiTest, ServicesUtils, TokenManager -> validaciones_api.py), biometria
(BiometryFlow -> biometria_api.py), Bizagi (pages/flows -> bizagi_*.py),
reportes Extent/Excel/Google Drive, Magnifai/Figma, simuladores y las suites de
analitica.

Uso: python -m colsubsidio_flow --help
"""

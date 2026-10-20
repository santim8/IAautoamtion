# Contrato Bizagi → plataforma y canal de origen (código, rama develop, 2026-09-25)

Leído con la búsqueda de código de Azure DevOps (ver memoria global `workflow_consultar_azure_devops`).

**Notificación de Bizagi a la plataforma** (`app-cre-loans-request-manager-internal-api`, `LoanNotifyRequestDto`, endpoint de `LoanNotificationController`, sale al front por WebSocket `/event-to-client`): `idCaso`, `noveltyType`, `idProducto`, `documento`, `paso`, `estadoPaso`, `datosAdicionales` (`tipoAfiliacion`, `urlBiometria`, `motivo`, nombres…).
- `paso`: VALIDATION, REQUEST_DATA, BIOMETRY_START, BIOMETRY_RESULT, OFFER_RESULT, OFFER_CONFIG_RESULT, BILLING_DATA, PEP_DATA, ACTIVATION_RESULT, CREATION (el enum de dominio agrega REACTIVATION_RESULT y CREDIT_LIMIT_RESULT).
- `estadoPaso`: OK, AFFILIATE_STATUS, AGE_OUT_OF_RANGE, INVALID_REQUIREMENTS, REQUIRED_WORK_TIME_DEP, REQUIRED_WORK_TIME_IND, REQUEST_IN_PROGRESS, CARD_STATUS, EXECUTION_ERROR, FAIL, RETRY, MANUAL, INVALID_DOCUMENT, EXECUTION_ERROR_HOLD, MAX_DAILY_ATTEMPTS_ACHIEVED, MAX_MONTHLY_ATTEMPTS_ACHIEVED.
- **Nuevo (HU 227148, confirmado 1/10):** `OFFER_RESULT` + `CASE_FOR_REVIEW` = Zona Gris derivada al asistido → pantalla "Un asesor continuará atendiendo tu solicitud". No estaba en develop el 1/10. Al reingresar, ese mismo caso hace que `/request/check` responda `CASE_IN_PROGRESS_PROMOTER` → "Ya tienes una solicitud en curso con un asesor".
- Estados aceptados por paso (`NotifyLoanStatusUseCase`): REQUEST_DATA OK/EXECUTION_ERROR_HOLD · BIOMETRY_START OK/EXECUTION_ERROR_HOLD/INVALID_DOCUMENT · BIOMETRY_RESULT OK/FAIL/RETRY/EXECUTION_ERROR/INVALID_DOCUMENT · **OFFER_RESULT OK/FAIL/EXECUTION_ERROR/MANUAL** · OFFER_CONFIG_RESULT OK/FAIL/EXECUTION_ERROR_HOLD · BILLING_DATA y PEP_DATA OK/EXECUTION_ERROR_HOLD · ACTIVATION_RESULT OK/FAIL/EXECUTION_ERROR. VALIDATION acepta además los códigos de política (AFFILIATE_STATUS, REQUEST_IN_PROGRESS, CARD_STATUS…). Un estado no aceptado devuelve 400 con códigos `LRMGRIN00xx`.

**Quién corre el motor:** `POST .../product/{id}/request/decision-engine/start` (`StartDecisionEngineUseCase`, paquete `startbizagiengine`) no llama a uFlow: busca la URL de la actividad `DECISION_ENGINE_START` del caso en Bizagi y la ejecuta (avanza el proceso; el log dice "Evento iniciar biometria"). **Bizagi** (proceso construido por Gattaca) invoca a **uFlow** (el motor, que da el veredicto), aplica la compuerta posterior al motor (HU 180005) y notifica a la plataforma con `OFFER_RESULT` + `estadoPaso`. `loan-offer-api` mapea la respuesta de uFlow para `GET offer/{idCaso}`. Gattaca responde por lo que pasa después del veredicto; el veredicto (y forzar Zona Gris en CERT) es del equipo de uFlow.

**Pantallas de error del front** (`app-cre-solicitud`, `src/configs/errorConfig.ts`, contenido de respaldo si Drupal falla): `MANUAL` = "Nuestro equipo analizará tu solicitud" / respuesta por correo; `REQUEST_IN_PROGRESS` = "Ya tienes una solicitud en curso" / acércate a Centros de Servicios u Oficinas de Crédito; `FAIL` distingue BIOMETRY_RESULT y OFFER_RESULT; `EXECUTION_ERROR_HOLD` en personalización de oferta devuelve al Onboarding.

**Reingreso con caso en curso (código develop, 2026-10-01):** el middleware del front (`middleware.ts` → `onCheckRequestStatus`) llama a check-status (`/request/check`, `CheckDocumentCaseUseCase`). Si el caso de Bizagi tiene `operatorCode` distinto de `"01"` responde `CASE_IN_PROGRESS_PROMOTER`; el front borra el token y las cookies del flujo, redirige a `/login?requestState=CASE_IN_PROGRESS_PROMOTER` y la página de login pinta `ErrorMessage` con ese código. Respaldo actual: "Ya tienes una solicitud en curso con un promotor" / "acércate a Centros de Servicio u Oficinas de Crédito" / botón "Conocer líneas de atención" (centros-de-servicio) / "Ir a Colsubsidio.com". Si `operatorCode == "01"` (caso digital) responde `IN_PROGRESS` + `pasoPendiente` y el front hace **retoma**: redirige al paso pendiente. En `validate-request` la misma regla da `CASE_IN_PROGRESS_PROMOTER` o `CASE_IN_PROGRESS` ("Ya tienes una solicitud digital en curso… revisa el enlace que enviamos a tu correo"). La constante se llama `OPERATOR_CODE_PROMOTER = "01"`, pero por el `filter` el "01" se comporta como el operador digital.
- **Búsqueda en Bizagi** (`SearchCasesEventConsumerBizagi`, performSearch): filtra `kmInformacionGeneral.bCasoFinalizado = false` + `kmInformacionTramite.kmIntegraciones.kpTipoIdentificacion` + `…sNumeroIdentificacion`, y toma el primer caso. Lee `kmInformacionTramite.kmGestionCreditos.sCodigoOperador` (decide promotor o digital) y `…kpEstado.sDescripcion` (el "estado" visible en Bizagi; se mapea pero **no se usa para decidir**). "En curso" = caso no finalizado, sin importar su estado.
- `REQUEST_IN_PROGRESS` ("Ya tienes una solicitud en curso" / acércate a Centros de Servicios) es otra cosa: lo envía Bizagi en la notificación del paso `VALIDATION`; la regla vive dentro de Bizagi, no en el código de la plataforma.
- Mock (solo con `app.infrastructure.bizagi.enable=false`): documentos 19126101 (operador "02" → promotor) y 19126102 (operador "01" → digital).

**Canal de origen:** `canalOrigen` en `validate-request` (`app-cre-loans-request-manager-api`, enum `RequestSourceChannelDto`) solo admite **WEB, OPERADOR, FLOTANTE** (en el internal-api: WEB, OPERATOR, FLOTANTE). El front siempre manda `WEB` (`WEB_CHANNEL_IDENTIFIER`). No existe "CFA" ni "ASISTIDO" como valor.

**Cómo probar `event-to-client` a mano (verificado 2026-10-15, tarea 232000):**
- Usar `https://platform-test-internal.colsubsidio.com/loans/int-req-mgr/internal/v1/status/event-to-client` con header `x-api-key` (la misma de card-validations, `api_key_card_validations` en token.txt). Por `platform-test-external`, el WAF responde 403 en HTML aunque se mande un token CIAM. Sin key responde 401.
- No consulta Bizagi: idCaso y documento pueden ser ficticios. La entrega depende de que haya un socket abierto. La lambda `send-message-socket` (repo `ed_credito_seguros-loan_websocket-sls`) busca en DynamoDB el id `{idProducto}_{tipo}_{numero}`, que el front abre como subprotocolo (`webSocketUtils.ts`).
- Lectura de la respuesta:
  - 200 + `enviarEventoCliente.estado OK`: el mensaje se entregó.
  - 200 + "Sesión no encontrada" / `ERROR_SENDING_MESSAGE`: el estado se aceptó, pero no había socket.
  - 500 `LRMIT0001` "Failed to read HTTP message": el ambiente no conoce el valor del enum.
  - Los errores LRMGRIN dicen 400 en el body, pero llegan con HTTP 500.
- En VALIDATION, un estado distinto de OK debe ir sin `datosAdicionales` (si viene: LRMGRIN0018). Con OK, `tipoAfiliacion` es obligatorio (si falta: LRMGRIN0007).
- Socket CERT: `wss://966rvchw1g.execute-api.us-east-2.amazonaws.com/cert`. El front de dev.colsubsidio.com también usa este socket y platform-test.
- La lambda `on-connect` lee `headers['Sec-WebSocket-Protocol']` respetando mayúsculas. El WebSocket nativo de Node lo manda en minúsculas y recibe 502.
- Script listo: `test_services/test_event_to_client/event_to_client.mjs` (handshake a mano). Allí mismo está la colección Postman `event-to-client.postman_collection.json`, y en Bruno el request `Event To Client[WEBSOCKET].bru`.
- **Ambientes:**
  - Pipeline "Req Mgr Internal Deploy Dev": despliega develop en `loans-dev2-back` (us-east-1), que no tiene host público.
  - Pipeline "Req Mgr Internal Deploy Qa": despliega en `loans-cert-back` (us-east-2), que es platform-test. El 9/10 Mateo Pineda lo desplegó desde `fix/case-for-review-event-to-client`; su PR 25372 a `qa` sigue activo.
  - develop no tiene `CASE_FOR_REVIEW` y va 28 commits adelante y 23 atrás de `qa`. Desplegar develop en CERT quitaría la Zona Gris.

**Dónde se ve VALIDATION en el front (código develop, 2026-10-15):**
- `AppProvider` abre el socket solo en políticas, información personal, validación de identidad, información adicional y personalización.
- El handler de VALIDATION (`useAffiliation.onMessageChange`) se registra al dar "Continuar" en **políticas** (`PoliciesButtons` → `checkUserAffiliation`), justo antes de validate-request.
- En `/validaciones` nadie escucha el socket. Los errores de esa pantalla salen de las llamadas HTTP directas a SAP, ASCARD y SIIF.
- Si la respuesta es OK, el front va a información personal. Con otro estado, `ErrorMessage` busca el texto en Drupal `/api_creditos/parametros/casuisticas` por `ERROR_CODES[estado]` (`src/constants/errorCodes.ts`).
- Un estado que no esté en `ERROR_CODES` debería pintar la pantalla de error sin título ni texto (deducido del código, no visto).
- Al 15/10, `ERROR_CODES` no tiene RETIRED, SALARY_DEP/IND, GENDER_WOMEN, MANDATORY_REFINANCE ni MAX_CURRENT_WOMEN_LOANS.
- En Drupal CERT existen RETIRED y SALARY_DEP/IND; no existen los 3 de mujeres y retanqueo.
- Truco para verlo sin crear caso, **sin probar**: en políticas, bloquear `*validate-request*` en DevTools → "Continuar" → enviar el evento con ese documento. Con el request bloqueado, el error de red no es 500, así que el loader se queda esperando el socket.
- **DEV:** el API Gateway interno es `https://866xft03u8.execute-api.us-east-1.amazonaws.com/dev` (sacado de la tarea 226673). Con la x-api-key de CERT responde 403 "explicit deny"; hay que pedir la key de DEV.

**How to apply:** al probar un estado nuevo (Zona Gris, derivación, libranza) verificar primero que el par `paso`/`estadoPaso` esté aceptado por el internal-api y qué pantalla/contenido le corresponde en el front; los enums de develop pueden ir adelante o atrás del ambiente de pruebas.

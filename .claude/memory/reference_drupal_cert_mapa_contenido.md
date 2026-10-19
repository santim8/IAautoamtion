# Drupal CERT: cómo está armado y cómo lo consume el front

Levantado el 2026-10-19 con la sesión de admin de Santiago, solo lectura (`drupal_sesion.py`), los endpoints públicos y el código del front (`app-cre-solicitud`, rama `feat/consumer-loans`).

## Ambientes y acceso

- **Un solo Drupal sirve a dos fronts:** el de dev (`d2b80yrnend1dj.cloudfront.net/loans-dev-solicitud`) y el de CERT leen ambos `https://platform-test-external.colsubsidio.com/loans-cert-admin-solicitud`. El admin de dev (`loans-dev-admin-solicitud`) responde 403. Un cambio de contenido se ve a la vez en dev y en el UAT de CERT. Lo que se edite para Consumo cambia también Cupo si comparten código.
- Drupal 10. El admin muestra el aviso "Hay una actualización de seguridad disponible".
- Admin: `/user/login`. La sesión se guarda con `python drupal_sesion.py login`, que pide Enter al terminar, y se usa con `estado` / `ver RUTA` o `from drupal_sesion import abrir`. Todo lo que no es login va en solo lectura (bloquea lo que no sea GET).
- **JSON:API está activo y es anónimo**: `/jsonapi/node/{tipo}` devuelve todo el contenido publicado con todos sus campos, incluidos los ocultos en el formulario. Sirve para QA. Pero también expone `/jsonapi/user/user` (los `display_name` de los usuarios del admin): es una enumeración de usuarios que conviene reportar.

## Cómo se publica el contenido

- Cada endpoint `/api_creditos/parametros/...` es una **vista de Drupal con presentación "Exportación REST"**. Todas filtran `Publicado = Sí` y por tipo de contenido. Casi todas ordenan por **fecha de autoría desc**; formularios y listas, asc.
- Los **filtros contextuales** son los segmentos de la URL: `casuisticas/{nid}`, `onboarding/consumo/{producto}/{pantalla}`, `onboarding/cupo-credito/{pantalla}`, `politicas/{producto}`, `v2/forms/{formulario}`, `v2/listas/{lista}`. Si el valor no existe responde **200 con `[]`**, no 404.
- **"Texto personalizado"**: en Onboarding Productos, Políticas, Casuísticas Redeban e Hitos, la vista oculta los campos y arma a mano un string con forma de JSON. Por eso `items`, `politicas` y `redeban` llegan como **string**, no como arreglo:
  - `politicas` no es JSON válido: Drupal no escapa las comillas de los `href`. El front lo parte por `","`.
  - `redeban` usa comillas simples (`{'codigos': ["S"]}`). El front hace `replace(/'/g,'"')` y `JSON.parse`.
  - `items` de Onboarding es válido mientras ningún ítem traiga comillas sin escapar. El 19/10 lo era en los 3 productos; antes, el link de CFA lo rompía.
- Caché: algunas vistas usan caché "basada en etiqueta", otras ninguna. La página responde `X-Drupal-Cache: HIT` y CloudFront no la cachea. El front pide `no-cache`, así que **un cambio en Drupal se ve al recargar**, sin despliegue.

## Tipo de contenido → endpoint → front

| Tipo (machine name) | Endpoint | ¿Por producto? | Front (servicio) | Pantalla |
|---|---|---|---|---|
| Casuísticas (`casuisticas`) | `/casuisticas`, `/casuisticas/{nid}` | **No** (un texto por código) | `errorContentService`, `loaderContentService` (navegador) | Todas las pantallas de error; el loader usa `LOADER_DEFAULT` y `LOADER_OFFER_RESULTS` |
| Casuísticas Redeban (`casuisticas_redeban`) | `/casuisticas_redeban` | No | `errorContentService` cuando el error es `ASCARD_ERROR` | Rechazos ASCARD de **Cupo** (en Consumo no se usan) |
| Casuísticas Novedades | `/casuisticas_novedades` (`MODAL_INCREMENT_VARIANT`, `MODAL_REACTIVATION_VARIANT`) | Solo Cupo | `quotaUpdateModalContentService` | Modal de aumento/reactivación |
| Onboarding Productos (`onboarding_productos`) | `/onboarding/cupo-credito/0X`, `/onboarding/consumo/{slug}/0X` | **Sí** (Producto + Pantalla) | `onboardingContentService` (servidor) | `/cupo-de-credito/onboarding`, `/consumo/{slug}/onboarding` |
| Onboarding (viejo) | `/onboarding`, `/onboarding/0X` | No | Ninguno (reemplazado) | — |
| Políticas (`politicas`) | `/politicas/{cupo_credito\|consumo}` | Solo familia: Mujeres y Compra de Cartera comparten las de Consumo | `policiesContentService` (navegador) | Pantalla de políticas compartida |
| Campos formulario (`campos_formulario`) | `/v2/forms/{form}`: `politicas_cupo`, `politicas_consumo`, `informacion_personal_*` | Por formulario | `policiesContentService`, `personalInformationContentService` | Políticas (switch `pregunta_X` + `check_afirmativo_X`/`check_negativo_X`) e Información personal |
| Listas (`listas`) | `/v2/listas/{lista}` y las viejas `/contrato`, `/estado_civil`, `/estudios`, `/vivienda`, `/documentos`, `/tipodevia` | No | Políticas, Información personal, `formOptionsService` | Selects |
| Información Personal | `/v2/hito/1` | No (Cupo) | `personalInformationContentService` (servidor) | `/cupo-de-credito/informacion-personal` |
| Hito 0–4 | `/hito/0`…`/hito/5`, `/hito/3/aumentos`, `/hito/3/reactivacion` | No (Cupo) | biometría (`hito/2`), oferta (`hito/3*`), datos adicionales (`hito/4`), fin (`hito/5`) | Pasos de Cupo |
| Personalización de la oferta | `/personalizacion_oferta` | Solo novedades | — | Alternativas de aumento/reactivación |
| Configuraciones generales | `/config/header` = "Solicitud de crédito" | No | `configContentService` (navegador; respaldo con el mismo texto) | Encabezado de todas las pantallas |
| Configuraciones canal autogestionado (`mantaince_window`, nodo 1227) | `/ventana_mantenimiento`; los flags, ver abajo | No | Middleware (`mantainanceWindowService`) | Página de mantenimiento |
| Inhabilitar flujo autogestionado | `/horario_flujo` (10 AM, 8 h) | No | — | Horario |
| Amparados, Ciudades y Municipios, Tipos de vía, Simuladores, Modales | `/amparados`, `/departamentos`, `/tipovia`, `/api_simulador/...`, JSON:API `modales` | — | Formularios de Cupo / simulador público | — |

Rutas de **Consumo** que hoy existen en el front: solo `onboarding`, `validaciones` y `politicas`. Informacion-personal, oferta, biometría y fin solo existen en Cupo, y su contenido (Hitos, Información Personal) **no tiene dimensión de producto**.

## Reglas del front al pintar contenido

- **Errores:** código del back → `ERROR_CODES[code]` → `find(code)` en el JSON de casuísticas.
  - Si el código no está en `ERROR_CODES` o no existe en Drupal, la pantalla sale **en blanco** (título y texto vacíos).
  - El respaldo local de `errorConfig` solo se usa si **Drupal falla**.
  - Si dos nodos tienen el mismo código, gana el de fecha de autoría más reciente.
- `botonVolver = 'Sí'` muestra el botón Volver. El botón abre su URL con `window.location.replace` y el enlace con `target=_self`, así que **los dos abren en la misma pestaña**, aunque Figma pida `_blank`.
- En Políticas, el front agrega `target="_blank"` a los links del HTML.
- Contenido pedido desde el **servidor** (SSR): onboarding, hitos, información personal, mantenimiento. Solo se puede simular su falla con un Drupal falso local (`drupal_mock.py`).
- Contenido pedido desde el **navegador**: casuísticas, redeban, header, loader, políticas, listas. Se puede interceptar con DevTools o con `route` de Playwright.

## Datos que no se ven en la interfaz del admin

- **Casuísticas:**
  - Campos: Título, Párrafo Uno (sugerido ≤ 250), Párrafo Dos (≤ 100), Helper, Texto/Url Botón, Texto/Url Link, imágenes, Activar Botón Volver, Código.
  - El Código es la taxonomía `error_codes`, con 32 términos. **No existe `MANDATORY_REFINANCE`.** Existe `INVALID_GENDER_...`, no `INVALID_GENRE_...`.
  - Título, botón y link aceptan 255 caracteres: **los límites de Figma (65/32/35/22) no se aplican**.
  - Nodos sin código: 1168 (duplicado de "afiliado", 2024) y 1177.
- **Flags del canal (nodo 1227):**
  - Los campos `field_fflag_incr` (aumentos), `field_feature_flag_inc_reac` (reactivación) y `field_feature_flag` (CIAM) están **desactivados en el formulario**: no se ven ni se editan desde la interfaz.
  - Sus endpoints REST (`/feature_flag_increment`, `/feature_flag_reactivation`, `/drupal_auth_strategy_feature_flag`, `/feature_flag_increment_and_reactivation`) dan **404 por CloudFront** (`Server: AmazonS3`) desde el 2/10, aunque la vista existe.
  - Lectura que sí funciona: `/jsonapi/node/mantaince_window?fields%5Bnode--mantaince_window%5D=field_feature_flag,field_feature_flag_inc_reac,field_fflag_incr,field_maintenance_window,changed`.
  - Al 19/10, **los cuatro en false**, con último cambio el 23/06/2026. El back puede leerlos por una URL interna.

## Receta de QA para validar contenido

1. Textos publicados: el endpoint público (`/api_creditos/parametros/...`). El `id` de cada casuística es su `nid`.
2. Historial (quién y cuándo editó): `/node/{nid}/revisions` con la sesión. Formulario y límites de cada campo: `/node/{nid}/edit` (solo mirar, nunca guardar).
3. Campos ocultos o configuración: JSON:API.
4. Para cada código que devuelve el back, comprobar que exista en `ERROR_CODES` del front **y** en la taxonomía de Drupal. Si falta en cualquiera de los dos, la pantalla sale en blanco.

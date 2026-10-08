"""Observador pasivo de flujos, por piezas.

El punto de entrada sigue siendo observador_flujo.py (lo lanza el panel y lo
empaqueta PyInstaller). Aqui vive el codigo, una responsabilidad por modulo:

  config        catalogo: hosts, endpoints rastreados, reglas por endpoint,
                disparadores de pantallazo, tiempos y topes
  endpoints     como casa una URL con un endpoint (version /vN/ comodin) y
                que reglas especiales le tocan
  redaccion     credenciales fuera de la evidencia
  util          utilidades sin estado (slug, rutas, jsonl)
  navegador     lanzar Chrome y dejarlo como recien abierto (--limpiar)

  observador    el nucleo: pasos (una pantalla = un paso) y orquestacion
  alcance       que se captura: de que pestana y que requests
  red           trafico HTTP: Playwright + sesion CDP propia (CORS, cortados,
                huerfanos, en vuelo al parar)
  pantallazos   todos los screenshots: al entrar, diferidos, extra y por
                respuesta de un servicio
  sockets       frames del WebSocket
  complementos  lo que se suma a la captura sin tocar el nucleo (la sonda de
                /request/check es uno)

  analisis      lecturas sobre los pasos: fallos, cobertura, /request/check
  cierre        lo que se escribe al cerrar (SALIDAS, en orden)
  reporte_html  reporte.html
  har           captura.har
  disco         regenerar el reporte desde una carpeta de evidencia
  parada        centinela del panel y cierre de emergencia
  cli           argumentos y loop principal

Para extender:
  - un endpoint nuevo a rastrear o con trato especial: config.py
    (ENDPOINTS_RASTREADOS, REGLAS_ENDPOINT)
  - algo que reaccione al flujo (otra sonda, otra consulta del lado del
    servidor): una subclase de complementos.Complemento, armada en
    cli.armar_complementos
  - un archivo de salida nuevo: una funcion en cierre.SALIDAS
  - un bloque nuevo en la cabecera del reporte: reporte_html.BLOQUES_CABECERA
"""

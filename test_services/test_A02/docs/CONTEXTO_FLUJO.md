# Contexto — Flujo activation-file ↔ Redeban (test_A02)

> Raíz de trabajo del esfuerzo de QA de este flujo. Última actualización tras reunión con el desarrollador (2026-06-05).

## 1. Programa Desatendido (Python) — alcance CONFIRMADO

El programa Python **solo VALIDA** que el contenido del archivo `.txt` que se subió cumpla los
parámetros de formato (longitudes, posiciones, texto, relleno, etc.).

- **NO intercepta el SFTP.** Trabaja sobre el archivo en sí (su contenido), no sobre el canal de transmisión.
- **En el futuro** ese mismo programa permitirá **crear** archivos A02 (generador).
- Lo construye Carlos Santacruz; luego se porta a clases Java para el microservicio.

## 2. Flujo completo (definitivo)

```
FASE 1 — ENVÍO (síncrono, dentro del POST /activation-file):
  El servicio activation-file hace 3 cosas:
    1. Genera el .txt A02
    2. Lo sube a S3
    3. Lo sube al SFTP de Redeban
    (+ crea el evento de EventBridge)
    → responde estado: ENVIADO

FASE 2 — RESPUESTA (polling cada 5 min):
  EventBridge → dispara Lambda (loans-prod-back-read-sftp-file)
  Lambda → consulta SFTP Redeban; si hay archivo de respuesta lo descarga
  Lambda → POST /process-activation
  /process-activation → Apigee → Bizagi  (notifica resultado del caso)
```

- El JSON del request **NO es el archivo A02**. El servicio transforma el JSON en el `.txt` posicional.
- `estado: ENVIADO` = el archivo ya está en S3 **y** en el SFTP de Redeban (envío síncrono).

## 3. Estrategia de pruebas — validar el flujo COMPLETO (E2E)

Hay que validar el flujo de punta a punta: lanzo activation-file → S3 + SFTP → Lambda → process-activation → Apigee → Bizagi.

### Caso POSITIVO
- **Origen:** request body **válido** para activation-file, lanzado desde el **flujo autogestionado** (cuando lanzo el activation desde ese flujo).
- **Esperado:**
  - El archivo se sube correctamente a S3 y al SFTP.
  - El contenido del `.txt` cumple el formato A02 (validar con el programa Python).
  - La Lambda procesa, se dispara process-activation.
  - **La información se refleja CORRECTAMENTE en Bizagi** (caso válido / estado correcto).

### Caso NEGATIVO
- **Origen:** request/archivo con **formato incorrecto**.
- **Esperado:**
  - Se **registran los logs** del caso negativo (formato incorrecto).
  - Se **dispara una alerta/detección** de que el archivo se envió en formato incorrecto.
  - **En Bizagi aparece como ERROR** — el caso NO es válido.

## 4. Tareas pendientes

- [ ] **Hablar con Juanita:** confirmar si al final del proceso se puede ver/recibir un **correo** (notificación al cierre del caso).
- [ ] **Definir cómo hacer un asistido con aumento** (flujo asistido para novedad de aumento, tipoNovedad=2).

## 5. Bloqueos / por confirmar

- Layout completo A02 (Excel de Juan Carlos) — para asserts de contenido.
- Formato del archivo de RESPUESTA de Redeban — para probar /process-activation.
- Acceso a: SFTP cert, bucket S3 (lectura), CloudWatch (logs de Lambda).
- Cómo se ven los logs/alertas del caso negativo (dónde quedan: CloudWatch / Bizagi).

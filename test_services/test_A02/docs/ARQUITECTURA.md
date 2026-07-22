# Arquitectura — Flujo activation-file ↔ Redeban

Confirmado leyendo el diagrama del equipo + reunión con el desarrollador (2026-06-05).

## Lectura clave del diagrama

Las dos flechas de SFTP son **distintas**:
- **"SFTP (archivo .txt)"**: origen Webflux **/activation-file** → Redeban. Una dirección (ENVÍO).
- **"Leer archivo .txt"**: origen **Lambda** ↔ Redeban. Bidireccional. La Lambda **solo LEE** respuestas.

## Diagrama

```
FASE 0 — VALIDACIÓN PREVIA (QA / herramienta)
   ┌──────────────────────────────────┐
   │   Programa Desatendido (Python)  │  (Carlos Santacruz)
   │   • VALIDA formato del .txt A02   │
   │   • (futuro) GENERA archivos A02  │
   └──────────────────────────────────┘

FASE 1 — ENVÍO (síncrono, dentro del POST):
   ┌─────────┐         ┌──────────────────────────────┐
   │ Bizagi  │ ─POST─▶ │  Webflux /activation-file    │
   │/cliente │         │  1. Genera .txt A02          │
   └─────────┘         │  2. Sube a S3 ───────────────┼──▶ s3://loans-{env}-back-documents/...
                       │  3. SFTP PUT ────────────────┼──▶ Redeban (Directorio In/Out)
                       │  4. Crea evento EventBridge   │
                       │  5. Responde estado: ENVIADO  │
                       └──────────────┬───────────────┘
                          "Crea Evento"│
                                       ▼
                       ┌──────────────────────┐
                       │  EventBridge         │
                       │  (Schedule Manager)  │
                       └──────────┬───────────┘
                                  │ dispara cada 5 min
   · · · ESPERA ASÍNCRONA · · · · │ · · · · · · · · · · · · · · ·
   (Redeban procesa y deja resp.) │
                                  ▼
FASE 2 — RESPUESTA (polling cada 5 min):
                       ┌──────────────────────────────┐
                       │  Lambda                      │
                       │  loans-prod-back-read-sftp-  │  "Leer archivo .txt"
                       │  file                        │ ◀──────────────▶ Redeban
                       │  • ¿hay archivo respuesta?   │   (consulta + descarga)
                       │  • si SÍ → descarga          │
                       └──────────────┬───────────────┘
                                      │ POST contenido
                                      ▼
                       ┌──────────────────────────────┐
                       │  Webflux /process-activation │
                       │  • parsea respuesta          │
                       │  • resultado por caso        │
                       └──────────────┬───────────────┘
                                      ▼
                       ┌──────────┐      ┌──────────┐
                       │  Apigee  │ ───▶ │  Bizagi  │ ──▶ estado final del caso
                       └──────────┘      └──────────┘
```

## Componentes

| Componente | Rol |
|---|---|
| **Webflux `/activation-file`** | Genera el .txt A02, lo sube a S3 **y** al SFTP de Redeban, crea el evento. Síncrono. Requiere `x-api-key`. |
| **S3 `loans-{env}-back-documents`** | Respaldo/evidencia del archivo enviado. NO es el canal de envío. Path codifica trazabilidad. |
| **Redeban (SFTP In/Out)** | Carpeta compartida. activation-file ENVÍA aquí; Redeban deja la RESPUESTA aquí. |
| **EventBridge (Schedule Manager)** | Dispara la Lambda cada 5 min. |
| **Lambda `loans-prod-back-read-sftp-file`** | Solo LEE: consulta el SFTP, descarga la respuesta, llama a /process-activation. |
| **Webflux `/process-activation`** | Lee el archivo de respuesta y notifica el resultado a Bizagi vía Apigee. |
| **Apigee** | Gateway entre el microservicio y Bizagi. |
| **Bizagi** | Motor de proceso de negocio; refleja el estado final del caso. |
| **Programa Desatendido (Python)** | Valida el formato del .txt (y a futuro lo genera). No intercepta el SFTP — opera sobre el archivo. |

## Notas para QA

- `estado: ENVIADO` = el archivo ya está en S3 **y** en el SFTP de Redeban (envío síncrono dentro del POST).
- El detalle interno (si activation-file lee de vuelta de S3 antes del SFTP o lo manda de memoria) NO afecta el QA de caja negra.
- La descarga importante es la de la **Lambda** (baja la respuesta de Redeban), no confundir con el envío.
- El JSON del request **NO es el archivo A02**; el servicio lo transforma en el `.txt` posicional.

# test_A02 — QA del flujo activation-file ↔ Redeban

Raíz de trabajo del esfuerzo de QA para el flujo de envío de archivos A02 (activación / aumento)
hacia Redeban vía SFTP, y su respuesta procesada hacia Bizagi.

## Estructura

```
test_A02/
├── README.md                         ← este archivo (entrada / índice)
├── docs/                             ← contexto y especificaciones
│   ├── CONTEXTO_FLUJO.md             flujo E2E + estrategia de pruebas + pendientes
│   ├── ARQUITECTURA.md               componentes + diagrama
│   ├── CONTRATO_ACTIVATION_FILE.md   request/response del endpoint
│   └── ESTRUCTURA_A02.md             layout posicional del archivo A02
└── bruno/                            ← colección Bruno ejecutable
    ├── bruno.json
    ├── environments/test.bru
    ├── TC-00 Generate Token.bru
    ├── TC-01 Happy Path Aumento.bru
    └── TC-02 Sin x-api-key.bru
```

## Documentación

| Documento | Contenido |
|---|---|
| [docs/CONTEXTO_FLUJO.md](docs/CONTEXTO_FLUJO.md) | Flujo end-to-end, estrategia (caso positivo/negativo), pendientes |
| [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md) | Componentes (Webflux, Lambda, EventBridge, S3, SFTP, Apigee, Bizagi) + diagrama |
| [docs/CONTRATO_ACTIVATION_FILE.md](docs/CONTRATO_ACTIVATION_FILE.md) | Request/response del endpoint, códigos, patrón S3 path y nombre de archivo |
| [docs/ESTRUCTURA_A02.md](docs/ESTRUCTURA_A02.md) | Layout posicional del archivo A02 (longitudes, posiciones, reglas) |

## Colección Bruno (`bruno/`)

Pruebas HTTP del endpoint `activation-file`. Abrir la carpeta `bruno/` como colección en Bruno.

- `environments/test.bru` — entorno CERT/TEST interno + `x-api-key` + credenciales Apigee
- `TC-00 Generate Token` — OAuth2 client_credentials (Apigee)
- `TC-01 Happy Path Aumento` — envío válido (tipoNovedad=2) con asserts del contrato
- `TC-02 Sin x-api-key` — negativo de seguridad (403)

## Equipo

| Persona | Rol en este flujo |
|---|---|
| Santiago Correa (yo) | QA — valida flujo E2E |
| Carlos Santacruz | Construye el Programa Desatendido (Python) + clases Java |
| Santiago Hernández Pérez | Integra la validación Java en el microservicio Webflux |
| Juan Carlos Hidalgo | Especificaciones, ejemplos TXT, Excel del layout |
| Carlos Humberto Gómez | Reglas de negocio (nomenclatura, BIN, consecutivos) |

> Origen: reunión Piscilago/Créditos 2026-06-05 + reunión con el desarrollador.

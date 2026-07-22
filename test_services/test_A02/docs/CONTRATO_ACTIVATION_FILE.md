# Contrato — POST /activation-file

Endpoint Webflux que genera el archivo A02, lo guarda en S3 y lo sube por SFTP a Redeban.

## Endpoint

```
POST {{baseUrl}}/loans/int-req-mgr/internal/v1/status/activation-file
```

- **Auth:** header `x-api-key` (no Bearer).
- **Host CERT/TEST interno:** `https://platform-test-internal.colsubsidio.com`

## Request

```json
{
  "datosSolicitud": {
    "categoria": "C",
    "cicloFacturacion": "1",
    "codigoCiudadCorrespondencia": "11001",
    "codigoCiudadResidencia": "11001",
    "codigoDepartamentoCorrespondencia": "11",
    "codigoDepartamentoResidencia": "11",
    "codigoVendedor": "128",
    "cupoAsignado": "4000000.0000",
    "direccionCorrespondencia1": "Cll wallaby 42 Sidney",
    "direccionCorrespondencia2": "Cll wallaby 42 Sidney",
    "fechaSolicitud": "20260520",
    "numeroIdentificacion": "112349649",
    "numeroSolicitud": "3006096",
    "numeroTarjetaAsignado": "8899010101455529",
    "oficinaRadicacionSolicitud": "147",
    "primerApellido": "MENDOZA",
    "primerNombre": "ANYIS",
    "segundoApellido": "ROMERO",
    "segundoNombre": "KARINA",
    "telefonoOficina": "3333333333",
    "telefonoResidencia": "3333333333",
    "tipoCupo": "NORMAL",
    "tipoIdentificacion": "CO1C",
    "tipoNovedad": "2",
    "valorCuotaFija": "200000.0000",
    "zonaPostalResidencia": "000000"
  },
  "idCaso": "121213",
  "trailer": { "consecutivo": "54321" }
}
```

### Notas de campos

- `tipoIdentificacion`: solo **CO1C** / **CO1E** (datos autorizados para testing).
- `tipoNovedad`: `1`=originación, `2`=aumento, `3`=reactivación (a confirmar).
- `fechaSolicitud`: en el **request HTTP** va en `YYYYMMDD`. Dentro del archivo A02 las fechas van en `YYMMDD` — no confundir.
- El JSON **NO es el archivo A02**: el servicio lo transforma en el `.txt` posicional.
- Para testing usar solo cédulas autorizadas (la del ejemplo: `112349649`).

## Response 200 (confirmado 2026-06-05)

```json
{
  "resultado": [
    { "codigo": 202, "descripcion": "Archivo enviado" }
  ],
  "archivo": {
    "nombre": "A0288000128040154321.txt",
    "ruta": "s3://loans-cert-back-documents/aplicaciones-de-prestamo/2_cupo_credito/112349649-121213/acuerdos-de-prestamo/intercambio-entidades-ascard/A0288000128040154321.txt",
    "estado": "ENVIADO",
    "fechaEnvio": "2028-04-01T00:00"
  }
}
```

### Patrón del nombre del archivo

`A02` + `<dígitos>` + `.txt` — concatenación posicional (BIN, código vendedor, consecutivo;
estructura exacta pendiente del Excel del equipo).

### Patrón del path S3

```
s3://loans-{env}-back-documents
  /aplicaciones-de-prestamo
  /{tipoNovedad}_cupo_credito          ← 1, 2, 3
  /{numeroIdentificacion}-{idCaso}     ← trazabilidad por caso
  /acuerdos-de-prestamo
  /intercambio-entidades-ascard
  /{nombre_archivo}
```

`{env}` observado: `cert`. En prod probablemente `prod`.

### Códigos de resultado

| Código | Descripción | Significado |
|---|---|---|
| 202 | Archivo enviado | Happy path — archivo generado y depositado en SFTP Redeban |

(Otros códigos por confirmar.)

### Estados de `archivo.estado`

- `ENVIADO` — el Webflux ya subió el archivo por SFTP a Redeban **dentro del POST** (síncrono), además de guardarlo en S3 y crear el evento. NO es solo "guardado en S3".
- Otros estados por confirmar.

## Asserts mínimos (Bruno, happy path)

```
res.status: eq 200
res.body.resultado[0].codigo: eq 202
res.body.resultado[0].descripcion: eq "Archivo enviado"
res.body.archivo.estado: eq "ENVIADO"
res.body.archivo.nombre: matches ^A02\d+\.txt$
res.body.archivo.ruta: contains s3://
res.body.archivo.ruta: contains {tipoNovedad}_cupo_credito
res.body.archivo.ruta: contains {numeroIdentificacion}-{idCaso}
res.body.archivo.fechaEnvio: isDefined
```

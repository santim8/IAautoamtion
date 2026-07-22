$ErrorActionPreference = "Stop"

# Base64 del archivo ZIP de la colección
$b64File = "C:\Users\santiago.correa03\ColsubsidioIA\IAautoamtion\bruno\notification-service\_b64_attachment.txt"
$base64 = Get-Content -Raw $b64File
$base64 = $base64 -replace "\s", ""

# Construir el payload
$payload = @{
    adjuntos = @(
        @{
            contenido = "data:application/zip;base64,$base64"
            nombreArchivo = "notification-service-collection.zip"
            tipo = "base64"
        }
    )
    datos = @{
        diaDePago = "1"
        fechaHoraSolicitud = "2026-05-25T16:38:48.00000"
        numeroTarjetaMultiservicios = "8800010305054110"
        tipoCuota = "FIJA"
        valorCuota = 130000.0
        valorCupo = 2600000.0
    }
    destinatario = @{
        email = "jrojas@gattaca.co"
        primerApellido = "RODRIGUEZ"
        primerNombre = "MARIA FERNANDA"
    }
    documento = @{
        numero = "80229110"
        tipo = "CO1C"
    }
    evento = "CUPO_CREDITO_APROBADO"
}

$jsonBody = $payload | ConvertTo-Json -Depth 10 -Compress

$headers = @{
    "x-api-key" = "ecn24ysGnZ4X17cU5lX4Q9gyFvyPR7fD1DkwR7I7"
    "content-type" = "application/json"
}

Write-Host "Tamaño del payload: $($jsonBody.Length) caracteres"
Write-Host "Tamaño del base64: $($base64.Length) caracteres"
Write-Host "Enviando POST a https://platform-test-internal.colsubsidio.com/loans/notification/internal/v1/email/send ..."

try {
    $response = Invoke-RestMethod -Uri "https://platform-test-internal.colsubsidio.com/loans/notification/internal/v1/email/send" `
        -Method Post -Headers $headers -Body $jsonBody -TimeoutSec 60
    Write-Host "RESPUESTA:"
    $response | ConvertTo-Json -Depth 10
} catch {
    Write-Host "ERROR HTTP: $($_.Exception.Response.StatusCode.value__)"
    $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
    $errBody = $reader.ReadToEnd()
    Write-Host "BODY ERROR: $errBody"
}

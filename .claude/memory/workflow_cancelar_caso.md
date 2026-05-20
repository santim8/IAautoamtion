# Workflow: Cancelar Caso

## Trigger
`"cancelar caso {idCaso}"` + token

## Descripción
Cancela una solicitud de crédito directamente via API usando el `idCaso` ya conocido.
**No requiere consulta a Bizagi** — el idCaso se pasa directo.

## Comando
```bash
curl -s --request POST \
  --url https://platform-test-external.colsubsidio.com/loans/req-mgr/external/v1/product/2/request/cancel-request \
  --header "authorization: {token}" \
  --header "content-type: application/json" \
  --data '{"idCaso": "{idCaso}"}'
```

## Notas
- El token se vence cada 2 horas; el usuario lo provee en cada invocación.
- Respuesta exitosa: `{"resultado":[{"codigo":200,"descripcion":"OK"}],"cancelarSolicitud":{"idCaso":"..."}}`

## Historial de correcciones
| Fecha      | Corrección |
|------------|------------|
| 2026-05-15 | El `{idCaso}` NO es el número de documento — es el ID de caso directo. No consultar Bizagi si ya se tiene el idCaso. |

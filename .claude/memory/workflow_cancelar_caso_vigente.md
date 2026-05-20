# Workflow: Cancelar Caso Vigente por Cédula

## Trigger
`"cancelar para esta {identification} el caso vigente"`

## Descripción
Busca en Bizagi (headless) la última solicitud de la cédula indicada y la cancela via API.
Usa `cancel_case_workflow.py`.

## Comando
```bash
python cancel_case_workflow.py {identification} {token}
# CE:
python cancel_case_workflow.py CE {identification} {token}
```

## Flujo interno
1. Bizagi headless → busca por `{identification}` → obtiene `idCaso` (última fila)
2. POST a `/loans/req-mgr/external/v1/product/2/request/cancel-request` con ese `idCaso`

## Notas
- Token se vence cada 2 horas; reutilizar el de la sesión si no ha expirado.
- Respuesta exitosa: `{"resultado":[{"codigo":200,"descripcion":"OK"}]}`
- Error de encoding en Windows: no usar emojis en prints (usar `[OK]` / `[FAIL]`).

## Historial de correcciones
| Fecha      | Corrección |
|------------|------------|
| 2026-05-15 | UnicodeEncodeError en Windows por ✔ — reemplazar por `[OK]` / `[FAIL]` en prints. |

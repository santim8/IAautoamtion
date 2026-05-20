# Workflow: Consultar Pull Request (Azure DevOps)

## Trigger
`"ver PR {repo} {número}"` / `"consultar PR {número}"` / imagen de un PR

## Flujo completo

### Paso 1 — Buscar repo ID
```bash
TOKEN=$(grep token_azure token.txt | cut -d= -f2)
curl -s -u ":$TOKEN" \
  "https://dev.azure.com/ColsubsidioDigital/Ecosistema%20Digital%20Cr%C3%A9dito%20y%20Seguros/_apis/git/repositories?api-version=7.0" \
  | python -c "import sys,json; repos=json.load(sys.stdin)['value']; [print(r['id'], r['name']) for r in repos if '{repo}' in r['name'].lower()]"
```

### Paso 2 — Confirmar número de PR (si viene de pantalla)
El número visible puede tener un dígito extra (ej. 122464 → real 22464). Listar PRs del repo:
```bash
TOKEN=$(grep token_azure token.txt | cut -d= -f2)
curl -s -u ":$TOKEN" \
  "https://dev.azure.com/ColsubsidioDigital/Ecosistema%20Digital%20Cr%C3%A9dito%20y%20Seguros/_apis/git/repositories/{repo_id}/pullrequests?searchCriteria.status=all&api-version=7.0" \
  | python -c "import sys,json; prs=json.load(sys.stdin)['value']; [print(p['pullRequestId'], p['title'][:80]) for p in prs]"
```

### Paso 3 — Consultar PR completo
```bash
TOKEN=$(grep token_azure token.txt | cut -d= -f2)
curl -s -u ":$TOKEN" \
  "https://dev.azure.com/ColsubsidioDigital/Ecosistema%20Digital%20Cr%C3%A9dito%20y%20Seguros/_apis/git/repositories/{repo_id}/pullrequests/{pr_number}?api-version=7.0" \
  | python -m json.tool
```

## Información a presentar (siempre completa)
1. **Datos generales**: título, estado, autor, fechas creación/merge, rama origen → destino, ticket vinculado, reviewers y votos
2. **Descripción completa**: cambios realizados por clase/componente, tipo de cambio, checklist, cómo se probó, escenarios validados
3. **Relación con historia**: cruzar con la HU correspondiente si se conoce

## Repos ID conocidos
| Repo | ID |
|---|---|
| `app-cre-product-eligibility-api` | `51a68bfb-dbe2-49ba-9bcf-1fb3ba285dbf` |

## Notas
- Token en `token.txt` → campo `token_azure`
- El número de PR en pantalla puede tener prefijo extra; siempre confirmar con el listado

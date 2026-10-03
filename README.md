# Sistema de incidencias (AgentCore + Lambda + web)

Registro y seguimiento de incidencias con un asistente de IA que clasifica cada una (severidad, categoría,
resumen, próximos pasos) y responde dudas sobre las abiertas.

```
Navegador ──► Lambda (Function URL: web + API) ──► DynamoDB (bajo demanda)
                         └──► AgentCore harness (InvokeHarness) ──► Bedrock
```
Todo se paga por uso: Lambda, DynamoDB on-demand, harness de AgentCore (sin cargo propio; se factura el
runtime/memoria consumidos) y Bedrock. Sin tráfico no hay coste, salvo el bucket S3 con el zip.

## API
| Método y ruta | Qué hace |
|---|---|
| `GET /` | web |
| `GET /api/incidents` | lista (más recientes primero) |
| `POST /api/incidents` `{title, description}` | crea y clasifica con el asistente (si falla, se guarda igualmente) |
| `PATCH /api/incidents/{id}` `{status}` | `abierta` · `en_curso` · `resuelta` |
| `POST /api/chat` `{message, session_id?}` | pregunta al asistente con las incidencias abiertas como contexto |

## Versiones
Ninguna fijada a mano: `uv.lock` las resuelve (boto3 va dentro del zip porque el de Lambda puede no traer
`InvokeHarness`) y el runtime de Lambda se deduce del Python de uv (`build/runtime.txt`). Las actions de
GitHub usan los últimos tags existentes al crear el repo.

## Puesta en marcha
1. Rol IAM OIDC para GitHub (confía en `token.actions.githubusercontent.com`, repo `Keniding/agent-aws`) con
   permisos sobre CloudFormation, IAM, Lambda, DynamoDB, S3 y `bedrock-agentcore:*`.
2. Acceso al modelo en Bedrock y un `MODEL_ID` válido (`aws bedrock list-inference-profiles`).
3. GitHub → Settings: secret `AWS_ROLE_ARN`; variables `AWS_REGION` y `MODEL_ID`.
4. Push a `main` (o ejecutar `deploy` a mano): sube el zip, despliega `template.yaml`, crea/actualiza el
   harness e imprime la URL. `ci.yml` valida ramas y PRs; `destroy.yml` (manual) lo borra todo.

Local: `uv sync && uv run pytest && ./scripts/package.sh`.

## Pendiente de validar
- Sin acceso a los docs de AWS ni a una cuenta desde el sandbox: la forma de la API sale del modelo de
  servicio de boto3 y la política del rol del harness es un punto de partida (ver *harness-security*).
- La URL es pública (`AuthType NONE`) y cualquiera puede crear incidencias y gastar tokens: antes de uso
  real, añade autenticación (Cognito/IAM), WAF y límites.
- La lista usa `Scan` (válido para volúmenes pequeños); para muchos datos, añade un índice por estado/fecha.

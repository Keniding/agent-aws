# agent-aws — demo AgentCore harness + Lambda + web (todo pay-per-use)

```
Browser ──► Lambda Function URL (sirve la web y /POST chat) ──► AgentCore harness (InvokeHarness) ──► Bedrock
```
Sin servidores fijos: Lambda, el harness de AgentCore y Bedrock cobran por uso (el harness no tiene cargo
adicional; se paga runtime/memoria/etc. consumidos). Nada cuesta si nadie lo usa, salvo el bucket S3 con el zip.

## Versiones
Ninguna fijada a mano: `uv.lock` las resuelve (boto3 se empaqueta dentro del zip porque el de Lambda puede
no traer `InvokeHarness`), y el runtime de Lambda se deduce del Python que usa uv (`build/runtime.txt`).
Las actions de GitHub usan los últimos tags existentes al crear el repo.

## Requisitos únicos en AWS
1. Rol IAM OIDC para GitHub (confía en `token.actions.githubusercontent.com`, repo `Keniding/agent-aws`)
   con permisos para CloudFormation, IAM, Lambda, S3 y `bedrock-agentcore:*`.
2. Acceso al modelo en Bedrock y un `MODEL_ID` válido: `aws bedrock list-inference-profiles` /
   `aws bedrock list-foundation-models`.
3. En GitHub → Settings: secret `AWS_ROLE_ARN`; variables `AWS_REGION` (región con AgentCore harness) y `MODEL_ID`.

## Uso
- PR / ramas: `ci.yml` (ruff, pytest, empaquetado).
- Push a `main` (o manual): `deploy.yml` → sube zip, despliega `template.yaml`, crea/actualiza el harness,
  imprime la URL.
- `destroy.yml` (manual): borra harness y stack.

Local: `uv sync && uv run pytest && ./scripts/package.sh`.

## Notas / pendiente de validar
- No pude leer los docs de AWS desde el sandbox ni desplegar (sin credenciales): la forma de la API sale del
  modelo de servicio de boto3; la política del rol del harness es un punto de partida, afínala con la página
  *harness-security* de AWS. Probar en una cuenta real antes de confiar.
- La Function URL es pública (`AuthType NONE`) y sin límite de gasto: para algo real, añade auth/WAF/throttling.

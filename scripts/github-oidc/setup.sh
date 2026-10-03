#!/usr/bin/env bash
# Crea (o actualiza) el proveedor OIDC de GitHub y el rol de despliegue en AWS, y guarda AWS_ROLE_ARN en GitHub.
# Lo ejecuta una persona con permisos de IAM: bash scripts/github-oidc/setup.sh
# Revisa antes trust.json (quién puede asumir el rol) y perms.json (qué puede hacer).
set -euo pipefail
cd "$(dirname "$0")"

ROLE=github-agent-aws-deploy
REPO=Keniding/agent-aws
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
PROVIDER="arn:aws:iam::$ACCOUNT:oidc-provider/token.actions.githubusercontent.com"
render() { sed "s/__ACCOUNT__/$ACCOUNT/g" "$1" > "$2"; }
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
render trust.json "$TMP/trust.json"; render perms.json "$TMP/perms.json"

echo "Cuenta: $ACCOUNT"
if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$PROVIDER" >/dev/null 2>&1; then
  echo "Proveedor OIDC: ya existe"
else
  aws iam create-open-id-connect-provider --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 >/dev/null
  echo "Proveedor OIDC: creado"
fi

if aws iam get-role --role-name "$ROLE" >/dev/null 2>&1; then
  aws iam update-assume-role-policy --role-name "$ROLE" --policy-document "file://$TMP/trust.json"
  echo "Rol: actualizada su confianza"
else
  aws iam create-role --role-name "$ROLE" --assume-role-policy-document "file://$TMP/trust.json" \
    --description "GitHub Actions ($REPO): despliegue de la pila incidencias" >/dev/null
  echo "Rol: creado"
fi
aws iam put-role-policy --role-name "$ROLE" --policy-name despliegue-incidencias \
  --policy-document "file://$TMP/perms.json"
echo "Política de permisos: aplicada"

ARN="arn:aws:iam::$ACCOUNT:role/$ROLE"
gh secret set AWS_ROLE_ARN --repo "$REPO" --body "$ARN"
echo "Secreto AWS_ROLE_ARN guardado en $REPO -> $ARN"

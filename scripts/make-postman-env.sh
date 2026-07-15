#!/usr/bin/env bash
# Generate a Postman environment (with real values from the deployed stack) for
# the SuperCarl collection. Writes SuperCarl.postman_environment.json at the repo
# root. That file contains the Cognito client secret, so it is gitignored.
#
#   ./scripts/make-postman-env.sh -p <aws-profile>
set -euo pipefail

PROFILE="${AWS_PROFILE:-}"
REGION="${AWS_REGION:-us-east-1}"
while [[ $# -gt 0 ]]; do
  case $1 in
    -p|--profile) PROFILE="$2"; shift 2 ;;
    -r|--region)  REGION="$2"; shift 2 ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
done
[[ -z "$PROFILE" ]] && { echo "AWS profile required (-p)"; exit 1; }

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/cdk-outputs.json"
[[ -f "$OUT" ]] || { echo "cdk-outputs.json not found — deploy first"; exit 1; }
jqp() { python3 -c "import json;print(json.load(open('$OUT'))['SuperCarlStack']['$1'])"; }

API=$(jqp ApiUrl); POOL=$(jqp UserPoolId); CID=$(jqp UserPoolClientId); DOMAIN=$(jqp CognitoDomain)
CS=$(aws cognito-idp describe-user-pool-client --user-pool-id "$POOL" --client-id "$CID" \
  --profile "$PROFILE" --region "$REGION" --query 'UserPoolClient.ClientSecret' --output text)
TOKENURL="https://${DOMAIN}.auth.${REGION}.amazoncognito.com/oauth2/token"

python3 - "$API" "$TOKENURL" "$CID" "$CS" > "$ROOT/SuperCarl.postman_environment.json" <<'PY'
import sys, json
api, tokenurl, cid, cs = sys.argv[1:5]
print(json.dumps({
    "id": "supercarl-env-0001",
    "name": "SuperCarl (live AWS)",
    "values": [
        {"key": "baseUrl", "value": api, "type": "default", "enabled": True},
        {"key": "cognitoTokenUrl", "value": tokenurl, "type": "default", "enabled": True},
        {"key": "clientId", "value": cid, "type": "default", "enabled": True},
        {"key": "clientSecret", "value": cs, "type": "secret", "enabled": True},
    ],
    "_postman_variable_scope": "environment",
}, indent=2))
PY

# Also emit a Bruno environment (same values) for the native Bruno collection.
mkdir -p "$ROOT/docs/bruno/environments"
cat > "$ROOT/docs/bruno/environments/live-aws.bru" <<EOF
vars {
  baseUrl: ${API}
  cognitoTokenUrl: ${TOKENURL}
  clientId: ${CID}
  clientSecret: ${CS}
}
EOF

echo "Wrote (both gitignored — they contain the client secret):"
echo "  - SuperCarl.postman_environment.json        (Postman)"
echo "  - docs/bruno/environments/live-aws.bru       (Bruno)"
echo ""
echo "Postman: import the env + docs/postman/SuperCarl.postman_collection.json"
echo "Bruno:   Open Collection -> docs/bruno  (the env is picked up automatically)"

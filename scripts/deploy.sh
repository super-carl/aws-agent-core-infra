#!/bin/bash
# SuperCarl — one-command deploy.
# Pre-flight checks, CDK install + bootstrap, deploy, health check.
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()   { echo -e "${RED}[ERROR]${NC} $1"; }

AWS_REGION="us-east-1"
AWS_PROFILE=""
DRY_RUN=false
STACK_NAME="SuperCarlStack"

show_help() {
  cat <<EOF
SuperCarl — Deploy

Usage: ./scripts/deploy.sh -p <aws-profile> [-r region] [--dry-run]

  -p, --profile   AWS profile (required)
  -r, --region    AWS region (default: us-east-1)
  -d, --dry-run   Synthesize only, no deploy
  -h, --help      Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case $1 in
    -p|--profile) AWS_PROFILE="$2"; shift 2 ;;
    -r|--region)  AWS_REGION="$2"; shift 2 ;;
    -d|--dry-run) DRY_RUN=true; shift ;;
    -h|--help)    show_help; exit 0 ;;
    *) err "Unknown option: $1"; show_help; exit 1 ;;
  esac
done

[[ -z "$AWS_PROFILE" ]] && { err "AWS profile is required (-p)"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"

echo "=========================================="
echo " SuperCarl — Deploy"
echo "=========================================="
info "Profile: $AWS_PROFILE   Region: $AWS_REGION"

# Pre-flight
command -v aws >/dev/null    || { err "AWS CLI not installed"; exit 1; }
command -v npx >/dev/null    || { err "Node.js/npm not installed"; exit 1; }
command -v docker >/dev/null || { err "Docker not installed (Runtime container build)"; exit 1; }
docker info >/dev/null 2>&1  || { err "Docker daemon not running"; exit 1; }
aws sts get-caller-identity --profile "$AWS_PROFILE" >/dev/null 2>&1 || { err "Bad AWS profile '$AWS_PROFILE'"; exit 1; }
ACCOUNT_ID=$(aws sts get-caller-identity --profile "$AWS_PROFILE" --query Account --output text)
ok "AWS account: $ACCOUNT_ID"

cd "$ROOT/infra"
info "Installing CDK deps..."; npm install --silent 2>&1 | tail -1
info "Type-checking..."; npx tsc --noEmit && ok "TypeScript OK"

export CDK_DEFAULT_ACCOUNT="$ACCOUNT_ID"
export CDK_DEFAULT_REGION="$AWS_REGION"

if [[ "$DRY_RUN" == "true" ]]; then
  warn "DRY RUN — synth only"
  npx cdk synth --profile "$AWS_PROFILE" >/dev/null && ok "Synth succeeded"
  exit 0
fi

BOOTSTRAP=$(aws ssm get-parameter --name "/cdk-bootstrap/hnb659fds/version" --profile "$AWS_PROFILE" --region "$AWS_REGION" --query Parameter.Value --output text 2>/dev/null || echo 0)
if [[ "$BOOTSTRAP" -lt 30 ]]; then
  warn "Bootstrapping CDK (v$BOOTSTRAP < 30)..."; npx cdk bootstrap --profile "$AWS_PROFILE"
else ok "CDK bootstrap up to date (v$BOOTSTRAP)"; fi

info "Deploying $STACK_NAME (5-10 min: Docker build + CloudFormation)..."
npx cdk deploy --require-approval never --profile "$AWS_PROFILE" --outputs-file "$ROOT/cdk-outputs.json"
ok "Stack deployed"

API_URL=$(python3 -c "import json;print(json.load(open('$ROOT/cdk-outputs.json'))['$STACK_NAME']['ApiUrl'])" 2>/dev/null || echo N/A)
echo ""; info "API: $API_URL"
info "Health check:"; curl -s "${API_URL}health" || true; echo ""
echo ""
warn "Next: set your SuperCarl API key:"
echo "  aws secretsmanager put-secret-value --secret-id supercarl/api-key \\"
echo "    --secret-string '{\"api_key\":\"YOUR_KEY\"}' --profile $AWS_PROFILE --region $AWS_REGION"
echo ""
ok "Done. See scripts/post-deploy.sh for SES/Slack delivery + observability setup."

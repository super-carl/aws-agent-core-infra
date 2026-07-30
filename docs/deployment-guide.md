# SuperCarl - Deployment Guide

## 1. Prerequisites
- AWS CLI configured with a profile that can deploy CloudFormation/IAM/Bedrock.
- Node.js 18+, Python 3.12+, Docker running, AWS CDK v2.
- Bedrock model access enabled in your region for Sonnet 4.5 (and Haiku 4.5).

## 2. Deploy
```bash
./scripts/deploy.sh -p <your-aws-profile>            # full deploy
./scripts/deploy.sh -p <your-aws-profile> --dry-run  # synth only
```
The script runs pre-flight checks, installs CDK deps, type-checks, bootstraps if
needed, deploys, and runs a health check. Outputs are written to `cdk-outputs.json`.

## 3. Post-deploy config
```bash
# SuperCarl MCP: store your key AND the MCP URL - this enables the live MCP path.
# The agent connects to the MCP directly; both fields must be present.
aws secretsmanager put-secret-value --secret-id supercarl/api-key \
  --secret-string '{"api_key":"YOUR_KEY","mcp_url":"https://api.supercarl.ai/mcp"}' \
  --profile <profile>

# Optional: Slack + SES (see scripts/post-deploy.sh)
```

If the secret has no `mcp_url`, the agent falls back to the mock Action Group
executors, so the stack stays deployable and testable offline - no live data until
you add `mcp_url` as above.

## 4. Get a Cognito token (client-credentials)
```bash
ACCOUNT=$(aws sts get-caller-identity --query Account --output text --profile <profile>)
CLIENT_ID=$(jq -r '.SuperCarlStack.UserPoolClientId' cdk-outputs.json)
# client secret: read from the Cognito console or describe-user-pool-client
TOKEN=$(curl -s -X POST \
  "https://supercarl-${ACCOUNT}.auth.us-east-1.amazoncognito.com/oauth2/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "grant_type=client_credentials&client_id=${CLIENT_ID}&client_secret=<SECRET>&scope=supercarl-api/read supercarl-api/write" \
  | jq -r '.access_token')
```

## 5. Submit a research task
```bash
API=$(jq -r '.SuperCarlStack.ApiUrl' cdk-outputs.json)

# health (no auth)
curl -s "${API}health"

# recruiting
curl -s -X POST "${API}research" \
  -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
  -d '{"prompt":"Senior backend engineers in Austin with AWS experience","useCase":"recruiting","channels":["ses"]}'

# fetch result
curl -s "${API}research/<taskId>" -H "Authorization: Bearer ${TOKEN}"

# schedule a daily BD run
curl -s -X POST "${API}research/schedule" \
  -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
  -d '{"prompt":"Series-A fintech companies hiring in NYC","useCase":"bd","scheduleExpression":"rate(1 day)","channels":["slack"]}'
```

## 6. Observability
- Logs: CloudWatch log groups for the orchestrator, executors, and API Gateway.
- Traces: enable CloudWatch Transaction Search (OTEL from the Runtime).
- Audit: CloudTrail trail `supercarl-trail` → S3 + CloudWatch.
- Alarms: SNS topic `supercarl-alerts` (runtime user errors, guardrail interventions).

## 7. Cleanup
```bash
cd infra && npx cdk destroy --profile <your-aws-profile>
```
The S3 bucket uses `RemovalPolicy.DESTROY` with `autoDeleteObjects`.

## Troubleshooting
- **Docker not running** → start Docker Desktop (Runtime build needs it).
- **Bedrock AccessDenied** → enable model access for Sonnet 4.5 in the region.
- **429 from SuperCarl API** → executor surfaces a retryable tool error; the agent backs off.
- **Empty shortlist** → check the executor still points at the mock vs the real API base URL.

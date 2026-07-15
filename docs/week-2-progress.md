# Weeks 2-3 - Serverless Infrastructure (Progress)

Per the implementation plan, the focus is CDK base, executors returning data, and
observability.

## CDK base - _Done when: CDK deploy OK_

| Deliverable | Status | Where |
|-------------|--------|-------|
| Cognito, API Gateway, Secrets Manager, DynamoDB task table, Lambda stubs | Done | `infra/lib/supercarl-stack.ts` |
| One-command deploy | Done | `scripts/deploy.sh` (verified on account <your-account-id>) |

## Executors - _Done when: first Action Groups return data_

| Deliverable | Status | Where |
|-------------|--------|-------|
| people_search + profile_lookup with validation + structured shaping | Done | `functions/people_search`, `functions/profile_lookup` |
| company_search + deliver_results | Done | `functions/company_search`, `functions/deliver_results` |
| Input validation (required fields, length caps, limit clamping) | Done | each `index.py` |
| Rate-limit handling (429 retry with exponential backoff) | Done | `supercarl_client.call_supercarl` |
| Structured shaping (only fields the agent should see) | Done | each executor |
| Unit tests (18 assertions, all green) | Done | `tests/test_executors.py` |

Executors return data against the mock contract today and switch to the live
SuperCarl API by setting `SUPERCARL_API_BASE_URL` (no code change).

## Observability - _Done when: logs and traces flowing_

| Deliverable | Status | Where |
|-------------|--------|-------|
| CloudWatch dashboard (single pane across all services) | Done | `Dashboard` in the stack (`DashboardUrl` output) |
| CloudTrail across all services | Done | `supercarl-trail` -> S3 + CloudWatch |
| Per-service log groups | Done | API GW, orchestrator, executors, Runtime |
| Alarms -> SNS | Done | runtime user-errors, guardrail interventions |
| Per-step trace emission (STEP#n) for QA + latency tuning | Done | agent records `tool`, `input`, `status`, `latencyMs`, `ts` to DynamoDB per tool call |

### Dashboard widgets
- API Gateway: request count, 4XX/5XX, latency p50/p99
- Orchestrator: invocations / errors / throttles / duration
- Action Group executors: invocations + errors (all four)
- AgentCore Runtime: invocations + user errors
- Guardrails: interventions
- DynamoDB: consumed write capacity + throttles

## Verified on AWS (account <your-account-id>, us-east-1)
- Stack deploys clean (CDK deploy OK).
- `/v1/health` returns healthy; Cognito client-credentials auth issues tokens.
- `POST /v1/research` creates a task, persists state in DynamoDB, invokes the Runtime.
- Action Group executors return shaped data when invoked directly.
- CloudWatch dashboard `supercarl` created; CloudTrail + log groups flowing.

## Open dependency (carried from Week 1)
- **Bedrock model access** must be enabled at the account level (console:
  Bedrock > Model access > Claude Sonnet 4.6) for the full agent loop to complete.
  Until then the agent reaches Bedrock and is denied with `AccessDeniedException`
  (a one-time account toggle, not a stack issue).
- Real SuperCarl API endpoints + sandbox keys (expected end of Week 1 per SOW).

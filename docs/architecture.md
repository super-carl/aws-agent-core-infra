# SuperCarl - Architecture

Serverless, AWS-native, single-tenant per deployment. Default region `us-east-1`.
The entire stack is one CDK app (`infra/lib/supercarl-stack.ts`) deployed with one
command into the deployer's own AWS account.

## Components

| Tier | Component | CDK construct | Role |
|------|-----------|---------------|------|
| Entry | API Gateway + Cognito | `RestApi`, `UserPool` (client-credentials) | Authenticated REST task submission |
| Entry | EventBridge Scheduler | `scheduler:CreateSchedule` (runtime) + `SchedulerRole` | Recurring/scheduled research triggers |
| Orchestration | Orchestrator Lambda | `functions/orchestrator` | Creates task, invokes Runtime, persists state |
| Orchestration | DynamoDB | `supercarl-tasks` single table | Task-state machine (META / STEP#n / RESULT) |
| Agent | AgentCore Runtime | `agentcore.Runtime` (ARM64) | Strands agent: reasoning + tool routing |
| Agent | Memory | `agentcore.Memory` (Semantic + Summarization + UserPreference) | STM (session loop) + LTM (deployer ICP) |
| Agent | Guardrail | `bedrock.CfnGuardrail` | Moderation, PII redaction, denied topics |
| Tools | Action Group Lambdas | `functions/{people_search,profile_lookup,company_search,deliver_results}` | SuperCarl API executors |
| External | SuperCarl API | (via `supercarl_client.py`) | Source of all profile data |
| Delivery | SES + Slack/Teams | `deliver_results` | Formatted shortlist delivery |
| Storage | Secrets Manager | `supercarl/api-key`, `supercarl/slack-webhook` | API credentials |
| Storage | S3 | `supercarl-{account}-{region}` | Artifact retention + CloudTrail logs |
| Observability | CloudWatch / CloudTrail / OTEL | LogGroups, Alarms, SNS, Trail | Logs, traces, audit, alarms |

## Request flow (on-demand)

1. Client gets a Cognito token (client-credentials flow) and `POST /v1/research`.
2. API Gateway authorizes (write scope) → **Orchestrator Lambda**.
3. Orchestrator writes a `TASK#{id} / META` record (`status=in_progress`) to DynamoDB.
4. Orchestrator invokes the **AgentCore Runtime** (`invoke_agent_runtime`).
5. The Strands agent reasons over the brief and routes to tools:
   - recruiting → `people_search` (+ `profile_lookup` to enrich strong candidates)
   - bd → `company_search` then `people_search`
6. Each tool is an Action Group **Lambda** that calls the SuperCarl API, validates,
   handles rate limits, and shapes the response to only the fields the agent should see.
7. The agent synthesizes a shortlist (grounded entirely in API results) and calls
   `deliver_results` → SES / Slack + S3 artifact.
8. Orchestrator writes `TASK#{id} / RESULT`, sets `status=completed`, returns the task id.

## Request flow (scheduled)

`POST /v1/research/schedule` creates an EventBridge schedule targeting the
orchestrator with `{"scheduled": true, ...}`. On fire, the orchestrator runs the
same `_execute()` path unattended. State is in DynamoDB, so runs are auditable and
resumable.

## Multi-step state & resumability

DynamoDB holds the task state machine so long-running and scheduled loops survive
across invocations. `STEP#{n}` items give an end-to-end trace of tool routing per
task: the agent records `tool`, `input`, `status`, `latencyMs`, and `ts` for every
tool call, used for QA and latency tuning.

## Observability

A single CloudWatch dashboard (`supercarl`) spans every tier: API Gateway
(requests, 4XX/5XX, latency p50/p99), orchestrator and the four executors
(invocations / errors / duration), AgentCore Runtime (invocations + user errors),
Guardrails (interventions), and DynamoDB (capacity + throttles). CloudTrail logs
all API calls to S3 + CloudWatch; alarms publish to the `supercarl-alerts` SNS
topic.

## Live SuperCarl integration (MCP)

The production SuperCarl API is an **MCP server** (`https://api.supercarl.ai/mcp`),
not REST. The agent connects to it directly over MCP (Streamable HTTP) using the
key + URL stored in Secrets Manager (`supercarl/api-key` as
`{api_key, mcp_url}`), and is given **only the search/read tools**:
`people_search`, `people_lookup_batch`, `company_search`, `company_search_batch`,
`jobs_search`, `posts_search`, `query_search_result`.

Write-capable MCP tools (`send_communication`, `project_action`, `contacts_*`,
`watch_signals`, `super_carl_action`, `social_proximity_research`) are **excluded
by an allowlist** so the agent can never send outreach or mutate the account.
Delivery happens only through our controlled `deliver_results` channel
(SES/Slack/S3). If the MCP creds are absent, the agent falls back to the mock
Action Group executors - so the stack stays deployable and testable offline.

## Async submission

`POST /v1/research` creates the task, fires an asynchronous self-invocation of the
orchestrator (the worker), and returns `202 {taskId, status:"processing"}`
immediately - the agent loop runs in the background (API Gateway has a hard 29s
limit). Clients poll `GET /v1/research/{taskId}` for status and the shortlist.
The worker Lambda has a 4-minute timeout (240s) to cover multi-step loops.

## Delivery

`deliver_results` renders the shortlist into channel-specific templates:
- **SES**: multipart email with an HTML card layout plus a plain-text fallback.
- **Slack/Teams**: Block Kit payload (header, brief context, one section per profile).
- **S3**: the raw shortlist JSON is always written to `shortlists/{taskId}.json`
  for retention and audit.

All rendered fields are HTML-escaped. Delivery targets are configured
post-deploy (verified SES identity; Slack webhook in Secrets Manager).

## Scheduling

`POST /v1/research/schedule` creates an EventBridge schedule (in the `supercarl`
group) that targets the orchestrator with `{"scheduled": true, ...}`. On fire the
orchestrator runs the same `_execute()` path unattended. State persists in
DynamoDB, so scheduled runs are auditable and resumable.

## Safety

- **Guardrails**: content filters (sexual, violence, hate, insults, misconduct;
  input side), PII (email anonymized; SSN/credit-card blocked), denied topics
  (legal advice, financial advice, scoring beyond API data). Prompt-attack
  filtering is left off by design - it was flagging the agent's own system prompt.
- **Grounding**: the system prompt forbids emitting any field not present in a
  SuperCarl API result; every profile carries `source = supercarl_api`. A
  deterministic grounding pass in `deliver_results` enforces this on the way out
  (strips unknown fields, drops identity-less rows, forces the source) as
  defence-in-depth.
- **Verification**: `scripts/verify-guardrails.sh` exercises the deployed
  guardrail via `ApplyGuardrail` (no model access required) - denied topics and
  PII are intervened on, benign briefs pass.

## Extensions (future)

- AgentCore **Gateway** (MCP) + **Code Interpreter** can be added to the stack (the
  QuickStart pattern this is based on includes both).
- Extract the in-agent tool wrappers into a Gateway target if you prefer MCP routing
  over direct Lambda invoke.

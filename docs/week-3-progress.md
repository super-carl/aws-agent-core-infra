# Week 3 - Integration, State & Delivery (Progress)

Week 3 rounds out the serverless infrastructure into a working state, scheduling,
and delivery layer. Because the full agent loop is gated on account-level Bedrock
model access (a console toggle), this week pulls forward the state and delivery
work that does not depend on the model, keeping the system demoable.

## Delivery

| Deliverable | Status | Where |
|-------------|--------|-------|
| Channel-specific templates (SES HTML + plain-text multipart) | Done | `functions/deliver_results/_render_html`, `_render_text` |
| Slack Block Kit formatting (header, context, sections) | Done | `functions/deliver_results/_render_slack_blocks` |
| HTML escaping on all rendered fields | Done | `functions/deliver_results/_esc` |
| Artifact retention to S3 | Done | `deliver_results` writes `shortlists/{taskId}.json` |

## State machine

| Deliverable | Status | Where |
|-------------|--------|-------|
| Task lifecycle (in_progress -> completed / failed) | Done | `orchestrator._execute` / `_update_status` |
| Status + step trace + result retrieval (`GET /v1/research/{taskId}`) | Done | `orchestrator._get_task` |
| List recent tasks (`GET /v1/research`) | Done | `orchestrator._list_tasks` (GSI `byCreatedAt`) |
| Input validation (useCase enum, channels, prompt length) | Done | `orchestrator._validate` |
| Structured JSON logging (Logs Insights friendly) | Done | `orchestrator._log` |

## Scheduling

| Deliverable | Status | Where |
|-------------|--------|-------|
| Create scheduled run (`POST /v1/research/schedule`) | Done | `orchestrator._create_schedule` -> EventBridge Scheduler |
| Schedule group + least-privilege scheduler role | Done | `infra/lib/supercarl-stack.ts` |
| Unattended execution path (`{"scheduled": true}`) | Done | `orchestrator.lambda_handler` |

## Observability

| Deliverable | Status | Where |
|-------------|--------|-------|
| Orchestrator error-rate alarm -> SNS | Done | `OrchestratorErrorsAlarm` |
| Dashboard header/overview widget | Done | `Dashboard` TextWidget |
| Existing dashboard + CloudTrail + step traces (Week 2) | Done | carried forward |

## Agent logic & guardrails

| Deliverable | Status | Where |
|-------------|--------|-------|
| Agent on Runtime with all four tools attached | Done | `agentcore_agents/app.py` |
| Explicit tool routing for recruiting and BD | Done | system prompt (recruiting: people_search -> profile_lookup; bd: company_search -> people_search) |
| Guardrails (moderation, PII, denied topics, prompt-attack) | Done | `Guardrail` in the stack |
| Guardrails verified live (no model access needed) | Done | `scripts/verify-guardrails.sh` - 5/5 passing |
| Grounding / automated-reasoning pass before delivery | Done | `deliver_results._ground` (forces `source=supercarl_api`, strips unknown fields, drops identity-less rows) |

Guardrail verification (live, account <your-account-id>):
- Financial-advice prompt -> `GUARDRAIL_INTERVENED`
- Legal-advice prompt -> `GUARDRAIL_INTERVENED`
- Email + SSN -> `GUARDRAIL_INTERVENED`
- Benign recruiting / BD briefs -> `NONE`

## Live SuperCarl integration (MCP)

| Deliverable | Status | Where |
|-------------|--------|-------|
| Model access enabled; agent loop runs on Sonnet 4.5 | Done | Runtime `MODEL_ID` |
| Connect agent to the live SuperCarl MCP server | Done | `agentcore_agents/app.py` (`_build_mcp_client`) |
| Search/read tools only (write tools excluded by allowlist) | Done | `SAFE_MCP_TOOLS` |
| Creds in Secrets Manager (`{api_key, mcp_url}`) | Done | `supercarl/api-key` |
| Mock fallback when MCP not configured | Done | `app.py` path selection |
| Async submission (fixes API Gateway 29s timeout) | Done | `POST /v1/research` -> worker; poll `GET` |

The agent is given only `people_search`, `people_lookup_batch`, `company_search`,
`company_search_batch`, `jobs_search`, `posts_search`, `query_search_result`.
Write-capable MCP tools (`send_communication`, `project_action`, `contacts_*`,
etc.) are deliberately excluded; delivery stays on our `deliver_results` channel.

Robustness: `deliver_results` is idempotent and writes the task RESULT + marks it
`completed` on first delivery (so a task finishes even if the model keeps
talking); `_ground` tolerates shape variance (bare list / alternate keys); the
worker has async retries disabled to avoid duplicate MCP calls.

**Verified end to end (live MCP):** a recruiting brief
("Senior backend engineers in Austin with AWS experience") returned **25 real
SuperCarl profiles** (real people at real Austin companies - not reproduced here
for privacy), one delivery, task `completed` in ~32s.

## Tests

| Suite | Result |
|-------|--------|
| Executors + grounding (`tests/test_executors.py`) | 22 passing |
| Orchestrator routing + validation + async (`tests/test_orchestrator.py`) | 14 passing |
| Guardrails live (`scripts/verify-guardrails.sh`) | 5 passing |

Run: `python3 tests/test_executors.py && python3 tests/test_orchestrator.py`
and `AWS_PROFILE=<profile> bash scripts/verify-guardrails.sh`

## Verified on AWS (account <your-account-id>, us-east-1)
- Stack deploys clean (fast path; no Runtime container rebuild).
- Action Group executors return shaped data when invoked directly.
- `POST /v1/research/schedule` creates an EventBridge schedule.
- CloudWatch dashboard + alarms present; CloudTrail flowing.

## Resolved
- Bedrock model access enabled (Sonnet 4.5) - full agent loop runs end to end.
- Live SuperCarl API wired (MCP) - real profiles flowing.

## Notes
- Sonnet 4.6 / Haiku 4.5 can be switched in via `MODEL_ID` once access is granted.
- SES/Slack delivery is optional config; the S3 artifact is always written.

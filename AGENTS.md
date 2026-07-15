# AGENTS.md - guide for coding agents

This file tells an AI coding agent (Claude Code, Codex, OpenClaude / goose,
Cursor, …) how to set up and run **SuperCarl** for a user who just opened this
repo. Read it top to bottom before acting.

SuperCarl is an autonomous research worker on Amazon Bedrock AgentCore: a
natural-language brief becomes a shortlist of real people / company profiles,
grounded in the live SuperCarl data and delivered to email / Slack.

## First: ask the user for what you need

Ask for these up front (don't guess, don't hardcode secrets into files):

Two connections are required for the live agent loop to work:

1. **SuperCarl MCP** - the live data source. The user provides a SuperCarl API
   key; the agent connects to `https://api.supercarl.ai/mcp` with it.
2. **A model (LLM)** - the agent reasons with **Amazon Bedrock**. The user's AWS
   account must have **Bedrock model access enabled** for Claude (Sonnet 4.5/4.6
   or Haiku 4.5) in-region. (When consuming SuperCarl from another agent
   framework instead, that agent's own LLM provider plays this role.)

Also ask for:
3. **AWS credentials** - to deploy the full stack (agent + guardrails + delivery +
   scheduling) into their account. Or run **locally** (no cloud, deterministic,
   mock data) for a quick offline try.
4. **Delivery targets (optional)** - a Slack webhook URL and/or a verified SES
   sender+recipient, if they want the shortlist emailed / posted.

Do not print secret values back to the user or write them into tracked files.
Secrets go into Secrets Manager (cloud) or a gitignored env (local).

## Pick a path

### Path A - run locally (fastest, no AWS)
Best for a first look. No account, no credentials.
```bash
./scripts/run-local.sh            # http://127.0.0.1:8080  (or: docker compose up)
curl -s -X POST localhost:8080/v1/research \
  -H 'Content-Type: application/json' \
  -d '{"prompt":"Senior backend engineers in Austin","useCase":"recruiting"}' | jq
```
See [docs/local-development.md](docs/local-development.md).

### Path B - deploy to the user's AWS account (full system)
Needs: AWS CLI configured, Docker running, Node 18+, Python 3.12+, CDK v2, and
Bedrock model access for Claude in-region.
```bash
./scripts/deploy.sh -p <aws-profile>
# then set the SuperCarl MCP credential:
aws secretsmanager put-secret-value --secret-id supercarl/api-key \
  --secret-string '{"api_key":"<SUPERCARL_KEY>","mcp_url":"https://api.supercarl.ai/mcp"}' \
  --profile <aws-profile>
# optional delivery:
AWS_PROFILE=<aws-profile> bash scripts/post-deploy.sh
```
Details: [docs/deployment-guide.md](docs/deployment-guide.md).

## Run a research task

- Cloud: `POST /v1/research {prompt, useCase: recruiting|bd, channels}` returns a
  `taskId` immediately; poll `GET /v1/research/{taskId}` until `completed`.
  Full runbook + auth: [docs/deployment-guide.md](docs/deployment-guide.md).
- Local: same endpoints on `localhost:8080` (no auth).
- Click-through: [Postman](docs/postman/) or [Bruno](docs/bruno/) collections.

## Consuming SuperCarl as an MCP directly

If the user just wants SuperCarl's tools inside their own agent (no AWS), add the
**SuperCarl MCP server** to their framework - see
[docs/mcp-integration.md](docs/mcp-integration.md). This repo's value-add on top
of raw MCP is the agentic loop: tool routing, guardrails, grounding, delivery,
scheduling, and state - deployed as their own AWS service.

## Safety rules (do not violate)

- The agent uses **search/read tools only**. Never enable SuperCarl's
  write-capable MCP tools (`send_communication`, `project_action`, `contacts_*`,
  `watch_signals`, `super_carl_action`, `social_proximity_research`) - the
  allowlist in `agentcore_agents/app.py` (`SAFE_MCP_TOOLS`) is intentional.
- Never commit secrets. `.gitignore` already excludes env files and credentials.
- Delivery goes only through the `deliver_results` channel, not MCP outreach tools.

## Repo map

- `agentcore_agents/app.py` - the Strands agent (MCP tools + routing + guardrails).
- `functions/orchestrator/` - API/EventBridge → async worker → Runtime; DynamoDB state.
- `infra/lib/supercarl-stack.ts` - the whole AWS stack (one CDK app).
- `local/` - offline API server. `mock/` - mock SuperCarl contract.
- `scripts/` - deploy, post-deploy, run-local, verify-guardrails, make-postman-env.
- `docs/` - architecture, api-contract, mcp-integration, deployment.

Verify everything still works before handing back:
`python3 tests/test_executors.py && python3 tests/test_orchestrator.py`.

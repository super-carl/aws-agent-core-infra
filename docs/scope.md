# SuperCarl - Scope

## What this is

An open-source, self-deployable autonomous research worker on Amazon Bedrock
AgentCore. Clone the repo, bring your own AWS account and your own SuperCarl API
key, and turn a single natural-language prompt into a synthesized shortlist of real
people / company profiles, grounded entirely in the live SuperCarl data.

The repository is the product: a reproducible reference implementation of the
"SuperCarl + AWS" blueprint, demonstrating the Agent-First API inside a live agentic
loop. It is single-tenant per deployment - you run your own infrastructure; there is
no shared backend.

## Two ways to run it

Both are self-serve and run on your own accounts:

- **In an open agent** (OpenClaw, goose, Claude Code, …) - connect the SuperCarl MCP
  and a model of your choice (Amazon Bedrock, Anthropic, or a local Claude CLI), then
  work in plain language. Fastest path; no AWS deploy required.
- **As a deployed service** on Amazon Bedrock AgentCore - one-command CDK deploy into
  your AWS account, with Runtime, Memory, Guardrails, API, delivery and scheduling.

## In scope

- Single CDK app, one-command self-deploy (single-tenant per deployment).
- Agentic loop over the SuperCarl API (People / Profile / Company search) - read-only.
- Two trigger modes: on-demand REST and scheduled.
- Two use cases: recruiting and business development (Company → People loop).
- Structured shortlist delivery to SES and/or Slack/Teams; S3 artifact retention.
- Memory (STM + LTM), Guardrails (moderation, PII, denied topics), observability.
- Agent-framework integration guides (OpenClaw, goose) using the SuperCarl MCP.

## Out of scope

- Shared / multi-tenant infrastructure (each deployer runs their own).
- Hosting or proxying the SuperCarl API (deployers bring their own key).
- A UI beyond the REST API and the delivery channels.

## Success criteria

- One-command deploy stands up the full stack in your own AWS account.
- Recruiting prompt → shortlist of 10+ relevant candidate profiles.
- BD prompt → Company Search → People Search loop returns targeted contacts.
- Output grounded entirely in SuperCarl API data (no hallucinated fields).
- Guardrails verified (PII redacted, denied topics blocked).
- The same agent is reproducible from an open agent (OpenClaw) and from the AWS
  deployment.

## Requirements

- An AWS account with **Bedrock model access** enabled for a Claude model in your
  region (e.g. `us-east-1`).
- A **SuperCarl API key** (the agent uses search/read tools only; write-capable tools
  are never enabled).
- For local / open-agent use: Node.js ≥ 24.15 and OpenClaw (or another MCP-capable
  agent). For the AWS deploy: AWS CLI, Docker, and AWS CDK v2.

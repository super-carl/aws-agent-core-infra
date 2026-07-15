# SuperCarl in OpenClaw - end-user use case

[OpenClaw](https://openclaw.ai) is an open-source, self-hosted agent framework
that connects an LLM to tools **and to your messaging apps** (Slack, WhatsApp,
Telegram, Discord, iMessage, WebChat), with a scheduled **"heartbeat"** for
proactive, always-on tasks. That makes it a natural home for SuperCarl: sourcing
from the chat you already live in.

## The use case: a sourcing copilot in your chat

**On-demand (in any channel).** A recruiter or BD rep messages their OpenClaw
agent - in Slack or WhatsApp - *"find senior backend engineers in Austin with AWS
experience."* OpenClaw calls SuperCarl's `people_search` over MCP and replies with
a shortlist right in the thread. For BD: *"Series-A fintech companies in NYC
hiring backend engineers, and a few contacts at each"* → `company_search` then
`people_search` (the Company → People loop).

**Always-on (heartbeat).** OpenClaw's scheduled heartbeat runs a saved brief on a
cadence - e.g. every morning, *"new Series-A fintech engineering leaders in NYC"* -
and proactively DMs the fresh shortlist. This is the same "set-and-forget"
sourcing our AWS deployment does with EventBridge, but delivered into the user's
messaging app.

Either way the user never touches AWS or an API - SuperCarl is just a tool inside
the agent they already use.

**Requirements (both needed):** an **LLM provider** in OpenClaw (Amazon Bedrock,
Anthropic, or the local Claude CLI via `claude-cli/<model>`) - Bedrock needs AWS
credentials with model access - and the **SuperCarl MCP** (a SuperCarl API key).
OpenClaw needs Node >= 24.15; the SuperCarl MCP transport is `streamable-http`.

## Setup

1. Install OpenClaw and configure an LLM provider (Amazon Bedrock, Anthropic,
   or the local Claude CLI via `claude-cli/<model>`).
2. Add the SuperCarl MCP server. Either merge
   [openclaw.mcp.json](openclaw.mcp.json) into `~/.openclaw/openclaw.json` and set
   your key, or use the CLI:
   ```bash
   openclaw mcp add supercarl \
     --url https://api.supercarl.ai/mcp \
     --transport streamable-http \
     --header "Authorization: Bearer $SUPERCARL_API_KEY" \
     --include 'people_search,people_lookup_batch,company_search,company_search_batch,jobs_search,posts_search,query_search_result'
   ```
3. Verify connectivity and see the discovered tools:
   ```bash
   openclaw mcp doctor supercarl --probe
   ```
4. Restart the gateway. Now message your agent from any connected channel.

## Safety (built in)

`toolFilter.include` restricts OpenClaw to SuperCarl's **search/read** tools only.
Write-capable tools (`send_communication`, `project_action`, `contacts_*`,
`watch_signals`, `super_carl_action`, `social_proximity_research`) are never
exposed - the agent can research and shortlist, but cannot send outreach or change
the account. This mirrors the allowlist our AWS deployment enforces.

## Demo talk track

- "This is the end-user experience Michael asked for: SuperCarl inside an open
  agent the user already runs - here, in Slack."
- "I just ask in plain language; OpenClaw calls SuperCarl over MCP and brings back
  real people at real companies, grounded and traceable."
- "The heartbeat makes it proactive - a daily shortlist delivered to my DMs, no
  clicks."
- "It's search/read only - safe by configuration, no outreach on autopilot."

## The three ways to consume SuperCarl (for the client)

| Path | Who it's for |
|------|--------------|
| **OpenClaw** (this) | End users who live in messaging apps; proactive/scheduled sourcing |
| **goose** ([../goose/](../goose/)) | Developers/power users in an open terminal agent |
| **This repo on AWS** | Teams wanting a hardened, hands-off service (guardrails, delivery, state) |

All three consume the same live SuperCarl MCP.

# Consuming SuperCarl from your agent (MCP)

SuperCarl exposes an **MCP server** (Model Context Protocol) so it plugs directly
into the agent ecosystem - Claude Code, Codex, goose, Cursor, and any MCP client.
This repo's AWS deployment builds an agentic loop *on top of* that MCP (routing,
guardrails, grounding, delivery, scheduling, state).

There are two ways to use SuperCarl. Pick based on the end user.

---

## Mode 1 - add SuperCarl MCP directly to your agent

Best when the user already works inside an agent framework and just wants
SuperCarl's search tools available in their chat/session. No AWS required.

- **Endpoint:** `https://api.supercarl.ai/mcp` (Streamable HTTP)
- **Auth:** `Authorization: Bearer <SUPERCARL_API_KEY>`

### Claude Code

```bash
claude mcp add --transport http supercarl https://api.supercarl.ai/mcp \
  --header "Authorization: Bearer $SUPERCARL_API_KEY"
```

or commit a project `.mcp.json` (example in
[docs/agent-frameworks/mcp.json](agent-frameworks/mcp.json)):

```json
{
  "mcpServers": {
    "supercarl": {
      "type": "http",
      "url": "https://api.supercarl.ai/mcp",
      "headers": { "Authorization": "Bearer ${SUPERCARL_API_KEY}" }
    }
  }
}
```

### Codex

In `~/.codex/config.toml`:

```toml
[mcp_servers.supercarl]
url = "https://api.supercarl.ai/mcp"
# provide the bearer token per your Codex version's header/env mechanism
```

### OpenClaw

OpenClaw is an open-source, self-hosted agent that connects to your messaging apps
(Slack, WhatsApp, Telegram, …) with a scheduled heartbeat - ideal for a sourcing
copilot in chat. Add SuperCarl to `~/.openclaw/openclaw.json` (or `openclaw mcp
add`), restricting tools via `toolFilter.include`. Full use case + config:
[agent-frameworks/openclaw/](agent-frameworks/openclaw/).

### goose / other MCP clients

Add a remote (Streamable HTTP) MCP extension pointing at
`https://api.supercarl.ai/mcp` with the `Authorization: Bearer` header. Any
spec-compliant MCP client works the same way.

For a ready-to-run **goose** setup (config snippet, recipe, and a two-use-case
demo script), see [agent-frameworks/goose/](agent-frameworks/goose/) - it's the
end-user demo where an open agent consumes SuperCarl live.

> The user then just asks their agent things like *"find senior backend engineers
> in Austin"* and the agent calls SuperCarl's tools.

---

## Mode 2 - deploy this repo (SuperCarl + AWS)

Best when the user wants a **hardened, hands-off service**: the agent runs on
Bedrock AgentCore with tool routing for recruiting/BD, guardrails + grounding,
email/Slack delivery, scheduled runs, task state, and observability - all in
*their* AWS account. See [AGENTS.md](../AGENTS.md) and
[deployment-guide.md](deployment-guide.md).

Here the deployed service consumes the SuperCarl MCP for the user; end users hit
the REST API (or the Postman/Bruno collections), or schedule runs.

---

## The SuperCarl MCP tool surface

The server exposes ~21 tools. This project uses **search / read tools only**:

| Tool | Purpose |
|------|---------|
| `people_search` | Primary person discovery |
| `people_lookup_batch` | Load specific LinkedIn profiles |
| `company_search` | Find companies |
| `company_search_batch` | Resolve named companies before people_search |
| `jobs_search` | Job postings |
| `posts_search` | LinkedIn posts |
| `query_search_result` | Reshape a prior result into columns |

**Excluded on purpose** (write / account-mutating): `send_communication`,
`project_action`, `project_google_sheet_sync`, `contacts_export`,
`contacts_reconcile`, `watch_signals`, `super_carl_action`,
`social_proximity_research`, `send_*`.

`agent_session` is read-only (it attributes the session to a client). This repo's
AWS deployment omits it; the OpenClaw guide **does** allow it so SuperCarl sees the
calling agent as "OpenClaw" rather than the underlying model. Either choice is safe.

> Note: If you wire SuperCarl MCP directly into an agent (Mode 1), that agent *can*
> see the write tools. For unattended or demo use, instruct the agent to use only
> the search/read tools above - the same allowlist this repo enforces in
> `agentcore_agents/app.py` (`SAFE_MCP_TOOLS`).

---

## What a deployer provides (the three inputs)

1. **SuperCarl API key** - the MCP credential (required).
2. **AWS credentials** (to deploy Mode 2) **or an LLM/agent framework** (to run
   Mode 1 in their own agent).
3. **Delivery tokens (optional)** - Slack webhook and/or SES sender+recipient for
   notifications.

Nothing else is needed to go from a cloned repo to a working integration.

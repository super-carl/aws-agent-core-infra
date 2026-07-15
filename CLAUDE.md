# CLAUDE.md

Guidance for Claude Code working in this repo. The full agent guide is in
[AGENTS.md](AGENTS.md) - read it first.

Quick facts:
- SuperCarl = autonomous research worker on Bedrock AgentCore. One brief → a
  shortlist of real people/company profiles, grounded in the live SuperCarl data.
- Two ways to run: **local** (`./scripts/run-local.sh`, no AWS) or **deploy**
  (`./scripts/deploy.sh -p <profile>`).
- Ask the user for: SuperCarl API key; AWS creds (to deploy) or nothing (local);
  optional Slack/SES delivery targets. Never hardcode or print secrets.
- The agent uses **search/read MCP tools only** - never enable SuperCarl's
  write-capable tools (see `SAFE_MCP_TOOLS` in `agentcore_agents/app.py`).
- Verify: `python3 tests/test_executors.py && python3 tests/test_orchestrator.py`.

Consuming SuperCarl as an MCP directly from an agent framework:
[docs/mcp-integration.md](docs/mcp-integration.md).

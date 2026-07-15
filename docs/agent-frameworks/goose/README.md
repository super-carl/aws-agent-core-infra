# SuperCarl in goose

Consume SuperCarl's live tools from the open-source agent
[goose](https://block.github.io/goose/) over MCP. The user just chats; goose calls
SuperCarl. Covers both use cases - **recruiting** and **business development**.

**Requirements (both needed):**
- **An LLM provider** in goose - e.g. Amazon Bedrock (provider id `aws_bedrock`),
  which requires AWS credentials with Bedrock model access.
- **The SuperCarl MCP** - a SuperCarl API key; goose connects to
  `https://api.supercarl.ai/mcp`.

Quick CLI form (Bedrock as the LLM):

```bash
export GOOSE_PROVIDER=aws_bedrock
export GOOSE_MODEL="us.anthropic.claude-sonnet-4-5-20250929-v1:0"
export AWS_PROFILE=<profile-with-bedrock-access>
goose run --recipe docs/agent-frameworks/goose/supercarl-recipe.yaml \
  --params SUPERCARL_API_KEY=<your-supercarl-key> --no-session
```

## Setup (once)

1. Install goose (CLI or Desktop): <https://block.github.io/goose/docs/getting-started/installation>.
2. Configure an LLM provider in goose (Anthropic, OpenAI, Bedrock, …).
3. Add the SuperCarl MCP extension - either:
   - **Desktop**: Settings → Extensions → Add → *Remote (Streamable HTTP)*,
     URL `https://api.supercarl.ai/mcp`, header `Authorization: Bearer <your key>`.
   - **CLI/config**: paste [config-snippet.yaml](config-snippet.yaml) into
     `~/.config/goose/config.yaml` and set your key.
   - **Recipe (recommended for the demo)**: [supercarl-recipe.yaml](supercarl-recipe.yaml)
     pins the extension + guardrail instructions in one file:
     ```bash
     goose run --recipe supercarl-recipe.yaml --params SUPERCARL_API_KEY=carl_xxx --interactive
     ```

## Demo script (both use cases)

Open a goose session and just talk. Two beats:

**1. Recruiting**
> "Find senior backend engineers in Austin with AWS experience and give me a
> shortlist with a match reason for each."

goose calls `people_search` (and enriches), then returns a grounded shortlist.

**2. Business development**
> "Now switch to BD: find Series-A fintech companies in NYC that are hiring
> backend engineers, then find a couple of contacts at each."

goose calls `company_search`, then `people_search` scoped to those companies -
the Company → People loop, live.

### Talk track
- "This is the *end-user* view: an open agent, not our API. The user never
  touches AWS - SuperCarl is just an MCP tool inside goose."
- "The recipe restricts goose to **search/read** tools - the same allowlist our
  AWS service enforces - so it can't send outreach or change the account."
- "Everything is grounded in real SuperCarl data - real people at real companies."

### Safety in a live demo (important)
Unlike our AWS deployment, goose (Mode 1) can *see* SuperCarl's write tools. To
keep a live demo safe:
- The recipe's `instructions` tell goose to use search/read tools only. Keep them.
- Run goose in **manual tool-approval** mode (Settings → tool approval, or
  `goose configure`) so you approve each call - never approve `send_communication`,
  `project_action`, `contacts_*`, `watch_signals`, `super_carl_action`, or
  `social_proximity_research`.

## Two ways to consume SuperCarl

- **This (goose)** = SuperCarl's tools inside an open agent the user already runs.
- **The AWS deployment** (this repo) = a hardened, hands-off service: guardrails,
  delivery to email/Slack, scheduled runs, task state, observability.

> goose's config/recipe schema can shift between versions. If goose rejects a
> key, check its current extension docs - the essentials are: remote MCP,
> Streamable HTTP, `https://api.supercarl.ai/mcp`, Bearer auth.

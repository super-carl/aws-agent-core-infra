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

**Always-on (scheduled watch).** OpenClaw's cron runs a saved brief on a cadence
and proactively DMs the result. The useful shape is a *watch*, not a re-run: keep
a ledger of everyone already reported, and push a message only when someone **new**
shows up.

```bash
openclaw cron add \
  --name supercarl-watch \
  --cron "0 9,17 * * *" \
  --model claude-opus-4-8 \
  --announce --channel whatsapp --to "+15551234567" \
  --message "Search SuperCarl for <brief>. Compare against seen.json (candidates
             already reported) and rewrite it as the cumulative list. Rebuild the
             dashboard, badging this run's arrivals as NEW and sorting them first.
             Reply with a short chat digest naming only the new people - or one
             line saying there are none."
```

Twice a day the dashboard refreshes itself and only genuinely new matches reach
your phone. This is the same "set-and-forget" sourcing our AWS deployment does with
EventBridge, but delivered into the user's messaging app.

Two notes from running it:

- **Make the ledger cumulative, not an overwrite.** If you rewrite it with just
  the current top N, anyone who drops out of the ranking gets re-reported as NEW
  on a later run. Union it instead.
- Scheduled jobs run through the **Gateway**, so it has to be running
  (`openclaw gateway run`, or `openclaw gateway install && openclaw gateway start`
  to keep it up). Ad-hoc runs via `openclaw agent --local` do not need it.

**Build something, not just a list.** The point of running SuperCarl inside a
capable agent is that the agent can *act on* the data. Ask it to turn a search
into an artifact, for example:

> "Find senior backend engineers in Austin with AWS experience. Pick the 10
> strongest, then build me an HTML dashboard with a card per candidate: their ICP
> fit (quoting the SuperCarl evidence) and a **draft** personalized outreach
> message with a copy button. Open it when it's done."

OpenClaw runs the search over MCP, reasons about fit, writes a self-contained HTML
file, and opens it. Same pattern for other end points: a Slack/WhatsApp digest on
a schedule, a refreshing dashboard, or drafting (never sending) outreach.

> Keep drafting and sending separate. The tool allowlist excludes every
> outreach/write tool, so the agent can compose messages for a human to review and
> send, but cannot send them itself.

Either way the user never touches AWS or an API - SuperCarl is just a tool inside
the agent they already use.

**Requirements (both needed):** an **LLM provider** in OpenClaw (Amazon Bedrock,
Anthropic, or the local Claude CLI via `claude-cli/<model>`) - Bedrock needs AWS
credentials with model access - and the **SuperCarl MCP** (a SuperCarl API key).
OpenClaw needs Node >= 24.15; the SuperCarl MCP transport is `streamable-http`.

**Use a strong model.** Reasoning over search results is the hard part: prefer
**Claude Opus 4.8** or **Sonnet 5** (`claude-opus-4-8` / `claude-sonnet-5` on
Bedrock or via the Claude CLI provider). Smaller models struggle on complex briefs.

**Identify the agent.** SuperCarl attributes a session via its `agent_session`
tool. Allow that tool and have the agent bind a session with
`client_name="OpenClaw"` so SuperCarl sees **OpenClaw** rather than the underlying
model harness. (The config also sends `X-Client-Name` / `User-Agent` headers.)

**Readable terminal output.** Pipe the agent's markdown through a renderer such as
[`glow`](https://github.com/charmbracelet/glow) (`brew install glow`) so tables and
headings render instead of raw markdown.

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
5. *(For chat delivery only.)* Pair a messaging channel:
   ```bash
   openclaw channels list --all                              # the full catalog
   openclaw channels add --channel telegram --bot-token ...  # configure
   openclaw channels login --channel telegram                # link
   ```
   Search and dashboards work without this; it is only needed for the scheduled
   watch to push digests to your phone.

   > **Install channel plugins from npm, not ClawHub.** Only **Telegram** and
   > **iMessage** ship bundled on 2026.7.1; everything else is a plugin. Install
   > the official npm package:
   >
   > ```bash
   > openclaw plugins install @openclaw/whatsapp   # official - works
   > # NOT: openclaw plugins install clawhub:@openclaw/whatsapp
   > ```
   >
   > The ClawHub spec installs the same code as an untrusted third-party plugin,
   > which is denied the credential store
   > (`openKeyedStore is only available for trusted plugins in this release`). The
   > channel then pairs successfully and fails to start, which is a confusing place
   > to land. Installed from npm it is a trusted official install and runs. Restart
   > the gateway after installing (`openclaw gateway restart`).

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

# SuperCarl in OpenClaw — end to end

This is the whole path in one place: from a fresh machine to a SuperCarl sourcing
worker that runs on Amazon Bedrock, answers in plain language, builds you a
dashboard, runs on a schedule, and messages you on WhatsApp.

It reads top to bottom. Every command here was run on macOS with the versions noted;
where a step commonly goes wrong, the fix is inline rather than in a separate FAQ.

## What it is

You talk to an agent (OpenClaw) in plain language. The agent reasons with a model,
and calls SuperCarl as a set of tools over MCP. Two connections make it work, and
neither belongs to OpenClaw — you bring both:

```
                    ┌──────────────────┐
   you  ─ plain ──▶ │     OpenClaw     │  self-hosted agent, on your machine
        language    └───────┬──────────┘
                            │
              ┌─────────────┴──────────────┐
              ▼                             ▼
      ┌───────────────┐            ┌──────────────────┐
      │ Amazon Bedrock│            │  SuperCarl (MCP)  │
      │   the model   │            │  the tools/data   │
      └───────────────┘            └──────────────────┘
      reasons over results         people/company/jobs search
      (Claude on Bedrock)          Bearer <your API key>, read-only allowlist
```

- **The model** — Amazon Bedrock in this guide. It never sees your SuperCarl key; it
  only decides which tool to call and reasons over what comes back.
- **The tools** — SuperCarl over MCP. Restricted to search/read tools by an
  allowlist, so the agent can research and shortlist but cannot send outreach or
  change your account.

Everything after the two connections — scheduling, dashboards, WhatsApp — is what
OpenClaw adds on top.

---

## 0. Prerequisites

- **A SuperCarl account and API key** (Part 1).
- **An AWS account with Bedrock model access** for the Claude model you pick
  (Part 3). Credentials with `bedrock:InvokeModel` / `InvokeModelWithResponseStream`.
- **Node.js ≥ 24.15** (OpenClaw's floor). Check with `node --version`. On macOS the
  default Homebrew `node` is often older and broken; install `node@24` and put it
  first on `PATH`:
  ```bash
  brew install node@24
  echo 'export PATH="/opt/homebrew/opt/node@24/bin:$PATH"' >> ~/.zshrc
  exec zsh              # reload the shell, then confirm:
  node --version        # v24.15+ 
  ```
- **`glow`** (optional, for rendered markdown in the terminal): `brew install glow`.

---

## 1. Sign up for SuperCarl and get your API key

1. Create an account at SuperCarl and open the developer/API section of settings.
2. Generate an API key. It looks like `carl_...`. Treat it like a password.
3. Keep it out of committed files. Export it in your shell instead:
   ```bash
   export SUPERCARL_API_KEY="carl_xxxxxxxxxxxxxxxxxxxx"
   ```

> Connect your networks (e.g. LinkedIn) under SuperCarl **Integrations** before you
> rely on results. If a network is not connected, searches run against the rest only
> and the agent will tell you so — a real blind spot for people search.

---

## 2. Install OpenClaw

```bash
npm install -g openclaw
openclaw --version                      # 2026.7.x
openclaw onboard                         # guided setup: workspace, gateway, model, channels
```

`onboard` is interactive and sets up the local **gateway** (the background service
that runs scheduled jobs and messaging channels). You can also do each piece by hand,
as below.

---

## 3. Point the model at Amazon Bedrock

The model is a provider entry in OpenClaw's config. Add a Bedrock provider that uses
the Bedrock Converse streaming API, in your region, with the Claude model you have
access to.

First, make sure the model is enabled: in the **AWS console → Bedrock → Model access**,
request/enable the Claude model for your region (e.g. `us-east-1`).

Then add the provider to `~/.openclaw/openclaw.json` (merge into any existing
`models` block):

```jsonc
{
  "models": {
    "providers": {
      "bedrock": {
        "api": "bedrock-converse-stream",
        "region": "us-east-1",
        "models": [
          { "id": "us.anthropic.claude-sonnet-4-5-20250929-v1:0" }
        ]
      }
    }
  }
}
```

Bedrock reads AWS credentials from the standard chain — environment variables, or a
named profile:

```bash
export AWS_PROFILE=my-bedrock-profile           # or AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
export AWS_REGION=us-east-1
```

Make it the default model and confirm it is configured:

```bash
openclaw models set "bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
openclaw models list                            # your Bedrock model shows 'default, configured'
```

> Use a strong model. Reasoning over search results is the hard part — prefer Claude
> Opus 4.8 or Sonnet 5 where you have access. Smaller models struggle on complex
> briefs.
>
> The model provider is independent of everything below. If you would rather not wire
> Bedrock yet, any configured provider (Anthropic direct, or the local Claude CLI via
> `claude-cli/<model>`) works the same — only this section changes.

---

## 4. Connect SuperCarl over MCP

Register SuperCarl as an MCP server, restricted to its search/read tools:

```bash
openclaw mcp add supercarl \
  --url https://api.supercarl.ai/mcp \
  --transport streamable-http \
  --header "Authorization=Bearer $SUPERCARL_API_KEY" \
  --header "X-Client-Name=OpenClaw" \
  --header "User-Agent=OpenClaw" \
  --include 'agent_session,people_search,people_lookup_batch,company_search,company_search_batch,jobs_search,posts_search,query_search_result'
```

What the flags do:

- `--include` is the **allowlist**. Only these tools are ever exposed. Write-capable
  tools (`send_communication`, `contacts_*`, `project_action`, `super_carl_action`,
  `watch_signals`, `social_proximity_research`) are never reachable — the agent
  researches and drafts, a human sends.
- `agent_session` is included on purpose: it lets the agent identify itself to
  SuperCarl as **OpenClaw** (via `client_name`), so your SuperCarl session shows
  OpenClaw rather than the underlying model harness. The `X-Client-Name` /
  `User-Agent` headers reinforce this.

Prefer editing config directly? Merge
[openclaw.mcp.json](openclaw.mcp.json) into `~/.openclaw/openclaw.json` and set your
key.

---

## 5. Verify both connections

```bash
openclaw mcp doctor supercarl --probe    # expect: supercarl: ok  (+ tool list)
openclaw models status                   # expect: your Bedrock model, configured
openclaw gateway restart                 # load the new config
```

If `mcp doctor` reports `ok` and `models status` shows your model, both connections
are live. Now talk to the agent.

---

## 6. Ask it things (plain language)

```bash
openclaw agent --local -m "Find senior backend engineers in Seattle with AWS experience, and tell me why each one fits."
```

Or open an interactive session:

```bash
openclaw chat --local
```

The agent binds the SuperCarl session as OpenClaw, calls `people_search`, narrows the
pool, and answers grounded in what the tools returned. Follow up in the same session —
it reasons over the previous results rather than searching again:

```
you> Which of those actually has AWS in their current job, not just their history?
you> Draft a short outreach message for the strongest two. Do not send anything.
```

> **Seeing the tool calls.** `--verbose on` does *not* surface MCP invocations. To
> show that answers come from tools and not the model, either read the audit log for
> scheduled runs (`openclaw audit --kind tool_action --limit 40 --json` — the JSON
> carries the full `toolName`; the table form truncates it), or ask the agent to open
> each reply with a short list of the SuperCarl calls it made.
>
> **Readable output.** Pipe through `glow` for rendered tables:
> `openclaw agent --local -m "..." | glow -`. If you script it, pipe glow onward
> (`| glow - | cat`) — on a bare terminal glow opens an interactive pager and waits
> for a keypress, which hangs unattended runs.

---

## 7. Build an artifact, not just a list

The point of an agent is that it can act on the data. Ask it to turn a search into
something you can use:

```bash
openclaw agent --local -m "Find senior backend engineers in Seattle with AWS experience. Pick the 5 strongest, then build me a self-contained HTML dashboard with a card per candidate: their ICP fit quoting the SuperCarl evidence, and a DRAFT personalized outreach message with a copy button. Open it when done."
```

It runs the search, reasons about fit, writes a self-contained HTML file, and opens
it. Same pattern points at other endpoints — a company→people BD loop, a jobs search
that tailors your resume per role (see [the job-seeker flow](#other-shapes)).

---

## 8. Schedule it (runs without you)

Turn a standing brief into a twice-daily **watch**: search, compare against everyone
already reported, and only surface who is new.

```bash
openclaw cron add \
  --name supercarl-watch \
  --cron "0 9,17 * * *" \
  --model "bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0" \
  --expect-final \
  --timeout-seconds 600 \
  --message "Search SuperCarl for senior backend engineers in Seattle with AWS experience. Compare against demo/out/seen.json (candidates already reported) and update it as the cumulative union - never drop anyone who fell out of the ranking, or they get re-reported as new later. Rebuild the dashboard, badging this run's arrivals as NEW and sorting them first. Reply with a short digest naming only the new people, or one line saying there are none."
```

- The schedule `0 9,17 * * *` is **9am and 5pm daily**.
- Scheduled jobs run through the **gateway**, so it must be running
  (`openclaw gateway run`, or `openclaw gateway install && openclaw gateway start`
  to keep it up as a service). Ad-hoc `openclaw agent --local` runs do not need it.
- Keep the ledger **cumulative**. If you rewrite it with just the current top N,
  anyone who drops out of the ranking is re-reported as new on a later run.

Manage it:

```bash
openclaw cron list                       # shows schedule, last run, status, delivery
openclaw cron run <job-id>               # run it now (id from cron list, not the name)
```

---

## 9. Get it on WhatsApp

So the digest lands on your phone instead of a terminal.

**Install the WhatsApp channel from npm** — not from ClawHub:

```bash
openclaw plugins install @openclaw/whatsapp     # official package: works
openclaw gateway restart
```

> Why npm and not `clawhub:@openclaw/whatsapp`: the ClawHub spec installs the same
> code as an *untrusted third-party* plugin, which is denied the credential store
> (`openKeyedStore is only available for trusted plugins in this release`). The
> channel then pairs successfully and fails to start — a confusing place to land.
> From npm it is a trusted official install and runs. On 2026.7.1 only **Telegram**
> and **iMessage** ship bundled; everything else installs this way.

**Link your account** (scan the QR from WhatsApp → Linked devices):

```bash
openclaw channels login --channel whatsapp
openclaw channels status                        # expect: running, connected, healthy
```

**Deliver the watch to WhatsApp** — add delivery flags when you register the job:

```bash
openclaw cron add \
  --name supercarl-watch \
  --cron "0 9,17 * * *" \
  --announce --channel whatsapp --to "+15551234567" \
  --model "bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0" \
  --expect-final --timeout-seconds 600 \
  --message "<same watch prompt as above>"
```

Now, twice a day, the dashboard refreshes itself and only genuinely new matches reach
your phone.

> **Letting the agent message you on demand** (not just on a schedule) needs the
> `full` tool profile. `coding` (the default) strips the `message` tool; `messaging`
> strips `cron`. Only `full` gives both:
> ```bash
> openclaw config set tools.profile full && openclaw gateway restart
> ```
> This widens what the agent can do on your machine — review the security note below
> before you set it.

---

## 10. Safety model

Two boundaries, and they are different:

1. **What SuperCarl tools are exposed.** The `--include` allowlist restricts the agent
   to search/read tools. It can never send outreach or modify your account through
   SuperCarl — those tools are not in the allowlist. This mirrors the allowlist the
   AWS deployment of this project enforces (`SAFE_MCP_TOOLS`).
2. **Who the agent may message.** It can message *you* on your own channels. It must
   never contact a *candidate* — outreach is always drafted for a human to review and
   send, labelled `DRAFT — NOT SENT`. Under the `full` profile the agent gains real
   capability on your machine (messaging, scheduling, browser, web); grant it
   deliberately, and keep the SuperCarl allowlist read-only regardless.

The one-line version: it can report to you; it cannot write to the people it found.

---

## 11. Other shapes {#other-shapes}

Same two connections, pointed elsewhere:

- **BD loop** — `company_search` for target accounts, then `people_search` for
  contacts at each.
- **Job seeker** — `jobs_search` against your background: the agent tailors your
  resume per role, drafts a cover note, builds an applications dashboard, and opens
  the posting so you press apply. It never submits.
- **Heartbeat digest** — a Slack/WhatsApp summary on a schedule, delivered into the
  chat you already use.

---

## Troubleshooting, in one place

| Symptom | Cause | Fix |
|---|---|---|
| `Node.js >= 24.15 required (current: v24.4.1)` | Homebrew's default `node` is old/broken | Put `node@24` first on `PATH` (Part 0) |
| WhatsApp pairs then won't start; `openKeyedStore ... trusted plugins` | Installed from ClawHub (untrusted) | Reinstall from npm: `@openclaw/whatsapp` (Part 9) |
| Terminal hangs after markdown renders | `glow` opened its pager on a TTY | Pipe onward: `... | glow - | cat` |
| Agent says "nothing has changed" and doesn't search | Reusing a prior session's memory | Start a fresh `--session-id`, or clear old session files |
| `cron.run params: id not found` | `cron run` takes the job **id**, not the name | Get the id from `openclaw cron list` |
| Scheduled job fails to register | Gateway not running | `openclaw gateway run` (or install as a service) |
| Agent says it can't message or schedule | Tool profile is `coding`/`messaging` | `openclaw config set tools.profile full` |
| `people_search` returns far-away people | SuperCarl location filter defaults loose | Ask the agent to tighten to strict current-location |
| Empty / thin results | A network (e.g. LinkedIn) not connected in SuperCarl | Connect it under Integrations and re-run |

---

## The whole path, condensed

```bash
# once
brew install node@24 glow && export PATH="/opt/homebrew/opt/node@24/bin:$PATH"
npm install -g openclaw
export SUPERCARL_API_KEY="carl_..."
# model on Bedrock: add the provider block (Part 3), then:
openclaw models set "bedrock/us.anthropic.claude-sonnet-4-5-20250929-v1:0"
# tools over MCP:
openclaw mcp add supercarl --url https://api.supercarl.ai/mcp --transport streamable-http \
  --header "Authorization=Bearer $SUPERCARL_API_KEY" \
  --include 'agent_session,people_search,people_lookup_batch,company_search,company_search_batch,jobs_search,posts_search,query_search_result'
openclaw plugins install @openclaw/whatsapp
openclaw channels login --channel whatsapp
openclaw gateway restart

# every day
openclaw agent --local -m "Find senior backend engineers in Seattle with AWS experience."   # ask
openclaw cron add --name supercarl-watch --cron "0 9,17 * * *" --announce --channel whatsapp \
  --to "+15551234567" --expect-final --message "<watch prompt>"                              # schedule + WhatsApp
```

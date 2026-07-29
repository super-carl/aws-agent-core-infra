#!/usr/bin/env bash
# Bring the SuperCarl agent up inside OpenClaw from your environment - no editing
# files, no console. Everything the agent needs is already in this repo; this wires
# the two connections and hands you an agent you can talk to in plain language.
#
# Set the two connections in your environment, then run this:
#   export SUPERCARL_API_KEY=carl_...            # 1. the data  (SuperCarl MCP)
#   export OPENCLAW_MODEL=claude-opus-4-8        # 2. the model (or a Bedrock/Anthropic id)
#   ./scripts/openclaw-up.sh
#
# The model defaults to Claude Opus 4.8 via the local Claude CLI, so you can try it
# with just the SuperCarl key. Point OPENCLAW_MODEL at a Bedrock or Anthropic model
# once you have those credentials configured.
set -euo pipefail

# OpenClaw needs Node >= 24.15; keep node@24 ahead of an older Homebrew default.
if [ -x /opt/homebrew/opt/node@24/bin/node ]; then
  export PATH="/opt/homebrew/opt/node@24/bin:$PATH"
fi

# Accept a bare name (claude-opus-4-8) or a fully-qualified id (provider/model).
MODEL="${OPENCLAW_MODEL:-claude-opus-4-8}"
case "$MODEL" in */*) : ;; *) MODEL="claude-cli/$MODEL" ;; esac
TOOLS='agent_session,people_search,people_lookup_batch,company_search,company_search_batch,jobs_search,posts_search,query_search_result'

step() { printf '\n\033[36m==>\033[0m %s\n' "$1"; }
die()  { printf '\n\033[31mx\033[0m %s\n' "$1" >&2; exit 1; }

command -v openclaw >/dev/null 2>&1 || die "OpenClaw not found. Install it: npm install -g openclaw"
[ -n "${SUPERCARL_API_KEY:-}" ] || die "Set your SuperCarl key first:  export SUPERCARL_API_KEY=carl_..."

# 1. The data - SuperCarl over MCP, restricted to search/read tools.
step "Connecting SuperCarl (search/read tools only)"
openclaw mcp add supercarl \
  --url https://api.supercarl.ai/mcp \
  --transport streamable-http \
  --header "Authorization=Bearer $SUPERCARL_API_KEY" \
  --header "X-Client-Name=OpenClaw" \
  --header "User-Agent=OpenClaw" \
  --include "$TOOLS" >/dev/null
echo "    supercarl MCP registered"

# 2. The model that reasons over the results.
step "Setting the model ($MODEL)"
openclaw models set "$MODEL" >/dev/null 2>&1 || true
echo "    model: $MODEL"

# 3. Load the config and confirm the connection.
step "Verifying"
openclaw gateway restart >/dev/null 2>&1 || true
if openclaw mcp doctor supercarl --probe 2>/dev/null | grep -q "supercarl: ok"; then
  echo "    supercarl: ok"
else
  die "SuperCarl MCP did not come up - check your key."
fi

cat <<'DONE'

Ready. Talk to your agent in plain language:

  openclaw chat --local

Try:
  Find senior backend engineers in Austin with AWS experience, and why each fits.
  Build me a dashboard of the best five with a draft outreach message each.
  Every morning at 9, message me on WhatsApp when a new match shows up.

Search, dashboards, scheduling and messaging - all from the chat. Drafting and
sending stay separate: the agent composes, you send.
DONE

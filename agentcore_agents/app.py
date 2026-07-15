"""
SuperCarl — autonomous research worker on Bedrock AgentCore.

A Strands agent that turns a single natural-language brief into a synthesized
shortlist of people/company profiles. It reasons over a multi-step loop, routing
to SuperCarl API tools (People Search, Profile Lookup, Company Search) and
delivering the result (SES / Slack). Memory (STM+LTM) and Guardrails are wired
by the CDK stack via environment variables.

Two use cases:
  - recruiting: one prompt yields a shortlist of 10+ candidate profiles
  - bd:        multi-step loop chaining Company Search then People Search
"""

import json
import os
import time
import logging
import contextvars
from typing import Dict, Any
from datetime import datetime, timezone
from uuid import uuid4

from bedrock_agentcore import BedrockAgentCoreApp

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Agent build marker (bump to force a fresh Runtime container that reads the
# current GUARDRAIL_VERSION at startup).
AGENT_BUILD = "2026-07-15.2"

# ─── Environment (set by CDK) ───────────────────────────────────────────────
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
MEMORY_ID = os.environ.get("MEMORY_ID", "")
GUARDRAIL_ID = os.environ.get("GUARDRAIL_ID", "")
GUARDRAIL_VERSION = os.environ.get("GUARDRAIL_VERSION", "")
MODEL_ID = os.environ.get("MODEL_ID", "us.anthropic.claude-sonnet-4-6")
TASK_TABLE = os.environ.get("TASK_TABLE", "")

PEOPLE_SEARCH_FN = os.environ.get("PEOPLE_SEARCH_FN", "")
PROFILE_LOOKUP_FN = os.environ.get("PROFILE_LOOKUP_FN", "")
COMPANY_SEARCH_FN = os.environ.get("COMPANY_SEARCH_FN", "")
DELIVER_RESULTS_FN = os.environ.get("DELIVER_RESULTS_FN", "")
API_KEY_SECRET_ARN = os.environ.get("API_KEY_SECRET_ARN", "")

# Real SuperCarl tools the agent is ALLOWED to use: search / read only. The MCP
# server also exposes write-capable tools (send_communication, project_action,
# contacts_*, watch_signals, super_carl_action, social_proximity_research). Those
# are deliberately excluded so the agent cannot send outreach or mutate the
# account — delivery happens only through our controlled deliver_results channel.
SAFE_MCP_TOOLS = {
    "people_search",
    "people_lookup_batch",
    "company_search",
    "company_search_batch",
    "jobs_search",
    "posts_search",
    "query_search_result",
}

# Per-invocation task context for step tracing (STEP#n in DynamoDB).
_task_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar("task_ctx", default=None)
_ddb_table = None


def _table():
    global _ddb_table
    if _ddb_table is None and TASK_TABLE:
        import boto3
        _ddb_table = boto3.resource("dynamodb", region_name=AWS_REGION).Table(TASK_TABLE)
    return _ddb_table


def _record_step(tool: str, inp: str, status: str, latency_ms: int, output_summary: str = ""):
    """Write a STEP#n trace item for QA + latency tuning. Never breaks the agent."""
    ctx = _task_ctx.get()
    if not ctx or not _table():
        return
    ctx["n"] += 1
    try:
        _table().put_item(Item={
            "PK": f"TASK#{ctx['task_id']}",
            "SK": f"STEP#{ctx['n']:03d}",
            "tool": tool,
            "input": (inp or "")[:500],
            "status": status,
            "latencyMs": latency_ms,
            "outputSummary": (output_summary or "")[:500],
            "ts": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:  # noqa: BLE001
        logger.warning(f"step trace write failed: {e}")

SYSTEM_PROMPT = """You are SuperCarl, an autonomous research worker.

Your job: turn a natural-language brief into a synthesized shortlist of
people/company profiles, grounded ENTIRELY in SuperCarl API data.

Tools:
- people_search(query): find candidate/contact profiles.
- profile_lookup(profile_id): resolve/enrich a profile by id.
- company_search(query): find organizations for BD targeting.
- deliver_results(task_id, shortlist, channels): route the shortlist to SES/Slack.

Tool routing by use case (follow exactly):
- recruiting:
  1. Call people_search with a focused query derived from the brief.
  2. For the strongest 5-10 candidates, call profile_lookup to enrich them.
  3. Synthesize a shortlist of 10+ relevant candidates with a clear match_reason.
- bd (business development):
  1. Call company_search to find target organizations matching the brief.
  2. For the top organizations, call people_search to find contacts inside them
     (include the company in the query).
  3. Synthesize a shortlist of contacts, each tied to its target company.

After synthesis, ALWAYS call deliver_results(task_id, shortlist, channels) with
the final shortlist, then return that same shortlist JSON.

Hard rules:
- Ground every field in a tool (API) result. NEVER invent names, titles,
  companies, emails, or contact details. If a field is not in an API result,
  omit it. This is a hard requirement (hallucination mitigation).
- Every profile in the shortlist must carry source="supercarl_api".
- Stay within sourcing: report only facts the tools return about candidates and
  companies; add no opinions, recommendations, or commentary beyond the results.
- Keep reasoning focused: search, enrich, synthesize. Do not loop more than a
  few times; stop when you have a defensible shortlist.

Output a final shortlist as JSON with fields: task_id, use_case, query,
results (array of {profile_id, name, title, company, location, match_reason,
source}), count, delivered_to.
"""

MCP_SYSTEM_PROMPT = """You are SuperCarl, an autonomous research worker connected
to the live SuperCarl MCP tools.

Your job: turn a natural-language brief into a synthesized shortlist of
people/company profiles, grounded ENTIRELY in SuperCarl tool results.

Live tools (search/read only):
- people_search(query, ...): primary tool for person discovery.
- people_lookup_batch(profiles): load specific LinkedIn profiles.
- company_search(query, ...): find companies (not people).
- company_search_batch(companies): resolve named companies before people_search.
- jobs_search(query, ...): job postings.
- posts_search(query, ...): LinkedIn posts.
- query_search_result(...): reshape a prior result into specific columns.
- deliver_results(task_id, shortlist, channels): OUR delivery channel (SES/Slack).

Tool routing by use case:
- recruiting: call people_search with a focused query; refine with filters if
  needed; pick the 10+ strongest matches.
- bd: call company_search (or company_search_batch) to find target companies,
  then people_search scoped to those companies to find contacts.

After you have the matches, build the shortlist as a JSON OBJECT of this exact
shape (results MUST be a top-level array named "results"):
{"task_id": "...", "use_case": "recruiting|bd", "query": "...",
 "results": [{"profile_id","name","title","company","location","match_reason",
 "source":"supercarl_api"}], "count": N}
Map the SuperCarl fields onto these; omit any field the tools did not return.
Pass that object as the `shortlist` argument.
Then call deliver_results(task_id, shortlist, channels) EXACTLY ONCE and STOP:
output the final shortlist JSON as your final message and do not call any more
tools. An empty "delivered_to" is still success — the shortlist is always saved;
never re-search or re-deliver after deliver_results returns.

Hard rules:
- Ground every field in a tool result. NEVER invent names, titles, companies,
  emails, or contact details. Omit anything not returned by a tool.
- Do NOT attempt to send messages or modify the account; you only have
  search/read tools plus our deliver_results.
- Stay within sourcing: report only facts the tools return about candidates and
  companies; add no opinions or commentary beyond the results. Be efficient: a
  few searches, then deliver once and finish.
"""

# ─── Lazy-initialized globals ────────────────────────────────────────────────
_agent = None
_initialized = False
_model = None
_deliver_tool = None
_mcp_config = None  # {"api_key":..., "mcp_url":...} or {} once loaded


def _load_mcp_config() -> dict:
    """Read {api_key, mcp_url} from Secrets Manager once per container."""
    global _mcp_config
    if _mcp_config is not None:
        return _mcp_config
    _mcp_config = {}
    if not API_KEY_SECRET_ARN:
        return _mcp_config
    try:
        import boto3
        sm = boto3.client("secretsmanager", region_name=AWS_REGION)
        secret = sm.get_secret_value(SecretId=API_KEY_SECRET_ARN)["SecretString"]
        data = json.loads(secret)
        url = (data.get("mcp_url") or "").strip()
        key = (data.get("api_key") or "").strip()
        if url and key and key != "your-supercarl-api-key-here":
            _mcp_config = {"api_key": key, "mcp_url": url}
            logger.info(f"SuperCarl MCP configured: {url}")
        else:
            logger.info("SuperCarl MCP not configured (placeholder/missing) — using mock tools")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"could not load MCP config: {e}")
    return _mcp_config


def _build_mcp_client(cfg: dict):
    """Build a Strands MCP client for the SuperCarl Streamable-HTTP endpoint."""
    from strands.tools.mcp import MCPClient
    from mcp.client.streamable_http import streamablehttp_client

    url, key = cfg["mcp_url"], cfg["api_key"]
    return MCPClient(lambda: streamablehttp_client(
        url, headers={"Authorization": f"Bearer {key}", "x-api-key": key}
    ))


def _invoke_executor(function_name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Invoke an Action Group executor Lambda and return its parsed JSON body."""
    import boto3

    client = boto3.client("lambda", region_name=AWS_REGION)
    resp = client.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    raw = resp["Payload"].read().decode("utf-8")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "Executor returned non-JSON", "raw": raw[:500]}
    # Executors return {"statusCode", "body": "<json string>"} (API-GW shape).
    if isinstance(data, dict) and "body" in data and isinstance(data["body"], str):
        try:
            return json.loads(data["body"])
        except json.JSONDecodeError:
            return {"raw": data["body"]}
    return data


def _ensure_initialized():
    """Lazy init: build the Agent with tools on first call (stays within the
    AgentCore 30-second init timeout)."""
    global _agent, _initialized
    if _initialized:
        return
    _initialized = True

    from strands import Agent
    from strands.models.bedrock import BedrockModel
    from strands.tools import tool

    def _traced(tool_name: str, fn_name: str, payload: dict, inp: str) -> dict:
        """Invoke an executor, timing it and recording a STEP#n trace."""
        t0 = time.monotonic()
        status, out = "ok", {}
        try:
            out = _invoke_executor(fn_name, payload)
            if isinstance(out, dict) and out.get("error"):
                status = "error"
            return out
        except Exception as e:  # noqa: BLE001
            status, out = "error", {"error": str(e)}
            return out
        finally:
            latency_ms = int((time.monotonic() - t0) * 1000)
            summary = ""
            if isinstance(out, dict):
                summary = f"count={out.get('count')}" if "count" in out else json.dumps(out)[:200]
            _record_step(tool_name, inp, status, latency_ms, summary)

    @tool
    def people_search(query: str) -> str:
        """Find candidate/contact profiles matching a natural-language query.
        Returns a JSON list of profiles from the SuperCarl API."""
        logger.info(f"TOOL: people_search(query={query!r})")
        return json.dumps(_traced("people_search", PEOPLE_SEARCH_FN, {"query": query}, query))

    @tool
    def profile_lookup(profile_id: str) -> str:
        """Resolve and enrich a single profile by its SuperCarl profile id."""
        logger.info(f"TOOL: profile_lookup(profile_id={profile_id!r})")
        return json.dumps(_traced("profile_lookup", PROFILE_LOOKUP_FN, {"profile_id": profile_id}, profile_id))

    @tool
    def company_search(query: str) -> str:
        """Find organizations for BD targeting matching a query.
        Returns a JSON list of companies from the SuperCarl API."""
        logger.info(f"TOOL: company_search(query={query!r})")
        return json.dumps(_traced("company_search", COMPANY_SEARCH_FN, {"query": query}, query))

    @tool
    def deliver_results(task_id: str, shortlist: str, channels: str = "ses") -> str:
        """Deliver the final shortlist. `shortlist` is the JSON shortlist string;
        `channels` is a comma-separated list of: ses, slack."""
        logger.info(f"TOOL: deliver_results(task_id={task_id!r}, channels={channels!r})")
        try:
            parsed = json.loads(shortlist) if isinstance(shortlist, str) else shortlist
        except json.JSONDecodeError:
            parsed = {"raw": shortlist}
        return json.dumps(
            _traced(
                "deliver_results", DELIVER_RESULTS_FN,
                {"task_id": task_id, "shortlist": parsed, "channels": channels.split(",")},
                f"task={task_id} channels={channels}",
            )
        )

    global _model, _deliver_tool
    tools = [people_search, profile_lookup, company_search, deliver_results]

    model_kwargs = {"model_id": MODEL_ID}
    if GUARDRAIL_ID and GUARDRAIL_VERSION:
        model_kwargs["guardrail_id"] = GUARDRAIL_ID
        model_kwargs["guardrail_version"] = GUARDRAIL_VERSION
        logger.info(f"Guardrails enabled: {GUARDRAIL_ID} v{GUARDRAIL_VERSION}")

    _model = BedrockModel(**model_kwargs)
    _deliver_tool = deliver_results
    # Mock-tool agent: fallback when the SuperCarl MCP server is not configured.
    _agent = Agent(model=_model, system_prompt=SYSTEM_PROMPT, tools=tools)
    logger.info(f"SuperCarl agent initialized (mock fallback), model={MODEL_ID}")


def _make_mcp_agent(mcp_client):
    """Build a per-invocation agent bound to the live SuperCarl MCP tools
    (search/read only) plus our deliver_results channel."""
    from strands import Agent

    all_tools = mcp_client.list_tools_sync()
    safe = [t for t in all_tools if getattr(t, "tool_name", None) in SAFE_MCP_TOOLS]
    logger.info(f"MCP tools available={len(all_tools)} allowed={[getattr(t,'tool_name',None) for t in safe]}")
    return Agent(model=_model, system_prompt=MCP_SYSTEM_PROMPT, tools=safe + [_deliver_tool])


def _invoke_with_memory(agent, brief, session_id, actor_id):
    """Run the agent, wiring AgentCore Memory (STM+LTM) when available."""
    if MEMORY_ID:
        try:
            from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
            from bedrock_agentcore.memory.integrations.strands.session_manager import (
                AgentCoreMemorySessionManager,
            )

            config = AgentCoreMemoryConfig(memory_id=MEMORY_ID, session_id=session_id, actor_id=actor_id)
            with AgentCoreMemorySessionManager(config, region_name=AWS_REGION) as sm:
                agent.session_manager = sm
                res = agent(brief)
                agent.session_manager = None
                return res
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Memory session failed, invoking without memory: {e}")
    return agent(brief)


# ─── Entrypoint ──────────────────────────────────────────────────────────────
app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Main agent entrypoint. Expects:
    { "prompt": "...", "useCase": "recruiting"|"bd", "taskId": "...",
      "channels": "ses,slack", "sessionId": "...", "actorId": "..." }
    """
    session_id = None
    try:
        _ensure_initialized()

        if not isinstance(payload, dict):
            raise ValueError("Invalid payload: must be a dictionary")

        user_message = (payload.get("prompt") or "").strip()
        if not user_message:
            raise ValueError("Invalid prompt: must be a non-empty string")
        user_message = user_message[:4000]

        use_case = payload.get("useCase", "recruiting")
        task_id = payload.get("taskId") or f"task-{uuid4().hex[:12]}"
        channels = payload.get("channels", "ses")
        session_id = payload.get("sessionId") or f"session-{uuid4().hex[:12]}"
        actor_id = payload.get("actorId", "default")

        # Attribute tool step traces (STEP#n) to this task.
        _task_ctx.set({"task_id": task_id, "n": 0})

        brief = (
            f"task_id: {task_id}\n"
            f"use_case: {use_case}\n"
            f"delivery_channels: {channels}\n"
            f"brief: {user_message}\n\n"
            "Run the research loop and, when the shortlist is ready, call "
            "deliver_results, then return the final shortlist JSON."
        )

        cfg = _load_mcp_config()
        tool_mode = "mcp" if cfg else "mock"
        logger.info(f"Invoked — task={task_id}, use_case={use_case}, tools={tool_mode}, session={session_id}")

        if cfg:
            try:
                mcp_client = _build_mcp_client(cfg)
                with mcp_client:
                    agent = _make_mcp_agent(mcp_client)
                    result = _invoke_with_memory(agent, brief, session_id, actor_id)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"MCP path failed, falling back to mock tools: {e}")
                result = _invoke_with_memory(_agent, brief, session_id, actor_id)
        else:
            result = _invoke_with_memory(_agent, brief, session_id, actor_id)

        response_text = result.message if hasattr(result, "message") and result.message else str(result)

        return {
            "result": response_text,
            "task_id": task_id,
            "session_id": session_id,
            "use_case": use_case,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "success",
        }

    except ValueError as ve:
        logger.error(f"Validation error: {ve}")
        return {"error": str(ve), "session_id": session_id or "unknown", "status": "error"}
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return {"error": "An unexpected error occurred.", "session_id": session_id or "unknown", "status": "error"}


if __name__ == "__main__":
    app.run()

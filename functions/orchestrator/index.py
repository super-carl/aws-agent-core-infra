"""
SuperCarl Orchestrator Lambda — the hub.

Triggered two ways:
  1. On-demand via API Gateway (Cognito-authed REST):
       POST /v1/research            -> submit a research task
       GET  /v1/research            -> list recent tasks
       GET  /v1/research/{taskId}   -> task status + synthesized shortlist
       POST /v1/research/schedule   -> create a scheduled (EventBridge) task
  2. Scheduled via EventBridge Scheduler (payload {"scheduled": true, ...}).

Responsibilities: create the task record in DynamoDB, invoke the AgentCore
Runtime, persist the final shortlist + delivery status, return the task id.
"""
import json
import os
import logging
from datetime import datetime, timezone, timedelta
from uuid import uuid4

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("REGION", "us-east-1")
TASK_TABLE = os.environ.get("TASK_TABLE", "")
RUNTIME_ARN = os.environ.get("AGENTCORE_RUNTIME_ARN", "")
SCHEDULER_ROLE_ARN = os.environ.get("SCHEDULER_ROLE_ARN", "")
ORCHESTRATOR_ARN = os.environ.get("ORCHESTRATOR_ARN", "")

_ddb = boto3.resource("dynamodb", region_name=REGION)
_table = _ddb.Table(TASK_TABLE) if TASK_TABLE else None


VALID_USE_CASES = {"recruiting", "bd"}
VALID_CHANNELS = {"ses", "slack"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log(event: str, **fields):
    """Structured JSON log line (CloudWatch Logs Insights friendly)."""
    logger.info(json.dumps({"event": event, **fields}, default=str))


def _validate(prompt: str, use_case: str, channels) -> str | None:
    """Return an error message if the request is invalid, else None."""
    if not prompt:
        return "prompt is required"
    if len(prompt) > 4000:
        return "prompt too long (max 4000 chars)"
    if use_case not in VALID_USE_CASES:
        return f"useCase must be one of {sorted(VALID_USE_CASES)}"
    if not isinstance(channels, list) or not channels:
        return "channels must be a non-empty list"
    bad = [c for c in channels if c not in VALID_CHANNELS]
    if bad:
        return f"unsupported channels {bad}; valid: {sorted(VALID_CHANNELS)}"
    return None


def _resp(code: int, body: dict) -> dict:
    return {
        "statusCode": code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
        },
        "body": json.dumps(body, default=str),
    }


# ─── DynamoDB task state ─────────────────────────────────────────────────────
def _create_task(task_id: str, use_case: str, prompt: str, channels, model: str, status: str):
    _table.put_item(Item={
        "PK": f"TASK#{task_id}",
        "SK": "META",
        "itemType": "TASK",
        "taskId": task_id,
        "useCase": use_case,
        "prompt": prompt,
        "deliveryChannels": channels,
        "model": model,
        "status": status,
        "createdAt": _now(),
        # 30-day TTL on task records.
        "ttl": int((datetime.now(timezone.utc) + timedelta(days=30)).timestamp()),
    })


def _update_status(task_id: str, status: str, extra: dict | None = None):
    # Alias every attribute name to dodge DynamoDB reserved keywords (status, error, ...).
    names = {"#s": "status", "#u": "updatedAt"}
    vals = {":s": status, ":u": _now()}
    sets = ["#s = :s", "#u = :u"]
    for i, (k, v) in enumerate((extra or {}).items()):
        nk, vk = f"#k{i}", f":v{i}"
        names[nk] = k
        vals[vk] = v
        sets.append(f"{nk} = {vk}")
    _table.update_item(
        Key={"PK": f"TASK#{task_id}", "SK": "META"},
        UpdateExpression="SET " + ", ".join(sets),
        ExpressionAttributeValues=vals,
        ExpressionAttributeNames=names,
    )


def _put_result(task_id: str, shortlist: dict, channels):
    _table.put_item(Item={
        "PK": f"TASK#{task_id}",
        "SK": "RESULT",
        "shortlist": shortlist,
        "count": shortlist.get("count") if isinstance(shortlist, dict) else None,
        "channels": channels,
        "deliveredAt": _now(),
    })


def _get_task(task_id: str) -> dict | None:
    resp = _table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key("PK").eq(f"TASK#{task_id}")
    )
    items = resp.get("Items", [])
    if not items:
        return None
    out = {"taskId": task_id, "steps": []}
    for it in items:
        sk = it.get("SK", "")
        if sk == "META":
            out.update({k: v for k, v in it.items() if k not in ("PK", "SK")})
        elif sk == "RESULT":
            out["result"] = {k: v for k, v in it.items() if k not in ("PK", "SK")}
        elif sk.startswith("STEP#"):
            out["steps"].append(it)
    return out


def _list_tasks(limit: int = 25) -> list:
    resp = _table.query(
        IndexName="byCreatedAt",
        KeyConditionExpression=boto3.dynamodb.conditions.Key("itemType").eq("TASK"),
        ScanIndexForward=False,
        Limit=limit,
    )
    return resp.get("Items", [])


# ─── Runtime invocation ──────────────────────────────────────────────────────
def _run_agent(task_id: str, use_case: str, prompt: str, channels) -> dict:
    if not RUNTIME_ARN:
        raise RuntimeError("AGENTCORE_RUNTIME_ARN not set")
    client = boto3.client("bedrock-agentcore", region_name=REGION)
    # AgentCore requires runtimeSessionId to be >= 33 chars.
    session_id = f"{task_id}-{uuid4().hex}"
    payload = json.dumps({
        "prompt": prompt,
        "useCase": use_case,
        "taskId": task_id,
        "channels": ",".join(channels) if isinstance(channels, list) else channels,
        "sessionId": session_id,
    }).encode("utf-8")
    resp = client.invoke_agent_runtime(
        agentRuntimeArn=RUNTIME_ARN,
        runtimeSessionId=session_id,
        payload=payload,
        qualifier="DEFAULT",
    )
    raw = ""
    for chunk in resp.get("response", []) or []:
        raw += chunk.decode("utf-8") if isinstance(chunk, bytes) else str(chunk)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"result": raw, "status": "success"}


def _run_task(task_id: str, use_case: str, prompt: str, channels):
    """Run the agent for an already-created task and persist the result."""
    try:
        agent_out = _run_agent(task_id, use_case, prompt, channels)
        shortlist = agent_out.get("result", agent_out)
        if isinstance(shortlist, str):
            try:
                shortlist = json.loads(shortlist)
            except json.JSONDecodeError:
                shortlist = {"summary": shortlist}
        _put_result(task_id, shortlist if isinstance(shortlist, dict) else {"summary": str(shortlist)}, channels)
        _update_status(task_id, "completed")
        return agent_out
    except Exception as e:  # noqa: BLE001
        logger.error(f"task {task_id} failed: {e}", exc_info=True)
        _update_status(task_id, "failed", {"error": str(e)})
        raise


def _execute(task_id: str, use_case: str, prompt: str, channels, model: str):
    """Create + run a task end-to-end (used by the scheduled path)."""
    _create_task(task_id, use_case, prompt, channels, model, status="in_progress")
    return _run_task(task_id, use_case, prompt, channels)


def _async_invoke(payload: dict):
    """Fire-and-forget self-invocation so the API returns before the agent loop
    runs (API Gateway has a hard 29s integration timeout)."""
    boto3.client("lambda", region_name=REGION).invoke(
        FunctionName=ORCHESTRATOR_ARN,
        InvocationType="Event",
        Payload=json.dumps(payload).encode("utf-8"),
    )


# ─── Scheduling ──────────────────────────────────────────────────────────────
def _create_schedule(task_id: str, schedule_expression: str, body: dict) -> str:
    scheduler = boto3.client("scheduler", region_name=REGION)
    name = f"supercarl-{task_id}"
    scheduler.create_schedule(
        Name=name,
        GroupName="supercarl",
        ScheduleExpression=schedule_expression,
        FlexibleTimeWindow={"Mode": "OFF"},
        Target={
            "Arn": ORCHESTRATOR_ARN,
            "RoleArn": SCHEDULER_ROLE_ARN,
            "Input": json.dumps({"scheduled": True, **body}),
        },
    )
    return name


# ─── Handler ─────────────────────────────────────────────────────────────────
def lambda_handler(event, context):
    # Async worker invocation (self-invoked by POST /research to run the agent
    # loop outside the API Gateway 29s window).
    if isinstance(event, dict) and event.get("async_task"):
        tid = event["taskId"]
        _log("worker_start", taskId=tid)
        _run_task(tid, event.get("useCase", "recruiting"), event.get("prompt", ""), event.get("channels", ["ses"]))
        _log("worker_done", taskId=tid)
        return {"taskId": tid, "status": "done"}

    # Scheduled invocation (direct from EventBridge Scheduler).
    if isinstance(event, dict) and event.get("scheduled"):
        task_id = f"task-{uuid4().hex[:12]}"
        use_case = event.get("useCase", "recruiting")
        prompt = event.get("prompt", "")
        channels = event.get("channels", ["ses"])
        model = event.get("model", os.environ.get("MODEL_ID", "sonnet-4-6"))
        logger.info(f"scheduled run -> task {task_id}")
        _execute(task_id, use_case, prompt, channels, model)
        return {"taskId": task_id, "status": "completed"}

    # API Gateway invocation.
    method = event.get("httpMethod", "")
    resource = event.get("resource", "")
    path_params = event.get("pathParameters") or {}

    try:
        if method == "GET" and resource == "/research/{taskId}":
            task = _get_task(path_params.get("taskId", ""))
            return _resp(200, task) if task else _resp(404, {"error": "task not found"})

        if method == "GET" and resource == "/research":
            return _resp(200, {"tasks": _list_tasks()})

        body = json.loads(event.get("body") or "{}")
        prompt = (body.get("prompt") or "").strip()
        use_case = body.get("useCase", "recruiting")
        channels = body.get("channels", ["ses"])
        model = body.get("model", os.environ.get("MODEL_ID", "sonnet-4-6"))

        if method == "POST" and resource == "/research/schedule":
            err = _validate(prompt, use_case, channels)
            if err:
                return _resp(400, {"error": err})
            sched = body.get("scheduleExpression")
            if not sched:
                return _resp(400, {"error": "scheduleExpression is required (e.g. 'rate(1 day)')"})
            task_id = f"task-{uuid4().hex[:12]}"
            name = _create_schedule(task_id, sched, {
                "useCase": use_case, "prompt": prompt, "channels": channels, "model": model,
            })
            _log("schedule_created", taskId=task_id, scheduleName=name, scheduleExpression=sched, useCase=use_case)
            return _resp(201, {"scheduleName": name, "scheduleExpression": sched, "status": "scheduled"})

        if method == "POST" and resource == "/research":
            err = _validate(prompt, use_case, channels)
            if err:
                return _resp(400, {"error": err})
            task_id = f"task-{uuid4().hex[:12]}"
            # Create the task, then run the agent loop asynchronously so the API
            # returns immediately (API Gateway times out at 29s). Poll GET
            # /v1/research/{taskId} for status + the synthesized shortlist.
            _create_task(task_id, use_case, prompt, channels, model, status="processing")
            _async_invoke({"async_task": True, "taskId": task_id, "useCase": use_case,
                           "prompt": prompt, "channels": channels})
            _log("task_submitted", taskId=task_id, useCase=use_case, channels=channels)
            return _resp(202, {"taskId": task_id, "status": "processing",
                               "poll": f"/v1/research/{task_id}"})

        return _resp(404, {"error": f"unsupported route: {method} {resource}"})

    except Exception as e:  # noqa: BLE001
        _log("orchestrator_error", error=str(e))
        logger.error(f"orchestrator error: {e}", exc_info=True)
        return _resp(500, {"error": str(e)})

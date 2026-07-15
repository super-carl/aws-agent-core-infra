"""
Orchestrator routing + validation tests (Week 3).

Imports the handler with no live table and stubs the AWS-touching helpers, so we
exercise routing, validation, and the status lifecycle offline. Run:

    python3 tests/test_orchestrator.py
"""
import json
import os
import sys
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["TASK_TABLE"] = ""  # _table stays None; we stub data helpers
os.environ["REGION"] = "us-east-1"

spec = importlib.util.spec_from_file_location("orch", os.path.join(ROOT, "functions", "orchestrator", "index.py"))
orch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orch)

# ─── Stub AWS-touching helpers ──────────────────────────────────────────────
orch._execute = lambda task_id, use_case, prompt, channels, model: {"status": "success", "result": {"count": 1}}
orch._run_task = lambda task_id, use_case, prompt, channels: {"status": "success"}
orch._create_task = lambda *a, **k: None
orch._async_invoke = lambda payload: None
orch._create_schedule = lambda task_id, sched, body: f"supercarl-{task_id}"
orch._get_task = lambda tid: {"taskId": tid, "status": "completed"} if tid == "task-1" else None
orch._list_tasks = lambda limit=25: [{"taskId": "task-1", "status": "completed"}]

passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1; print(f"  PASS  {name}")
    else:
        failed += 1; print(f"  FAIL  {name}")


def api(method, resource, body=None, path=None):
    return orch.lambda_handler({
        "httpMethod": method, "resource": resource,
        "pathParameters": path or {}, "body": json.dumps(body) if body is not None else None,
    }, None)


def code(r):
    return r["statusCode"]


print("validation")
check("missing prompt -> 400", code(api("POST", "/research", {})) == 400)
check("invalid useCase -> 400", code(api("POST", "/research", {"prompt": "x", "useCase": "sales"})) == 400)
check("invalid channel -> 400", code(api("POST", "/research", {"prompt": "x", "channels": ["fax"]})) == 400)
check("empty channels -> 400", code(api("POST", "/research", {"prompt": "x", "channels": []})) == 400)
check("overlong prompt -> 400", code(api("POST", "/research", {"prompt": "x" * 4001})) == 400)

print("routing")
r = api("POST", "/research", {"prompt": "engineers in Austin", "useCase": "recruiting", "channels": ["ses"]})
check("valid submit -> 202 processing", code(r) == 202 and json.loads(r["body"])["status"] == "processing")
r = api("POST", "/research/schedule", {"prompt": "x", "useCase": "bd", "channels": ["slack"], "scheduleExpression": "rate(1 day)"})
check("valid schedule -> 201", code(r) == 201 and "scheduleName" in json.loads(r["body"]))
check("schedule w/o expression -> 400", code(api("POST", "/research/schedule", {"prompt": "x"})) == 400)
check("get task found -> 200", code(api("GET", "/research/{taskId}", path={"taskId": "task-1"})) == 200)
check("get task missing -> 404", code(api("GET", "/research/{taskId}", path={"taskId": "nope"})) == 404)
check("list tasks -> 200", code(api("GET", "/research")) == 200)
check("unknown route -> 404", code(api("DELETE", "/research")) == 404)

print("scheduled invocation")
out = orch.lambda_handler({"scheduled": True, "prompt": "x", "useCase": "recruiting", "channels": ["ses"]}, None)
check("scheduled run completes", out.get("status") == "completed" and out.get("taskId", "").startswith("task-"))

print("async worker invocation")
out = orch.lambda_handler({"async_task": True, "taskId": "task-1", "useCase": "recruiting", "prompt": "x", "channels": ["ses"]}, None)
check("worker runs task", out.get("status") == "done" and out.get("taskId") == "task-1")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

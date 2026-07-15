"""
Executor unit tests (Week 2 — "First Action Groups return data").

Runs each executor against the deterministic mock contract (no AWS, no network)
and asserts the structured-shaping + validation contract. Run:

    python3 tests/test_executors.py
"""
import json
import os
import sys
import importlib.util

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("SUPERCARL_API_BASE_URL", "https://mock.supercarl.local")
os.environ.setdefault("API_KEY_SECRET_ARN", "")


def _load(name: str):
    """Load an executor module in isolation (each has its own supercarl_client copy)."""
    d = os.path.join(ROOT, "functions", name)
    sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location(f"exec_{name}", os.path.join(d, "index.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.path.remove(d)
    # drop the per-dir supercarl_client so the next import picks up its sibling copy
    sys.modules.pop("supercarl_client", None)
    return mod


passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}")


print("people_search")
people = _load("people_search")
r = people.lambda_handler({"query": "backend engineers in Austin"}, None)
b = json.loads(r["body"])
check("returns 200", r["statusCode"] == 200)
check("returns 10+ profiles", b["count"] >= 10)
check("every row source=supercarl_api", all(p["source"] == "supercarl_api" for p in b["results"]))
check("shaped keys only", set(b["results"][0]) == {"profile_id", "name", "title", "company", "location", "match_reason", "source"})
check("empty query rejected", people.lambda_handler({"query": ""}, None)["statusCode"] == 400)
check("overlong query rejected", people.lambda_handler({"query": "x" * 1001}, None)["statusCode"] == 400)

print("company_search")
company = _load("company_search")
r = company.lambda_handler({"query": "fintech in NYC"}, None)
b = json.loads(r["body"])
check("returns 200", r["statusCode"] == 200)
check("returns companies", b["count"] >= 1)
check("shaped keys", set(b["results"][0]) == {"company_id", "name", "industry", "size", "location", "match_reason", "source"})
check("limit clamped (no crash on 999)", company.lambda_handler({"query": "x", "limit": 999}, None)["statusCode"] == 200)

print("profile_lookup")
profile = _load("profile_lookup")
r = profile.lambda_handler({"profile_id": "p_0429173"}, None)
b = json.loads(r["body"])
check("returns 200", r["statusCode"] == 200)
check("source=supercarl_api", b["source"] == "supercarl_api")
check("has skills list", isinstance(b["skills"], list))
check("missing id rejected", profile.lambda_handler({}, None)["statusCode"] == 400)
check("invalid id rejected", profile.lambda_handler({"profile_id": "a/b c"}, None)["statusCode"] == 400)

print("deliver_results")
deliver = _load("deliver_results")
sl = {"use_case": "recruiting", "query": "x", "count": 1,
      "results": [{"name": "A", "title": "SWE", "company": "Acme", "location": "Austin", "match_reason": "x"}]}
r = deliver.lambda_handler({"task_id": "task-test", "shortlist": sl, "channels": ["ses"]}, None)
b = json.loads(r["body"])
check("returns 200", r["statusCode"] == 200)
check("reports delivered_to", "delivered_to" in b)
check("missing task_id rejected", deliver.lambda_handler({"shortlist": sl}, None)["statusCode"] == 400)

print("grounding (deliver_results._ground)")
g = deliver._ground({
    "use_case": "marketing",  # invalid -> normalized
    "results": [
        {"name": "Real", "title": "SWE", "company": "Acme", "evil_field": "DROP ME"},
        {"title": "no identity"},          # dropped (no name/profile_id)
        {"profile_id": "p_1", "source": "made_up"},  # source forced
        "not-a-dict",                       # ignored
    ],
})
check("invalid use_case normalized", g["use_case"] == "recruiting")
check("identity-less row dropped", g["count"] == 2)
check("unknown fields stripped", all("evil_field" not in r for r in g["results"]))
check("source forced to supercarl_api", all(r["source"] == "supercarl_api" for r in g["results"]))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)

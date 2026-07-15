"""
SuperCarl — local dev server (no AWS).

Exposes the same API surface as the deployed stack
(POST /v1/research, GET /v1/research/{taskId}, GET /v1/research, GET /v1/health)
so you can develop and demo the research loop entirely on your machine.

Local mode runs the same recruiting / BD tool routing the agent uses, but with
deterministic routing (no Bedrock) against the mock SuperCarl data, so it needs
no cloud, no credentials, and no GPU. The LLM reasoning path is the AWS-deployed
Runtime; local mode is for offline dev, tests, and demos.

    python3 local/local_server.py            # http://127.0.0.1:8080
    curl -s localhost:8080/v1/health
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime, timezone
from uuid import uuid4

# Reuse the deterministic SuperCarl generators (stdlib-only import).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions", "people_search"))
from supercarl_client import mock_people, mock_companies, mock_profile  # noqa: E402

PORT = int(os.environ.get("PORT", "8080"))
HOST = os.environ.get("HOST", "127.0.0.1")  # set 0.0.0.0 in Docker
ARTIFACT_DIR = os.path.join(os.path.dirname(__file__), "artifacts")
os.makedirs(ARTIFACT_DIR, exist_ok=True)

_tasks = {}  # taskId -> record
_lock = threading.Lock()
ALLOWED = {"profile_id", "name", "title", "company", "location", "match_reason", "source"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _shape(row: dict) -> dict:
    out = {k: row.get(k) for k in ALLOWED if row.get(k) not in (None, "")}
    out["source"] = "supercarl_api"
    return out


def _run_recruiting(query: str) -> dict:
    steps = []
    people = mock_people(query, 15)["results"]
    steps.append({"tool": "people_search", "status": "ok", "out": f"count={len(people)}"})
    # enrich the strongest handful
    for p in people[:6]:
        prof = mock_profile(p["profile_id"])
        p.setdefault("title", prof.get("title"))
        steps.append({"tool": "profile_lookup", "status": "ok", "out": p["profile_id"]})
    results = [_shape(p) for p in people if p.get("name") or p.get("profile_id")]
    return {"results": results, "steps": steps}


def _run_bd(query: str) -> dict:
    steps = []
    companies = mock_companies(query, 4)["results"]
    steps.append({"tool": "company_search", "status": "ok", "out": f"count={len(companies)}"})
    results = []
    for c in companies[:3]:
        people = mock_people(f"{query} at {c['name']}", 4)["results"]
        steps.append({"tool": "people_search", "status": "ok", "out": f"{c['name']}: {len(people)}"})
        for p in people:
            p["company"] = c["name"]
            results.append(_shape(p))
    return {"results": results, "steps": steps}


def _process(task_id: str, use_case: str, query: str, channels):
    run = _run_bd(query) if use_case == "bd" else _run_recruiting(query)
    shortlist = {
        "task_id": task_id, "use_case": use_case, "query": query,
        "results": run["results"], "count": len(run["results"]),
        "delivered_to": ["local", "s3(local-file)"],
    }
    # "deliver": write the artifact locally
    with open(os.path.join(ARTIFACT_DIR, f"{task_id}.json"), "w") as f:
        json.dump(shortlist, f, indent=2)
    with _lock:
        _tasks[task_id].update({
            "status": "completed", "result": shortlist,
            "steps": run["steps"], "updatedAt": _now(),
        })


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body):
        payload = json.dumps(body, indent=2).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/v1/health":
            return self._send(200, {"status": "healthy", "service": "supercarl", "mode": "local"})
        if self.path == "/v1/research":
            with _lock:
                return self._send(200, {"tasks": list(_tasks.values())})
        if self.path.startswith("/v1/research/"):
            tid = self.path.rsplit("/", 1)[-1]
            with _lock:
                task = _tasks.get(tid)
            return self._send(200, task) if task else self._send(404, {"error": "task not found"})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or "{}") if length else {}
        if self.path != "/v1/research":
            return self._send(404, {"error": "not found"})
        prompt = (body.get("prompt") or "").strip()
        if not prompt:
            return self._send(400, {"error": "prompt is required"})
        use_case = body.get("useCase", "recruiting")
        channels = body.get("channels", ["local"])
        task_id = f"task-{uuid4().hex[:12]}"
        with _lock:
            _tasks[task_id] = {
                "taskId": task_id, "useCase": use_case, "prompt": prompt,
                "status": "processing", "createdAt": _now(),
            }
        _process(task_id, use_case, prompt, channels)  # synchronous locally
        with _lock:
            task = _tasks[task_id]
        return self._send(202, {"taskId": task_id, "status": task["status"],
                                "poll": f"/v1/research/{task_id}", "result": task.get("result")})

    def log_message(self, fmt, *args):
        sys.stderr.write("[local] " + (fmt % args) + "\n")


if __name__ == "__main__":
    print(f"SuperCarl local API on http://{HOST}:{PORT}  (mode=local, no AWS)")
    print("  curl -s localhost:%d/v1/health" % PORT)
    print("  curl -s -X POST localhost:%d/v1/research -d '{\"prompt\":\"backend engineers in Austin\",\"useCase\":\"recruiting\"}'" % PORT)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()

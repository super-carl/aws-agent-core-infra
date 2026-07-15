"""
Local mock SuperCarl API server (Week 1).

A zero-dependency stdlib HTTP server that implements the mock contract in
supercarl-openapi.yaml. Use it to test the executors against a real HTTP host
before the production SuperCarl API is available:

    python3 mock/mock_server.py            # serves on http://127.0.0.1:8099
    export SUPERCARL_API_BASE_URL=http://127.0.0.1:8099

Then point the executor Lambdas (or a local test) at that base URL. It reuses
the same deterministic generators as the executors' fallback so responses match.
"""
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Reuse the deterministic generators from the people_search executor.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "functions", "people_search"))
from supercarl_client import mock_people, mock_companies, mock_profile  # noqa: E402

PORT = int(os.environ.get("MOCK_PORT", "8099"))


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: dict):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _auth_ok(self) -> bool:
        return self.headers.get("Authorization", "").startswith("Bearer ")

    def do_GET(self):
        if not self._auth_ok():
            return self._send(401, {"error": "missing bearer token"})
        if self.path.startswith("/v1/profiles/"):
            profile_id = self.path.rsplit("/", 1)[-1]
            return self._send(200, mock_profile(profile_id))
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._auth_ok():
            return self._send(401, {"error": "missing bearer token"})
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length) or "{}") if length else {}
        query = body.get("query", "")
        if self.path == "/v1/people/search":
            return self._send(200, mock_people(query))
        if self.path == "/v1/companies/search":
            return self._send(200, mock_companies(query))
        self._send(404, {"error": "not found"})

    def log_message(self, fmt, *args):  # quieter logs
        sys.stderr.write("[mock] " + (fmt % args) + "\n")


if __name__ == "__main__":
    print(f"SuperCarl mock API listening on http://127.0.0.1:{PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

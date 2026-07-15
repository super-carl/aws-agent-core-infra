# SuperCarl - Local development

Run the whole research API on your machine with **no AWS account, no credentials,
and no GPU**. Local mode serves the same endpoints as the deployed stack and runs
the same recruiting / BD tool routing, but with **deterministic routing** against
the mock SuperCarl data (the LLM reasoning path is the AWS-deployed Runtime).

Use it for offline development, tests, and demos.

## Option A - plain Python (stdlib only)

```bash
./scripts/run-local.sh
# or: python3 local/local_server.py
```

Serves `http://127.0.0.1:8080`.

## Option B - Docker

```bash
docker compose up --build
```

Serves `http://localhost:8080`.

## Try it

```bash
# Health
curl -s localhost:8080/v1/health
# {"status":"healthy","service":"supercarl","mode":"local"}

# Recruiting brief
curl -s -X POST localhost:8080/v1/research \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Senior backend engineers in Austin with AWS","useCase":"recruiting"}' | jq

# Business-development loop (Company -> People)
curl -s -X POST localhost:8080/v1/research \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Series-A fintech companies in NYC","useCase":"bd"}' | jq

# Fetch a task (also returns the per-step trace)
curl -s localhost:8080/v1/research/<taskId> | jq
```

Shortlist artifacts are written to `local/artifacts/<taskId>.json`.

## Endpoints (parity with the deployed API)

| Method | Endpoint | Notes |
|--------|----------|-------|
| GET | `/v1/health` | no auth |
| POST | `/v1/research` | `{prompt, useCase: recruiting\|bd, channels?}` |
| GET | `/v1/research/{taskId}` | status + shortlist + step trace |
| GET | `/v1/research` | list tasks |

Differences vs. the cloud deployment:
- No Cognito auth (local only).
- Synchronous (the cloud API is async: returns `taskId`, poll `GET`).
- Deterministic routing instead of the Bedrock agent; data is the mock contract.
- Delivery is a local file, not SES/Slack.

## Offline tests

```bash
python3 tests/test_executors.py       # executors + grounding
python3 tests/test_orchestrator.py    # orchestrator routing/validation/async
```

## Mock upstream API (optional)

The deterministic SuperCarl contract can also be served over HTTP:

```bash
python3 mock/mock_server.py           # http://127.0.0.1:8099
```

See [../mock/supercarl-openapi.yaml](../mock/supercarl-openapi.yaml).

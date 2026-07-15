# SuperCarl - API Contract

Two contracts live here:
1. **SuperCarl public REST API** (this stack) - how callers submit research tasks.
2. **SuperCarl data API** (upstream dependency) - what the executors call. The
   machine-readable contract is [../mock/supercarl-openapi.yaml](../mock/supercarl-openapi.yaml).

---

## 1. SuperCarl REST API (deployed by this stack)

Base URL: the `ApiUrl` stack output (e.g. `https://abc123.execute-api.us-east-1.amazonaws.com/v1/`).
Auth: Cognito **client-credentials** bearer token (except `/health`).

### POST /v1/research - submit a research task
```json
// request
{
  "prompt": "Senior backend engineers in Austin with AWS + distributed systems",
  "useCase": "recruiting",          // "recruiting" | "bd"
  "channels": ["ses", "slack"],     // optional, default ["ses"]
  "model": "us.anthropic.claude-sonnet-4-6-v1:0"  // optional override
}
// response 202 (async - the agent loop runs in the background)
{ "taskId": "task-ab12cd34ef56", "status": "processing", "poll": "/v1/research/task-ab12cd34ef56" }
```
Submission is asynchronous: poll `GET /v1/research/{taskId}` until `status` is
`completed` (or `failed`) to read the synthesized shortlist. API Gateway has a
hard 29s timeout, and the agent loop can take longer, so the work runs in a
background worker (5-min budget).

### GET /v1/research/{taskId} - task status + shortlist
```json
// response 200
{
  "taskId": "task-ab12cd34ef56",
  "useCase": "recruiting",
  "status": "completed",
  "createdAt": "2026-06-16T18:00:00Z",
  "result": { "shortlist": { ...see §3 }, "channels": ["ses"], "deliveredAt": "..." },
  "steps": [ ... ]
}
```

### GET /v1/research - list recent tasks
```json
{ "tasks": [ { "taskId": "...", "useCase": "...", "status": "...", "createdAt": "..." } ] }
```

### POST /v1/research/schedule - scheduled task
```json
// request
{ "prompt": "...", "useCase": "bd", "channels": ["slack"], "scheduleExpression": "rate(1 day)" }
// response 201
{ "scheduleName": "supercarl-task-...", "scheduleExpression": "rate(1 day)", "status": "scheduled" }
```
`scheduleExpression` accepts any EventBridge Scheduler expression
(`rate(...)`, `cron(...)`, `at(...)`).

### GET /v1/health - no auth
```json
{ "status": "healthy", "service": "supercarl" }
```

---

## 2. SuperCarl data API (upstream - executors call this)

Auth: `Authorization: Bearer <SuperCarl API key>` (Secrets Manager `supercarl/api-key`).
Set `SUPERCARL_API_BASE_URL` on the executor Lambdas once the real API is live.

| Method | Path | Backing executor | Purpose |
|--------|------|------------------|---------|
| POST | `/v1/people/search` | `supercarl_people_search` | Find candidate/contact profiles |
| GET | `/v1/profiles/{profileId}` | `supercarl_profile_lookup` | Resolve/enrich a profile by id |
| POST | `/v1/companies/search` | `supercarl_company_search` | Find organizations for BD |

**Errors handled by executors:** `400` (validation), `401` (auth), `404`
(not found), `429` (rate limit → surfaced as a retryable tool error), `5xx`.

See the OpenAPI file for full request/response schemas and field types.

---

## 3. Output: Shortlist schema

| Field | Type | Description |
|-------|------|-------------|
| `task_id` | string | Unique task identifier |
| `use_case` | enum | `recruiting` or `bd` |
| `query` | string | Original natural-language brief |
| `results` | array | Profiles; each `{ profile_id, name, title, company, location, match_reason, source }` |
| `count` | number | Number of profiles in the shortlist |
| `delivered_to` | array | Channels delivered to (`ses`, `slack`) |

Every `results` row carries `source = "supercarl_api"`, so each profile is
traceable to the API response it came from.

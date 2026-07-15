# Week 1 - Discovery & API Mapping (Progress)

Per the implementation plan, Week 1 has two focus areas: **API mapping** and
**Foundations**. Status below.

## API mapping - _Done when: contracts agreed, mock API ready_

| Deliverable | Status | Where |
|-------------|--------|-------|
| Document People / Profile / Company endpoints (payload, auth, errors, rate limits) | Done | [api-contract.md](api-contract.md) §2, [../mock/supercarl-openapi.yaml](../mock/supercarl-openapi.yaml) |
| Mock API ready (testable contract) | Done | [../mock/mock_server.py](../mock/mock_server.py) + deterministic fallback in executors |
| Output shortlist schema | Done | [api-contract.md](api-contract.md) §3 |

> **Open dependency:** real SuperCarl API endpoints + sandbox keys are expected
> **end of Week 1** (per the SOW). Executors are built against the mock contract and
> switch to the live API by setting `SUPERCARL_API_BASE_URL` - no code change. Confirm
> delivery at kickoff.

## Foundations - _Done when: architecture approved, repo + access ready_

| Deliverable | Status | Where |
|-------------|--------|-------|
| Project Charter | Done | [project-charter.md](project-charter.md) |
| Technical Discovery / Architecture | Done | [architecture.md](architecture.md) |
| IAM role design | Done | [iam-role-design.md](iam-role-design.md) |
| Public repo scaffold (CDK app, agent, Action Groups, docs) | Done | this repository |
| OSS license decision | Done (working: Apache-2.0) | [../LICENSE](../LICENSE) - confirm with SuperCarl |
| Confirm API keys + AWS/GitHub access | Pending | pending kickoff confirmation |

## What's deployable today (Week 1)

The full stack synthesizes and deploys; the agentic loop runs end-to-end against
the **mock** SuperCarl API:

```bash
# local mock + executors
python3 mock/mock_server.py &
export SUPERCARL_API_BASE_URL=http://127.0.0.1:8099

# or deploy to AWS (mock fallback active until the real API base URL is set)
./scripts/deploy.sh -p <profile> --dry-run   # synth check
./scripts/deploy.sh -p <profile>             # full deploy
```

## Next (Weeks 2-3 - Serverless Infrastructure)
- Point executors at the real SuperCarl API; validate live People/Profile/Company calls.
- First Action Groups return live data; input validation + structured shaping hardened.
- CloudWatch dashboards + CloudTrail across all services (Logs and traces flowing).
- Per-step trace emission (`STEP#{n}`) from the agent for QA + latency tuning.

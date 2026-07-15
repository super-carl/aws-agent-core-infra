# SuperCarl - Project Charter

## Vision
An open-source, self-deployable autonomous research worker on Bedrock AgentCore.
Any developer clones the repo and deploys it into their own AWS account (with their
own SuperCarl API key) to turn a single natural-language prompt into a synthesized
shortlist of people / company profiles.

## Primary deliverable
The **reproducible reference implementation** itself - the public "SuperCarl + AWS"
blueprint - demonstrating the Agent-First API inside a live agentic loop and driving
developer adoption. The repository is the product.

## Scope
**In scope**
- Single CDK app, one-command self-deploy (single-tenant per deployment).
- Agentic loop over the SuperCarl API (People / Profile / Company search).
- Two trigger modes (on-demand REST, scheduled), two use cases (recruiting, bd).
- Structured shortlist delivery to SES and/or Slack/Teams; S3 artifact retention.
- Memory (STM+LTM), Guardrails (moderation, PII, denied topics), observability.

**Out of scope**
- Shared/multi-tenant infrastructure (each deployer runs their own).
- Hosting or proxying the SuperCarl API (deployers bring their own key).
- A UI beyond the REST API and delivery channels.

## Success criteria
- Public GitHub repo with a one-command deploy that stands up the full stack.
- Recruiting prompt → shortlist of 10+ relevant candidate profiles.
- BD prompt → Company Search → People Search loop returns targeted contacts.
- Output grounded entirely in SuperCarl API data (no hallucinated fields).
- Guardrails verified (PII redacted, denied topics blocked).
- README doubles as the public Integration Blueprint.

## Dependencies & assumptions
- **SuperCarl API endpoints + sandbox keys** are a Week-1 dependency (expected end
  of Week 1). Until then, executors are built and tested against the documented
  mock contract (`mock/`).
- End users supply their own SuperCarl API key at deploy time.
- AWS account with Bedrock model access in `us-east-1` (Sonnet 4.6 / Haiku 4.5).

## Timeline (8-week sprint plan)
| Phase | Weeks | Focus |
|-------|-------|-------|
| Discovery & API Mapping | 1 | Contracts, mock API, foundations, repo + IAM |
| Serverless Infrastructure | 2-3 | CDK base, executors return data, observability |
| Agent Logic & Guardrails | 4-6 | Agent on Runtime, tool routing, safety, QA |
| Integration, State & UAT | 7 | DynamoDB state machine, scheduler, delivery, UAT |
| Blueprint & Handoff | 8 | Public blueprint, runbooks, ownership transfer |

## Stakeholders / roles
- **Delivery team** - builds and maintains the blueprint repo.
- **SuperCarl (client)** - provides API + final OSS license choice (Apache-2.0 / MIT).
- **End-user developers** - clone and self-deploy.

## License
Apache-2.0 (working choice; to be confirmed with SuperCarl).

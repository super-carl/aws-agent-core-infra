# SuperCarl - IAM Role Design

Least-privilege roles, one per execution identity. All roles are created by the CDK
stack; nothing is shared across deployments. Grants below mirror
`infra/lib/supercarl-stack.ts`.

## Roles

### 1. AgentCore Runtime role (agent)
The Strands agent's execution identity.
| Permission | Resource | Why |
|------------|----------|-----|
| `bedrock:InvokeModel*` | foundation-model/*, inference-profile/* (account) | Reasoning (Sonnet 4.6 / Haiku 4.5) |
| `bedrock:ApplyGuardrail`, `bedrock:GetGuardrail` | SuperCarl guardrail ARN | Safety enforcement |
| `bedrock-agentcore` Memory read/write + `BatchCreateMemoryRecords` | Memory ARN | STM + LTM |
| `lambda:InvokeFunction` | the 4 `supercarl_*` executors | Tool calls |
| DynamoDB read/write | `supercarl-tasks` | Step traces |

### 2. Orchestrator Lambda role (hub)
| Permission | Resource | Why |
|------------|----------|-----|
| `bedrock-agentcore:InvokeAgentRuntime` | Runtime ARN | Run the agent |
| DynamoDB read/write | `supercarl-tasks` + `byCreatedAt` GSI | Task state machine |
| `scheduler:CreateSchedule/DeleteSchedule/GetSchedule` | `schedule/supercarl/*` | Scheduled tasks |
| `iam:PassRole` | SchedulerRole | Hand the schedule its invoke role |
| Basic Lambda execution + X-Ray | (managed) | Logs + traces |

### 3. Action Group executor roles (tools)
Each executor (`people_search`, `profile_lookup`, `company_search`) gets:
| Permission | Resource | Why |
|------------|----------|-----|
| `secretsmanager:GetSecretValue` | `supercarl/api-key` | Auth to SuperCarl API |
| Basic Lambda execution + X-Ray | (managed) | Logs + traces |

`deliver_results` additionally gets:
| Permission | Resource | Why |
|------------|----------|-----|
| `secretsmanager:GetSecretValue` | `supercarl/slack-webhook` | Slack/Teams delivery |
| `s3:PutObject*` | artifact bucket | Retain shortlist artifacts |
| `ses:SendEmail`, `ses:SendRawEmail` | `*` (scope to verified identity in prod) | Email delivery |

### 4. EventBridge Scheduler role
| Permission | Resource | Why |
|------------|----------|-----|
| `lambda:InvokeFunction` | Orchestrator | Fire scheduled research runs |
Trust: `scheduler.amazonaws.com`.

## Principles
- **No wildcards on identity-bearing actions** except SES (tighten to a verified
  sender ARN in production via a condition key).
- **Secrets never travel through Lambda env vars** - only ARNs do; values are
  fetched at runtime and cached per container.
- **CDK `@aws-cdk/aws-iam:minimizePolicies`** is enabled (see `cdk.json`).
- **Credential rotation**: rotate the `supercarl/api-key` secret value in place;
  no code or role change required (executors read it on cold start).

## Hardening backlog (post-Week-1)
- Scope `ses:SendEmail` to the verified identity ARN with a `ses:FromAddress` condition.
- Add a resource policy on the task table; enable DynamoDB encryption with a CMK.
- Add VPC endpoints + private networking if the SuperCarl API supports PrivateLink.

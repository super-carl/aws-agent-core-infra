# Diagrams

## `supercarl-aws-architecture-agentcore.drawio`

The SuperCarl architecture, drawn with **real AWS service icons** (draw.io AWS
2020 / `mxgraph.aws4` stencils). This is the full **reference / target**
architecture — it includes optional pieces that `deploy.sh` does not provision
today (a CloudFront + S3 web UI, web search, AgentCore Gateway / Identity,
prompt versioning/logging). The inline Mermaid diagram in the root README
reflects exactly what the CDK stack builds.

**Open / edit:**
- Web: <https://app.diagrams.net> → File → Open → this file.
- VS Code: install the *Draw.io Integration* extension, then open the file.
- Desktop: [diagrams.net desktop](https://github.com/jgraph/drawio-desktop).

**Export** (PNG/SVG for slides): File → Export as → PNG/SVG, or with the CLI:

```bash
drawio -x -f png -o supercarl-architecture.png docs/diagrams/supercarl-aws-architecture-agentcore.drawio
```

The diagram shows the full flow: Users → API Gateway (+ Cognito) / EventBridge →
Orchestrator (async worker) → **AgentCore Runtime** (Runtime · Gateway · Memory ·
Guardrails · Bedrock models) → **SuperCarl API/MCP** (search/read only) →
`deliver_results` → SES / Slack / S3, with DynamoDB task state and the
security/observability layer (CloudWatch, CloudTrail).

> A Markdown/Mermaid version of the same architecture (renders inline on GitHub)
> lives in the root [README](../../README.md#architecture).

# Diagrams

## `supercarl-architecture.drawio`

The SuperCarl architecture, drawn with **real AWS service icons** (draw.io AWS
2020 / `mxgraph.aws4` stencils).

**Open / edit:**
- Web: <https://app.diagrams.net> → File → Open → this file.
- VS Code: install the *Draw.io Integration* extension, then open the file.
- Desktop: [diagrams.net desktop](https://github.com/jgraph/drawio-desktop).

**Export** (PNG/SVG for slides): File → Export as → PNG/SVG, or with the CLI:

```bash
drawio -x -f png -o supercarl-architecture.png docs/diagrams/supercarl-architecture.drawio
```

The diagram shows the full flow: Client → API Gateway (+ Cognito) → Orchestrator
(async worker) → AgentCore Runtime → **SuperCarl MCP** (search/read only) →
`deliver_results` → SES / Slack / S3, with DynamoDB task state and the
observability stack (CloudWatch, CloudTrail, SNS).

> A Markdown/Mermaid version of the same architecture (renders inline on GitHub)
> lives in the root [README](../../README.md#architecture).

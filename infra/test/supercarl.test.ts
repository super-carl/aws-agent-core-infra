import { App } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { SuperCarlStack } from "../lib/supercarl-stack";

describe("SuperCarlStack", () => {
  const app = new App();
  const stack = new SuperCarlStack(app, "TestStack", {
    env: { account: "123456789012", region: "us-east-1" },
  });
  const template = Template.fromStack(stack);

  test("creates the DynamoDB task table", () => {
    template.hasResourceProperties("AWS::DynamoDB::Table", {
      TableName: "supercarl-tasks",
    });
  });

  test("creates a Bedrock Guardrail with denied topics", () => {
    template.resourceCountIs("AWS::Bedrock::Guardrail", 1);
  });

  test("creates the four Action Group executor Lambdas + orchestrator", () => {
    // 4 executors + orchestrator = 5 Python functions (plus any CDK helpers).
    const fns = template.findResources("AWS::Lambda::Function");
    const names = Object.values(fns)
      .map((f: any) => f.Properties?.FunctionName)
      .filter(Boolean);
    expect(names).toEqual(
      expect.arrayContaining([
        "supercarl_people_search",
        "supercarl_profile_lookup",
        "supercarl_company_search",
        "supercarl_deliver_results",
        "supercarl-orchestrator",
      ])
    );
  });

  test("exposes the REST API", () => {
    template.hasResourceProperties("AWS::ApiGateway::RestApi", {
      Name: "supercarl-api",
    });
  });
});

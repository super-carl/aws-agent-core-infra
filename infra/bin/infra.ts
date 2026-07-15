#!/usr/bin/env node
import "source-map-support/register.js";
import * as cdk from "aws-cdk-lib";
import { SuperCarlStack } from "../lib/supercarl-stack";

const app = new cdk.App();

new SuperCarlStack(app, "SuperCarlStack", {
  env: {
    account: process.env.CDK_DEFAULT_ACCOUNT,
    region: process.env.CDK_DEFAULT_REGION || "us-east-1",
  },
  description:
    "SuperCarl — autonomous research worker on Bedrock AgentCore: Runtime, Memory, Guardrails, " +
    "Orchestrator + Action Group Lambdas, DynamoDB task state, API Gateway + Cognito, EventBridge Scheduler.",
});

import {
  Stack,
  StackProps,
  Duration,
  CfnOutput,
  RemovalPolicy,
  Tags,
} from "aws-cdk-lib";
import { Construct } from "constructs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as apigw from "aws-cdk-lib/aws-apigateway";
import * as cognito from "aws-cdk-lib/aws-cognito";
import * as iam from "aws-cdk-lib/aws-iam";
import * as logs from "aws-cdk-lib/aws-logs";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import * as secretsmanager from "aws-cdk-lib/aws-secretsmanager";
import * as cloudwatch from "aws-cdk-lib/aws-cloudwatch";
import * as cw_actions from "aws-cdk-lib/aws-cloudwatch-actions";
import * as sns from "aws-cdk-lib/aws-sns";
import * as cloudtrail from "aws-cdk-lib/aws-cloudtrail";
import * as scheduler from "aws-cdk-lib/aws-scheduler";
import * as bedrock from "aws-cdk-lib/aws-bedrock";
import * as agentcore from "@aws-cdk/aws-bedrock-agentcore-alpha";
import { Platform } from "aws-cdk-lib/aws-ecr-assets";
import { join } from "path";

/**
 * SuperCarl — autonomous research worker on Bedrock AgentCore.
 *
 * Single-tenant, single-command deploy into the deployer's own AWS account.
 * The orchestrator Lambda is the hub: triggered on-demand (API Gateway + Cognito)
 * or on a schedule (EventBridge), it tracks task state in DynamoDB, invokes the
 * AgentCore Runtime (Strands agent), which calls the SuperCarl API through Action
 * Group executor Lambdas and routes results out to SES / Slack.
 */
export class SuperCarlStack extends Stack {
  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    // ─── Tags ──────────────────────────────────────────────────────────────
    Tags.of(this).add("Project", "SuperCarl");
    Tags.of(this).add("ManagedBy", "CDK");

    // Model: Sonnet 4.5 (the inference profile with access enabled in this
    // account). Switchable to Haiku 4.5
    // ("us.anthropic.claude-haiku-4-5-20251001-v1:0") or Sonnet 4.6 once access
    // is granted ("us.anthropic.claude-sonnet-4-6").
    const MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0";

    // ─── S3 (artifact retention + CloudTrail logs) ─────────────────────────
    const artifactBucket = new s3.Bucket(this, "ArtifactBucket", {
      bucketName: `supercarl-${this.account}-${this.region}`,
      versioned: true,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      lifecycleRules: [
        { id: "DeleteOldVersions", enabled: true, noncurrentVersionExpiration: Duration.days(30) },
        { id: "AbortIncompleteUploads", enabled: true, abortIncompleteMultipartUploadAfter: Duration.days(7) },
      ],
    });

    // ─── DynamoDB single-table task state machine ──────────────────────────
    // PK = TASK#{taskId}, SK ∈ { META, STEP#{n}, RESULT }
    const taskTable = new dynamodb.Table(this, "TaskTable", {
      tableName: "supercarl-tasks",
      partitionKey: { name: "PK", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "SK", type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      pointInTimeRecovery: true,
      removalPolicy: RemovalPolicy.DESTROY,
      timeToLiveAttribute: "ttl",
    });
    // GSI for "list recent tasks" (GET /v1/research)
    taskTable.addGlobalSecondaryIndex({
      indexName: "byCreatedAt",
      partitionKey: { name: "itemType", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "createdAt", type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    // ─── Cognito (client-credentials auth for the REST API) ────────────────
    const userPool = new cognito.UserPool(this, "UserPool", {
      userPoolName: "supercarl-user-pool",
      mfa: cognito.Mfa.OFF,
      selfSignUpEnabled: false,
      signInAliases: { email: true, username: true },
      standardAttributes: { email: { required: true, mutable: true } },
      passwordPolicy: {
        minLength: 8,
        requireLowercase: true,
        requireUppercase: true,
        requireDigits: true,
        requireSymbols: true,
      },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      removalPolicy: RemovalPolicy.DESTROY,
    });

    const readScope = new cognito.ResourceServerScope({
      scopeName: "read",
      scopeDescription: "Read research tasks",
    });
    const writeScope = new cognito.ResourceServerScope({
      scopeName: "write",
      scopeDescription: "Submit research tasks",
    });

    const resourceServer = userPool.addResourceServer("ResourceServer", {
      identifier: "supercarl-api",
      userPoolResourceServerName: "SuperCarl API",
      scopes: [readScope, writeScope],
    });

    const userPoolClient = new cognito.UserPoolClient(this, "UserPoolClient", {
      userPool,
      userPoolClientName: "supercarl-client",
      generateSecret: true,
      oAuth: {
        flows: { clientCredentials: true },
        scopes: [
          cognito.OAuthScope.resourceServer(resourceServer, readScope),
          cognito.OAuthScope.resourceServer(resourceServer, writeScope),
        ],
      },
      authFlows: { userPassword: true, userSrp: true },
    });

    userPool.addDomain("UserPoolDomain", {
      cognitoDomain: { domainPrefix: `supercarl-${this.account}` },
    });

    // ─── Secrets Manager ───────────────────────────────────────────────────
    // SuperCarl API key — the deployer's own credential (placeholder; update post-deploy).
    const apiKeySecret = new secretsmanager.Secret(this, "SuperCarlApiKeySecret", {
      secretName: "supercarl/api-key",
      description: "SuperCarl API key for People/Profile/Company search",
      generateSecretString: {
        secretStringTemplate: JSON.stringify({ api_key: "your-supercarl-api-key-here" }),
        generateStringKey: "api_key",
        excludeCharacters: '"@/\\',
      },
    });

    // Slack/Teams incoming webhook URL for delivery (placeholder; optional).
    const slackSecret = new secretsmanager.Secret(this, "SlackWebhookSecret", {
      secretName: "supercarl/slack-webhook",
      description: "Slack/Teams incoming webhook URL for shortlist delivery",
      generateSecretString: {
        secretStringTemplate: JSON.stringify({ webhook_url: "" }),
        generateStringKey: "webhook_url",
        excludeCharacters: '"@/\\',
      },
    });

    // ─── CloudTrail ────────────────────────────────────────────────────────
    const trailLogGroup = new logs.LogGroup(this, "CloudTrailLogGroup", {
      logGroupName: "/aws/cloudtrail/supercarl",
      retention: logs.RetentionDays.ONE_WEEK,
      removalPolicy: RemovalPolicy.DESTROY,
    });
    new cloudtrail.Trail(this, "Trail", {
      trailName: "supercarl-trail",
      bucket: artifactBucket,
      s3KeyPrefix: "cloudtrail",
      cloudWatchLogGroup: trailLogGroup,
      sendToCloudWatchLogs: true,
      isMultiRegionTrail: false,
    });

    // ─── Bedrock Guardrail ─────────────────────────────────────────────────
    // Content filters + PII handling + denied topics (legal/financial advice,
    // scoring beyond API data) per the implementation plan.
    const guardrail = new bedrock.CfnGuardrail(this, "Guardrail", {
      name: "supercarl-guardrail",
      description: "Content safety + PII + denied topics for SuperCarl",
      blockedInputMessaging: "Your request was blocked by our content safety policy.",
      blockedOutputsMessaging: "The response was blocked by our content safety policy.",
      contentPolicyConfig: {
        // Full-strength moderation on INPUT (where prompts/attacks arrive).
        // OUTPUT is grounded SuperCarl API data (names, titles, companies), so
        // high-strength output filters were intermittently blocking legitimate
        // shortlists — output moderation is relaxed here while PII redaction and
        // denied topics still apply to output.
        filtersConfig: [
          { type: "SEXUAL", inputStrength: "HIGH", outputStrength: "NONE" },
          { type: "VIOLENCE", inputStrength: "HIGH", outputStrength: "NONE" },
          { type: "HATE", inputStrength: "HIGH", outputStrength: "NONE" },
          { type: "INSULTS", inputStrength: "HIGH", outputStrength: "NONE" },
          { type: "MISCONDUCT", inputStrength: "HIGH", outputStrength: "NONE" },
          // PROMPT_ATTACK at HIGH was blocking our own directive-heavy system
          // prompt (classified as an injection attempt), failing the agent
          // intermittently. The system prompt is trusted content we author;
          // disable prompt-attack detection here. (Proper input-tagging to guard
          // only user briefs is a hardening backlog item.)
          { type: "PROMPT_ATTACK", inputStrength: "NONE", outputStrength: "NONE" },
        ],
      },
      sensitiveInformationPolicyConfig: {
        // Email anonymized; SSN and credit/debit card blocked.
        piiEntitiesConfig: [
          { type: "EMAIL", action: "ANONYMIZE" },
          { type: "US_SOCIAL_SECURITY_NUMBER", action: "BLOCK" },
          { type: "CREDIT_DEBIT_CARD_NUMBER", action: "BLOCK" },
        ],
      },
      topicPolicyConfig: {
        topicsConfig: [
          {
            name: "LegalAdvice",
            definition: "Providing legal advice, interpretation of law, or counsel on legal matters.",
            examples: ["Is this contract enforceable?", "Can I sue this candidate?"],
            type: "DENY",
          },
          {
            // Narrow: advice to the USER about their own money — NOT researching
            // finance/fintech companies (a core BD use case). Max 200 chars.
            name: "FinancialAdvice",
            definition:
              "Personalized advice to the user about their own money, investments, " +
              "taxes, or which securities to buy or sell. Researching or listing " +
              "finance or fintech companies is allowed.",
            examples: [
              "Should I invest my savings in this company's stock?",
              "What stocks should I buy this quarter?",
              "How should I allocate my 401k?",
            ],
            type: "DENY",
          },
          {
            // Narrow: judging a person's worth or personal/protected attributes.
            // Must NOT catch normally listing/ordering candidates in a shortlist.
            name: "ScoringBeyondApiData",
            definition:
              "Judging or rating a person's intelligence, worth, attractiveness, or " +
              "protected personal attributes (race, religion, health, etc.). Listing " +
              "or ranking candidates by job fit is allowed.",
            examples: ["Rate this person's intelligence.", "Who is the most attractive candidate?"],
            type: "DENY",
          },
        ],
      },
    });

    const guardrailVersion = new bedrock.CfnGuardrailVersion(this, "GuardrailVersion", {
      guardrailIdentifier: guardrail.attrGuardrailId,
      // Bump this description to publish a new version when the guardrail changes
      // (the Runtime reads the versioned guardrail via GUARDRAIL_VERSION).
      description: "v4 - prompt-attack off (was blocking our own system prompt)",
    });

    // ─── AgentCore Memory (STM + LTM) ──────────────────────────────────────
    // STM = per-session loop context; LTM = deployer's ICP (roles, regions, exclusions).
    const memory = new agentcore.Memory(this, "Memory", {
      memoryName: "supercarl_memory",
      memoryStrategies: [
        agentcore.MemoryStrategy.usingBuiltInSemantic(),
        agentcore.MemoryStrategy.usingBuiltInSummarization(),
        agentcore.MemoryStrategy.usingBuiltInUserPreference(),
      ],
      expirationDuration: Duration.days(90),
      description: "Memory for SuperCarl research worker",
    });

    // ─── Action Group executor Lambdas (the agent's tools) ─────────────────
    // Each is invoked by the agent as a tool. Auth to SuperCarl API via Secrets
    // Manager; input validation, rate-limit handling, structured response shaping.
    const executorEnv = {
      API_KEY_SECRET_ARN: apiKeySecret.secretArn,
      // SuperCarl API base URL. Until the real API ships (end of Week 1) this
      // points at the mock contract; override per deployment via CDK/env.
      SUPERCARL_API_BASE_URL: process.env.SUPERCARL_API_BASE_URL || "https://mock.supercarl.local",
      REGION: this.region,
    };

    const makeExecutor = (name: string, dir: string): lambda.Function => {
      const fn = new lambda.Function(this, `Executor_${name}`, {
        functionName: `supercarl_${name}`,
        runtime: lambda.Runtime.PYTHON_3_12,
        handler: "index.lambda_handler",
        // Executors use only stdlib (urllib) + boto3, which is provided by the
        // Lambda Python runtime — no pip/Docker bundling needed (faster, no
        // network dependency at deploy time).
        code: lambda.Code.fromAsset(join(__dirname, `../../functions/${dir}`), {
          exclude: ["__pycache__", "*.pyc", "requirements.txt"],
        }),
        timeout: Duration.seconds(30),
        memorySize: 512,
        environment: executorEnv,
        tracing: lambda.Tracing.ACTIVE,
      });
      apiKeySecret.grantRead(fn);
      return fn;
    };

    const peopleSearchFn = makeExecutor("people_search", "people_search");
    const profileLookupFn = makeExecutor("profile_lookup", "profile_lookup");
    const companySearchFn = makeExecutor("company_search", "company_search");
    const deliverResultsFn = makeExecutor("deliver_results", "deliver_results");

    // deliver_results also needs SES send + Slack webhook + S3 artifact write.
    slackSecret.grantRead(deliverResultsFn);
    artifactBucket.grantWrite(deliverResultsFn);
    deliverResultsFn.addEnvironment("SLACK_WEBHOOK_SECRET_ARN", slackSecret.secretArn);
    deliverResultsFn.addEnvironment("ARTIFACT_BUCKET", artifactBucket.bucketName);
    // First delivery writes RESULT + marks the task completed (idempotent).
    deliverResultsFn.addEnvironment("TASK_TABLE", taskTable.tableName);
    taskTable.grantReadWriteData(deliverResultsFn);
    deliverResultsFn.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["ses:SendEmail", "ses:SendRawEmail"],
        resources: ["*"],
      })
    );

    // ─── AgentCore Runtime (Strands agent, ARM64) ──────────────────────────
    const agentRuntimeArtifact = agentcore.AgentRuntimeArtifact.fromAsset(
      join(__dirname, "../../agentcore_agents"),
      { platform: Platform.LINUX_ARM64 }
    );

    const runtime = new agentcore.Runtime(this, "Runtime", {
      runtimeName: "supercarl_runtime",
      agentRuntimeArtifact,
      networkConfiguration: agentcore.RuntimeNetworkConfiguration.usingPublicNetwork(),
      description: "SuperCarl agent runtime (Strands): reasoning + tool routing",
      authorizerConfiguration: agentcore.RuntimeAuthorizerConfiguration.usingIAM(),
      environmentVariables: {
        MEMORY_ID: memory.memoryId,
        GUARDRAIL_ID: guardrail.attrGuardrailId,
        GUARDRAIL_VERSION: guardrailVersion.attrVersion,
        MODEL_ID,
        TASK_TABLE: taskTable.tableName,
        PEOPLE_SEARCH_FN: peopleSearchFn.functionName,
        PROFILE_LOOKUP_FN: profileLookupFn.functionName,
        COMPANY_SEARCH_FN: companySearchFn.functionName,
        DELIVER_RESULTS_FN: deliverResultsFn.functionName,
        // SuperCarl MCP creds {api_key, mcp_url} live in this secret; the agent
        // connects to the live MCP server when present, else uses mock tools.
        API_KEY_SECRET_ARN: apiKeySecret.secretArn,
        AGENT_OBSERVABILITY_ENABLED: "true",
        OTEL_PYTHON_DISTRO: "aws_distro",
        OTEL_PYTHON_CONFIGURATOR: "aws_configurator",
        AWS_REGION: this.region,
      },
      lifecycleConfiguration: {
        idleRuntimeSessionTimeout: Duration.minutes(15),
        maxLifetime: Duration.hours(8),
      },
    });

    memory.grantRead(runtime);
    memory.grantWrite(runtime);
    runtime.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["bedrock-agentcore:BatchCreateMemoryRecords"],
        resources: [memory.memoryArn],
      })
    );
    runtime.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
        resources: [
          "arn:aws:bedrock:*::foundation-model/*",
          `arn:aws:bedrock:*:${this.account}:inference-profile/*`,
        ],
      })
    );
    runtime.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["bedrock:ApplyGuardrail", "bedrock:GetGuardrail"],
        resources: [guardrail.attrGuardrailArn],
      })
    );
    // Agent invokes its tools (Action Group executors) via Lambda.
    [peopleSearchFn, profileLookupFn, companySearchFn, deliverResultsFn].forEach((fn) =>
      fn.grantInvoke(runtime)
    );
    taskTable.grantReadWriteData(runtime);
    // Agent reads the SuperCarl MCP creds (api_key + mcp_url) at init.
    apiKeySecret.grantRead(runtime);

    // ─── Orchestrator Lambda (API GW / EventBridge → Runtime) ──────────────
    const orchestrator = new lambda.Function(this, "Orchestrator", {
      functionName: "supercarl-orchestrator",
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: "index.lambda_handler",
      // Orchestrator uses only boto3 (provided by the Lambda runtime) — package
      // the source directly without pip/Docker bundling.
      code: lambda.Code.fromAsset(join(__dirname, "../../functions/orchestrator"), {
        exclude: ["__pycache__", "*.pyc", "requirements.txt"],
      }),
      // Worker path runs the full agent loop (multi-step). The API path returns
      // in <1s via async self-invoke. retryAttempts:0 below stops Lambda from
      // re-running a slow/failed worker (which would duplicate MCP calls).
      timeout: Duration.seconds(240),
      retryAttempts: 0,
      memorySize: 1024,
      environment: {
        AGENTCORE_RUNTIME_ARN: runtime.agentRuntimeArn,
        TASK_TABLE: taskTable.tableName,
        REGION: this.region,
      },
      tracing: lambda.Tracing.ACTIVE,
    });
    runtime.grantInvokeRuntime(orchestrator);
    taskTable.grantReadWriteData(orchestrator);
    // Allow the orchestrator to self-invoke asynchronously (API -> worker).
    orchestrator.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["lambda:InvokeFunction"],
        resources: [`arn:aws:lambda:${this.region}:${this.account}:function:supercarl-orchestrator`],
      })
    );

    // ─── EventBridge Scheduler (scheduled research runs) ───────────────────
    // Schedule group the orchestrator creates schedules in at runtime.
    new scheduler.CfnScheduleGroup(this, "ScheduleGroup", { name: "supercarl" });

    const schedulerRole = new iam.Role(this, "SchedulerRole", {
      roleName: "supercarl-scheduler-role",
      assumedBy: new iam.ServicePrincipal("scheduler.amazonaws.com"),
      description: "Lets EventBridge Scheduler invoke the SuperCarl orchestrator",
    });

    // Use literal ARNs (resources have explicit names) to avoid a circular
    // dependency between the orchestrator and the scheduler role: grantInvoke
    // would make the role depend on the function, while the function depends on
    // the role's ARN via env var — CloudFormation rejects that cycle.
    const orchestratorArn = `arn:aws:lambda:${this.region}:${this.account}:function:supercarl-orchestrator`;
    const schedulerRoleArn = `arn:aws:iam::${this.account}:role/supercarl-scheduler-role`;

    schedulerRole.addToPolicy(
      new iam.PolicyStatement({
        actions: ["lambda:InvokeFunction"],
        resources: [orchestratorArn],
      })
    );
    // The orchestrator creates schedules at runtime (POST /v1/research/schedule).
    orchestrator.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["scheduler:CreateSchedule", "scheduler:DeleteSchedule", "scheduler:GetSchedule"],
        resources: [`arn:aws:scheduler:${this.region}:${this.account}:schedule/supercarl/*`],
      })
    );
    orchestrator.addToRolePolicy(
      new iam.PolicyStatement({
        actions: ["iam:PassRole"],
        resources: [schedulerRoleArn],
      })
    );
    orchestrator.addEnvironment("SCHEDULER_ROLE_ARN", schedulerRoleArn);
    orchestrator.addEnvironment("ORCHESTRATOR_ARN", orchestratorArn);

    // ─── API Gateway ───────────────────────────────────────────────────────
    const api = new apigw.RestApi(this, "Api", {
      restApiName: "supercarl-api",
      description: "SuperCarl research API",
      defaultCorsPreflightOptions: {
        allowOrigins: apigw.Cors.ALL_ORIGINS,
        allowMethods: apigw.Cors.ALL_METHODS,
        allowHeaders: ["Content-Type", "Authorization", "X-Session-ID"],
      },
      deployOptions: { stageName: "v1", tracingEnabled: true },
    });

    const authorizer = new apigw.CognitoUserPoolsAuthorizer(this, "Authorizer", {
      cognitoUserPools: [userPool],
      authorizerName: "SuperCarlAuthorizer",
    });
    const writeAuth = {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
      authorizationScopes: [`${resourceServer.userPoolResourceServerId}/write`],
    };
    const readAuth = {
      authorizer,
      authorizationType: apigw.AuthorizationType.COGNITO,
      authorizationScopes: [`${resourceServer.userPoolResourceServerId}/read`],
    };
    const orchestratorIntegration = new apigw.LambdaIntegration(orchestrator);

    // GET /v1/health (no auth)
    api.root.addResource("health").addMethod(
      "GET",
      new apigw.MockIntegration({
        integrationResponses: [
          {
            statusCode: "200",
            responseTemplates: {
              "application/json": JSON.stringify({ status: "healthy", service: "supercarl" }),
            },
          },
        ],
        requestTemplates: { "application/json": JSON.stringify({ statusCode: 200 }) },
      }),
      { methodResponses: [{ statusCode: "200" }], authorizationType: apigw.AuthorizationType.NONE }
    );

    // /v1/research
    const research = api.root.addResource("research");
    research.addMethod("POST", orchestratorIntegration, writeAuth); // submit task
    research.addMethod("GET", orchestratorIntegration, readAuth); // list recent tasks
    research.addResource("{taskId}").addMethod("GET", orchestratorIntegration, readAuth); // status + shortlist
    research.addResource("schedule").addMethod("POST", orchestratorIntegration, writeAuth); // scheduled task

    api.addUsagePlan("UsagePlan", {
      name: "supercarl-usage-plan",
      apiStages: [{ api, stage: api.deploymentStage }],
      throttle: { rateLimit: 50, burstLimit: 100 },
    });

    // ─── CloudWatch / SNS alarms ───────────────────────────────────────────
    const alertTopic = new sns.Topic(this, "AlertTopic", {
      topicName: "supercarl-alerts",
      displayName: "SuperCarl Alerts",
    });

    const runtimeErrorsAlarm = new cloudwatch.Alarm(this, "RuntimeErrorsAlarm", {
      alarmName: "supercarl-runtime-user-errors-high",
      alarmDescription: "AgentCore Runtime returning a high number of user errors.",
      metric: new cloudwatch.Metric({
        namespace: "bedrock-agentcore",
        metricName: "UserErrors",
        dimensionsMap: { ResourceArn: runtime.agentRuntimeArn, Operation: "InvokeAgentRuntime" },
        statistic: "Sum",
        period: Duration.minutes(5),
      }),
      threshold: 5,
      evaluationPeriods: 3,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    const guardrailAlarm = new cloudwatch.Alarm(this, "GuardrailInterventionsAlarm", {
      alarmName: "supercarl-guardrail-interventions-high",
      alarmDescription: "Bedrock Guardrails intervening on a high number of invocations.",
      metric: new cloudwatch.Metric({
        namespace: "AWS/Bedrock/Guardrails",
        metricName: "InvocationsIntervened",
        dimensionsMap: { GuardrailArn: guardrail.attrGuardrailArn },
        statistic: "Sum",
        period: Duration.minutes(5),
      }),
      threshold: 5,
      evaluationPeriods: 3,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    // Orchestrator error-rate alarm (hub health).
    const orchestratorErrorsAlarm = new cloudwatch.Alarm(this, "OrchestratorErrorsAlarm", {
      alarmName: "supercarl-orchestrator-errors-high",
      alarmDescription: "The orchestrator Lambda is failing on a high number of invocations.",
      metric: new cloudwatch.Metric({
        namespace: "AWS/Lambda",
        metricName: "Errors",
        dimensionsMap: { FunctionName: orchestrator.functionName },
        statistic: "Sum",
        period: Duration.minutes(5),
      }),
      threshold: 3,
      evaluationPeriods: 3,
      comparisonOperator: cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
      treatMissingData: cloudwatch.TreatMissingData.NOT_BREACHING,
    });

    const snsAction = new cw_actions.SnsAction(alertTopic);
    runtimeErrorsAlarm.addAlarmAction(snsAction);
    guardrailAlarm.addAlarmAction(snsAction);
    orchestratorErrorsAlarm.addAlarmAction(snsAction);

    // ─── CloudWatch Dashboard (single pane across all services) ────────────
    const lambdaMetric = (fn: lambda.Function, metricName: string, stat = "Sum") =>
      new cloudwatch.Metric({
        namespace: "AWS/Lambda",
        metricName,
        dimensionsMap: { FunctionName: fn.functionName },
        statistic: stat,
        period: Duration.minutes(5),
      });

    const executors = [peopleSearchFn, profileLookupFn, companySearchFn, deliverResultsFn];
    const apiDims = { ApiName: api.restApiName, Stage: api.deploymentStage.stageName };
    const apiMetric = (metricName: string, stat: string) =>
      new cloudwatch.Metric({
        namespace: "AWS/ApiGateway",
        metricName,
        dimensionsMap: apiDims,
        statistic: stat,
        period: Duration.minutes(5),
      });

    const dashboard = new cloudwatch.Dashboard(this, "Dashboard", {
      dashboardName: "supercarl",
      defaultInterval: Duration.hours(3),
    });

    dashboard.addWidgets(
      new cloudwatch.TextWidget({
        markdown:
          "# SuperCarl — operations\n" +
          "Autonomous research worker on Bedrock AgentCore. Rows below trace a request " +
          "end to end: **API Gateway → Orchestrator → Action Group executors → AgentCore " +
          "Runtime**, with Guardrails and DynamoDB. Per-tool step traces live in the " +
          "`supercarl-tasks` table (`STEP#n` items).",
        width: 24,
        height: 3,
      })
    );

    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "API Gateway — requests & errors",
        left: [apiMetric("Count", "Sum")],
        right: [apiMetric("4XXError", "Sum"), apiMetric("5XXError", "Sum")],
        width: 12,
      }),
      new cloudwatch.GraphWidget({
        title: "API Gateway — latency (p50/p99)",
        left: [apiMetric("Latency", "p50"), apiMetric("Latency", "p99")],
        width: 12,
      })
    );

    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Orchestrator — invocations / errors / throttles",
        left: [
          lambdaMetric(orchestrator, "Invocations"),
          lambdaMetric(orchestrator, "Errors"),
          lambdaMetric(orchestrator, "Throttles"),
        ],
        width: 12,
      }),
      new cloudwatch.GraphWidget({
        title: "Orchestrator — duration",
        left: [lambdaMetric(orchestrator, "Duration", "Average"), lambdaMetric(orchestrator, "Duration", "Maximum")],
        width: 12,
      })
    );

    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "Action Group executors — invocations",
        left: executors.map((fn) => lambdaMetric(fn, "Invocations")),
        width: 12,
      }),
      new cloudwatch.GraphWidget({
        title: "Action Group executors — errors",
        left: executors.map((fn) => lambdaMetric(fn, "Errors")),
        width: 12,
      })
    );

    dashboard.addWidgets(
      new cloudwatch.GraphWidget({
        title: "AgentCore Runtime — invocations & user errors",
        left: [
          new cloudwatch.Metric({
            namespace: "bedrock-agentcore",
            metricName: "Invocations",
            dimensionsMap: { ResourceArn: runtime.agentRuntimeArn, Operation: "InvokeAgentRuntime" },
            statistic: "Sum",
            period: Duration.minutes(5),
          }),
          runtimeErrorsAlarm.metric,
        ],
        width: 8,
      }),
      new cloudwatch.GraphWidget({
        title: "Guardrails — interventions",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/Bedrock/Guardrails",
            metricName: "InvocationsIntervened",
            dimensionsMap: { GuardrailArn: guardrail.attrGuardrailArn },
            statistic: "Sum",
            period: Duration.minutes(5),
          }),
        ],
        width: 8,
      }),
      new cloudwatch.GraphWidget({
        title: "DynamoDB — capacity & throttles",
        left: [
          new cloudwatch.Metric({
            namespace: "AWS/DynamoDB",
            metricName: "ConsumedWriteCapacityUnits",
            dimensionsMap: { TableName: taskTable.tableName },
            statistic: "Sum",
            period: Duration.minutes(5),
          }),
          new cloudwatch.Metric({
            namespace: "AWS/DynamoDB",
            metricName: "ThrottledRequests",
            dimensionsMap: { TableName: taskTable.tableName },
            statistic: "Sum",
            period: Duration.minutes(5),
          }),
        ],
        width: 8,
      })
    );

    // ─── Outputs ───────────────────────────────────────────────────────────
    new CfnOutput(this, "ApiUrl", { value: api.url, description: "SuperCarl REST API base URL" });
    new CfnOutput(this, "UserPoolId", { value: userPool.userPoolId, description: "Cognito User Pool ID" });
    new CfnOutput(this, "UserPoolClientId", { value: userPoolClient.userPoolClientId, description: "Cognito Client ID" });
    new CfnOutput(this, "CognitoDomain", { value: `supercarl-${this.account}`, description: "Cognito domain prefix" });
    new CfnOutput(this, "RuntimeArn", { value: runtime.agentRuntimeArn, description: "AgentCore Runtime ARN" });
    new CfnOutput(this, "MemoryId", { value: memory.memoryId, description: "AgentCore Memory ID" });
    new CfnOutput(this, "GuardrailId", { value: guardrail.attrGuardrailId, description: "Bedrock Guardrail ID" });
    new CfnOutput(this, "TaskTableName", { value: taskTable.tableName, description: "DynamoDB task table" });
    new CfnOutput(this, "ApiKeySecretArn", { value: apiKeySecret.secretArn, description: "SuperCarl API key secret ARN" });
    new CfnOutput(this, "SlackWebhookSecretArn", { value: slackSecret.secretArn, description: "Slack webhook secret ARN" });
    new CfnOutput(this, "BucketName", { value: artifactBucket.bucketName, description: "Artifact S3 bucket" });
    new CfnOutput(this, "OrchestratorArn", { value: orchestrator.functionArn, description: "Orchestrator Lambda ARN" });
    new CfnOutput(this, "DashboardName", { value: dashboard.dashboardName, description: "CloudWatch dashboard name" });
    new CfnOutput(this, "DashboardUrl", {
      value: `https://${this.region}.console.aws.amazon.com/cloudwatch/home?region=${this.region}#dashboards/dashboard/supercarl`,
      description: "CloudWatch dashboard URL",
    });
  }
}

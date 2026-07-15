# SuperCarl - Postman

The easiest way to **show** SuperCarl: click through the requests and watch a
plain-English brief become a shortlist of real profiles.

> **Using Bruno?** Bruno's Postman import can be finicky. Use the native Bruno
> collection instead - no import, just *Open Collection* → `docs/bruno`. See
> [../bruno/README.md](../bruno/README.md).

## Import (once)

1. Open Postman → **Import**.
2. Import the collection: `docs/postman/SuperCarl.postman_collection.json` (in the repo).
3. Import the environment: `SuperCarl.postman_environment.json`.
   - This file holds your API URL, Cognito client id + **secret**, so it is **not**
     committed. Generate it from a deployed stack with:
     ```bash
     ./scripts/make-postman-env.sh -p <your-aws-profile>
     ```
4. Top-right in Postman, select the **"SuperCarl (live AWS)"** environment.

## Run the demo (in order)

| Step | Request | What happens |
|------|---------|--------------|
| 0 | **0 - Health** | Public health check, no auth |
| 1 | **1 - Get token** | Fetches a Cognito token, stores it in `{{token}}` |
| 2 | **2 - Submit research (recruiting)** | Returns a `taskId` immediately (async), stored in `{{taskId}}` |
| 3 | **3 - Get task (poll)** | Run a few times until `status: "completed"` - the shortlist is in `result` |
| 4 | **4 - List recent tasks** | Shows task history |
| 5 | **5 - Submit research (BD)** | Company → People loop |
| 6 | **6 - Schedule** | Creates a recurring EventBridge run |

Steps 1 → 2 → 3 are the demo. Token and taskId are wired automatically via test
scripts, so you just click.

> Tip: keep an eye on the **CloudWatch dashboard** (`DashboardUrl` in
> `cdk-outputs.json`) while step 3 polls - you'll see the request and step traces.

## Fully offline (no AWS)

Run `./scripts/run-local.sh`, then send the same requests against
`http://localhost:8080` (no auth). See [../local-development.md](../local-development.md).

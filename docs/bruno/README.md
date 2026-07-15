# SuperCarl - Bruno

A native [Bruno](https://www.usebruno.com/) collection - no import needed, just
open the folder.

## Open

1. In Bruno: **Open Collection** → select this folder (`docs/bruno`).
2. Make sure the environment exists with your real values:
   ```bash
   ./scripts/make-postman-env.sh -p <your-aws-profile>
   ```
   This writes `docs/bruno/environments/live-aws.bru` (gitignored - it holds the
   Cognito client secret). A committed `live-aws.bru.example` shows the format.
3. Top-right in Bruno, select the **live-aws** environment.

## Run the demo (in order)

1. **1 - Get token** → stores `{{token}}`
2. **2 - Submit research (recruiting)** → returns a `taskId`, stored in `{{taskId}}`
3. **3 - Get task (poll)** → run a few times until `status: "completed"`

Then **5 - BD** and **6 - Schedule** for the other flows. Token and taskId are
wired automatically via post-response scripts.

> Prefer Postman, or importing? Bruno can also **Import → Postman Collection**
> using `../postman/SuperCarl.postman_collection.json`, but opening this native
> folder is the most reliable.

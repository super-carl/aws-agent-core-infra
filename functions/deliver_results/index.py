"""
Action Group executor: deliver_results

Renders the shortlist into channel-specific templates and routes it to SES email
and/or a Slack/Teams webhook. Writes the artifact to S3 for retention.
"""
import json
import os
import logging
from datetime import datetime, timezone
from urllib import request as urlrequest

import boto3

from supercarl_client import error_response, ok_response

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("REGION", "us-east-1")
ARTIFACT_BUCKET = os.environ.get("ARTIFACT_BUCKET", "")
SLACK_WEBHOOK_SECRET_ARN = os.environ.get("SLACK_WEBHOOK_SECRET_ARN", "")
SES_SENDER = os.environ.get("SES_SENDER", "")  # set post-deploy to a verified SES identity
SES_RECIPIENT = os.environ.get("SES_RECIPIENT", "")
TASK_TABLE = os.environ.get("TASK_TABLE", "")

_table = boto3.resource("dynamodb", region_name=REGION).Table(TASK_TABLE) if TASK_TABLE else None


def _existing_count(task_id: str) -> int:
    """Return the count of an already-delivered shortlist for this task, or -1 if
    none. Used so a later, richer delivery can supersede an earlier empty one
    (concurrent agent runs) instead of being discarded."""
    if not _table:
        return -1
    try:
        item = _table.get_item(Key={"PK": f"TASK#{task_id}", "SK": "RESULT"}).get("Item")
        if not item:
            return -1
        c = item.get("count")
        return int(c) if c is not None else 0
    except Exception:  # noqa: BLE001
        return -1


def _persist_result(task_id: str, shortlist: dict, delivered, channels):
    """First delivery is authoritative: write RESULT and mark the task completed,
    so the task finishes even if the agent keeps talking afterwards."""
    if not _table:
        return
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    try:
        _table.put_item(Item={
            "PK": f"TASK#{task_id}", "SK": "RESULT",
            "shortlist": shortlist, "count": shortlist.get("count"),
            "delivered_to": delivered, "channels": channels, "deliveredAt": now,
        })
        _table.update_item(
            Key={"PK": f"TASK#{task_id}", "SK": "META"},
            UpdateExpression="SET #s = :s, #u = :u",
            ExpressionAttributeNames={"#s": "status", "#u": "updatedAt"},
            ExpressionAttributeValues={":s": "completed", ":u": now},
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"persist result failed: {e}")


def _slack_webhook_url() -> str:
    if not SLACK_WEBHOOK_SECRET_ARN:
        return ""
    sm = boto3.client("secretsmanager", region_name=REGION)
    try:
        secret = sm.get_secret_value(SecretId=SLACK_WEBHOOK_SECRET_ARN)["SecretString"]
        return json.loads(secret).get("webhook_url", "")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"could not read slack webhook secret: {e}")
        return ""


ALLOWED_RESULT_KEYS = {"profile_id", "name", "title", "company", "location", "match_reason", "source"}
VALID_USE_CASES = {"recruiting", "bd"}


def _ground(shortlist: dict) -> dict:
    """Automated-reasoning / grounding pass: enforce that the shortlist only
    contains fields the SuperCarl API can produce, every row is sourced, and
    rows without an identity are dropped. Defence-in-depth on top of the agent's
    grounding rules (hallucination mitigation)."""
    # Tolerate shape variance from the model: a bare list of rows, or rows under
    # a differently-named container.
    if isinstance(shortlist, list):
        shortlist = {"results": shortlist}
    if not isinstance(shortlist, dict):
        return {"results": [], "count": 0}
    rows = shortlist.get("results")
    if not isinstance(rows, list):
        for k in ("candidates", "profiles", "people", "shortlist", "matches"):
            v = shortlist.get(k)
            if isinstance(v, list):
                rows = v
                break
            if isinstance(v, dict) and isinstance(v.get("results"), list):
                rows = v["results"]
                break
        if not isinstance(rows, list):
            rows = []
    clean = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        row = {k: r.get(k) for k in ALLOWED_RESULT_KEYS if r.get(k) not in (None, "")}
        # An identity-less row cannot be grounded in an API result.
        if not (row.get("name") or row.get("profile_id")):
            continue
        row["source"] = "supercarl_api"
        clean.append(row)
    shortlist["results"] = clean
    shortlist["count"] = len(clean)
    if shortlist.get("use_case") not in VALID_USE_CASES:
        shortlist["use_case"] = "recruiting"
    return shortlist


def _esc(s) -> str:
    """Minimal HTML escaping."""
    return (
        str(s or "")
        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _render_text(shortlist: dict) -> str:
    rows = shortlist.get("results", [])
    lines = [
        f"SuperCarl shortlist - {shortlist.get('use_case', 'research')}",
        f"Brief: {shortlist.get('query', '')}",
        f"Count: {shortlist.get('count', len(rows))}",
        "",
    ]
    for i, r in enumerate(rows, 1):
        lines.append(
            f"{i}. {r.get('name', '?')} - {r.get('title', '')} @ {r.get('company', '')} "
            f"({r.get('location', '')})\n   {r.get('match_reason', '')}"
        )
    return "\n".join(lines)


def _render_html(shortlist: dict) -> str:
    rows = shortlist.get("results", [])
    use_case = _esc(shortlist.get("use_case", "research"))
    query = _esc(shortlist.get("query", ""))
    count = shortlist.get("count", len(rows))
    cards = []
    for i, r in enumerate(rows, 1):
        cards.append(
            f"""<tr>
              <td style="padding:12px 16px;border-bottom:1px solid #eef0f2;">
                <div style="font-weight:600;color:#0b1f3a;">{i}. {_esc(r.get('name','?'))}</div>
                <div style="color:#5a6673;font-size:13px;">{_esc(r.get('title',''))} &middot; {_esc(r.get('company',''))} &middot; {_esc(r.get('location',''))}</div>
                <div style="color:#16202b;font-size:13px;margin-top:4px;">{_esc(r.get('match_reason',''))}</div>
              </td>
            </tr>"""
        )
    return f"""<!doctype html><html><body style="margin:0;background:#f4f6f8;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f8;padding:24px 0;">
        <tr><td align="center">
          <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="background:#fff;border-radius:8px;overflow:hidden;">
            <tr><td style="background:#0b1f3a;padding:20px 16px;">
              <div style="color:#fff;font-size:20px;font-weight:700;">SuperCarl shortlist</div>
              <div style="color:#1fa29a;font-size:13px;">{use_case} &middot; {count} profiles</div>
            </td></tr>
            <tr><td style="padding:14px 16px;color:#5a6673;font-size:13px;">Brief: {query}</td></tr>
            {''.join(cards)}
          </table>
        </td></tr>
      </table>
    </body></html>"""


def _render_slack_blocks(shortlist: dict) -> dict:
    rows = shortlist.get("results", [])
    use_case = shortlist.get("use_case", "research")
    count = shortlist.get("count", len(rows))
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"SuperCarl shortlist — {use_case} ({count})"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"*Brief:* {shortlist.get('query','')}"}]},
        {"type": "divider"},
    ]
    for i, r in enumerate(rows[:25], 1):  # Slack caps blocks; keep top 25
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (f"*{i}. {r.get('name','?')}*  _{r.get('title','')}_\n"
                         f"{r.get('company','')} · {r.get('location','')}\n{r.get('match_reason','')}"),
            },
        })
    return {"blocks": blocks, "text": f"SuperCarl shortlist — {use_case} ({count} profiles)"}


def _deliver_slack(shortlist: dict) -> bool:
    url = _slack_webhook_url()
    if not url:
        logger.info("slack webhook not configured - skipping")
        return False
    payload = _render_slack_blocks(shortlist)
    req = urlrequest.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception as e:  # noqa: BLE001
        logger.warning(f"slack delivery failed: {e}")
        return False


def _deliver_ses(subject: str, text: str, html: str) -> bool:
    if not (SES_SENDER and SES_RECIPIENT):
        logger.info("SES sender/recipient not configured - skipping")
        return False
    ses = boto3.client("ses", region_name=REGION)
    try:
        ses.send_email(
            Source=SES_SENDER,
            Destination={"ToAddresses": [SES_RECIPIENT]},
            Message={
                "Subject": {"Data": subject},
                "Body": {"Text": {"Data": text}, "Html": {"Data": html}},
            },
        )
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning(f"SES delivery failed: {e}")
        return False


def lambda_handler(event, context):
    event = event or {}
    task_id = event.get("task_id", "").strip()
    shortlist = event.get("shortlist") or {}
    channels = event.get("channels") or ["ses"]
    if not task_id:
        return error_response(400, "task_id is required")
    if isinstance(shortlist, str):
        try:
            shortlist = json.loads(shortlist)
        except json.JSONDecodeError:
            return error_response(400, "shortlist must be JSON")

    # Grounding pass before anything leaves the system.
    shortlist = _ground(shortlist)
    new_count = shortlist.get("count", 0)

    # Idempotency (richest wins): if this task already has a shortlist with at
    # least as many rows, this is a duplicate/lesser delivery — tell the agent to
    # stop without downgrading. A later, richer shortlist (e.g. a concurrent run
    # that found more contacts) still supersedes an earlier empty one.
    prev = _existing_count(task_id)
    if prev >= new_count and prev >= 0:
        return ok_response({
            "task_id": task_id, "status": "already_delivered",
            "message": "Already delivered. Stop and return the final shortlist.",
        })

    text = _render_text(shortlist)
    html = _render_html(shortlist)
    subject = f"SuperCarl shortlist - {shortlist.get('use_case', 'research')} ({task_id})"
    delivered = []

    if "slack" in channels and _deliver_slack(shortlist):
        delivered.append("slack")
    if "ses" in channels and _deliver_ses(subject, text, html):
        delivered.append("ses")

    # Always persist the artifact to S3 for retention/audit. The artifact is the
    # canonical deliverable, so its success makes delivery succeed even when no
    # email/Slack channel is configured.
    artifact = None
    if ARTIFACT_BUCKET:
        try:
            s3 = boto3.client("s3", region_name=REGION)
            key = f"shortlists/{task_id}.json"
            s3.put_object(
                Bucket=ARTIFACT_BUCKET, Key=key,
                Body=json.dumps(shortlist, indent=2).encode("utf-8"),
                ContentType="application/json",
            )
            artifact = f"s3://{ARTIFACT_BUCKET}/{key}"
            delivered.append("s3")
            logger.info(f"artifact written: {artifact}")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"S3 artifact write failed: {e}")

    # First delivery is authoritative — persist RESULT + mark the task completed.
    _persist_result(task_id, shortlist, delivered, channels)

    # A definitive success signal so the agent stops after one delivery (an empty
    # email/Slack list is NOT a failure — the shortlist is always retained).
    return ok_response({
        "task_id": task_id,
        "status": "delivered",
        "delivered_to": delivered,
        "count": shortlist.get("count"),
        "artifact": artifact,
        "deliveredAt": datetime.now(timezone.utc).isoformat(),
        "message": "Delivery complete. Do not call deliver_results again; return the final shortlist.",
    })

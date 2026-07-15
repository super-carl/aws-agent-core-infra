"""
Action Group executor: profile_lookup

Resolves/enriches a single profile by id via the SuperCarl Profile Lookup API.
"""
import logging

from supercarl_client import call_supercarl, mock_profile, error_response, ok_response

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    profile_id = (event or {}).get("profile_id", "").strip()
    if not profile_id:
        return error_response(400, "profile_id is required")
    if len(profile_id) > 128 or any(c in profile_id for c in "/?#& "):
        return error_response(400, "invalid profile_id")

    logger.info(f"profile_lookup: profile_id={profile_id!r}")
    try:
        data = call_supercarl(
            path=f"/v1/profiles/{profile_id}",
            method="GET",
            mock_fn=lambda: mock_profile(profile_id),
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"profile_lookup error: {e}")
        return error_response(502, f"SuperCarl API error: {e}")

    shaped = {
        "profile_id": data.get("profile_id") or profile_id,
        "name": data.get("name"),
        "title": data.get("title"),
        "company": data.get("company"),
        "location": data.get("location"),
        "summary": data.get("summary"),
        "skills": data.get("skills", []),
        "match_reason": data.get("match_reason"),
        "source": "supercarl_api",
    }
    return ok_response(shaped)

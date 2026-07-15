"""
Action Group executor: people_search

Invoked by the SuperCarl agent as a tool. Calls the SuperCarl People Search API
(auth via Secrets Manager), validates input, handles rate limits, and shapes the
response to only the fields the agent should see.

Until the real SuperCarl API ships (end of Week 1) this falls back to the mock
contract when SUPERCARL_API_BASE_URL points at the placeholder host.
"""
import json
import os
import logging

from supercarl_client import call_supercarl, mock_people, error_response, ok_response

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    event = event or {}
    query = (event.get("query") or "").strip()
    if not query:
        return error_response(400, "query is required")
    if len(query) > 1000:
        return error_response(400, "query too long (max 1000 chars)")
    limit = max(1, min(int(event.get("limit", 25) or 25), 50))

    logger.info(f"people_search: query={query!r} limit={limit}")
    try:
        data = call_supercarl(
            path="/v1/people/search",
            method="POST",
            body={"query": query, "limit": limit},
            mock_fn=lambda: mock_people(query),
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"people_search error: {e}")
        return error_response(502, f"SuperCarl API error: {e}")

    # Structured shaping — only fields the agent should see.
    profiles = [
        {
            "profile_id": p.get("profile_id") or p.get("id"),
            "name": p.get("name"),
            "title": p.get("title"),
            "company": p.get("company"),
            "location": p.get("location"),
            "match_reason": p.get("match_reason"),
            "source": "supercarl_api",
        }
        for p in data.get("results", [])
    ]
    return ok_response({"results": profiles, "count": len(profiles)})

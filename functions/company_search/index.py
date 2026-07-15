"""
Action Group executor: company_search

Finds organizations for BD targeting via the SuperCarl Company Search API.
"""
import logging

from supercarl_client import call_supercarl, mock_companies, error_response, ok_response

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

    logger.info(f"company_search: query={query!r} limit={limit}")
    try:
        data = call_supercarl(
            path="/v1/companies/search",
            method="POST",
            body={"query": query, "limit": limit},
            mock_fn=lambda: mock_companies(query),
        )
    except Exception as e:  # noqa: BLE001
        logger.error(f"company_search error: {e}")
        return error_response(502, f"SuperCarl API error: {e}")

    companies = [
        {
            "company_id": c.get("company_id") or c.get("id"),
            "name": c.get("name"),
            "industry": c.get("industry"),
            "size": c.get("size"),
            "location": c.get("location"),
            "match_reason": c.get("match_reason"),
            "source": "supercarl_api",
        }
        for c in data.get("results", [])
    ]
    return ok_response({"results": companies, "count": len(companies)})

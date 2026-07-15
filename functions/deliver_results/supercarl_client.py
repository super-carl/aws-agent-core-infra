"""
Shared SuperCarl API client for Action Group executor Lambdas.

Responsibilities:
- Fetch the SuperCarl API key from Secrets Manager (cached per container).
- Call the SuperCarl API with auth, timeout, and basic rate-limit handling.
- Fall back to the deterministic mock contract while the real API is not yet
  available (Week 1 dependency). This keeps the whole stack deployable and
  end-to-end testable against the documented contract in /mock.

NOTE: this file is duplicated into each executor's directory because CDK bundles
each Lambda asset independently. Keep the copies in sync (scripts/sync-client.sh).
"""
import json
import os
import time
import logging
import hashlib
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

logger = logging.getLogger()

REGION = os.environ.get("REGION", "us-east-1")
BASE_URL = os.environ.get("SUPERCARL_API_BASE_URL", "https://mock.supercarl.local")
API_KEY_SECRET_ARN = os.environ.get("API_KEY_SECRET_ARN", "")

_api_key_cache = None


def _is_mock() -> bool:
    return "mock.supercarl.local" in BASE_URL or not BASE_URL


def _get_api_key() -> str:
    global _api_key_cache
    if _api_key_cache is not None:
        return _api_key_cache
    # Env fallback (handy for local testing against the mock server).
    env_key = os.environ.get("SUPERCARL_API_KEY")
    if env_key:
        _api_key_cache = env_key
        return env_key
    if not API_KEY_SECRET_ARN:
        _api_key_cache = ""
        return ""
    import boto3

    sm = boto3.client("secretsmanager", region_name=REGION)
    secret = sm.get_secret_value(SecretId=API_KEY_SECRET_ARN)["SecretString"]
    try:
        _api_key_cache = json.loads(secret).get("api_key", secret)
    except json.JSONDecodeError:
        _api_key_cache = secret
    return _api_key_cache


def call_supercarl(path: str, method: str = "GET", body: dict | None = None, mock_fn=None) -> dict:
    """Call the SuperCarl API. Falls back to mock_fn() when pointed at the mock host."""
    if _is_mock():
        if mock_fn is None:
            raise RuntimeError("No mock available and SuperCarl API base URL is the mock placeholder")
        logger.info(f"[mock] {method} {path}")
        return mock_fn()

    api_key = _get_api_key()
    if not api_key or api_key == "your-supercarl-api-key-here":
        raise RuntimeError("SuperCarl API key not configured (update the supercarl/api-key secret)")

    url = BASE_URL.rstrip("/") + path
    data = json.dumps(body).encode("utf-8") if body is not None else None

    # Retry on 429 / transient network errors with exponential backoff.
    max_attempts = 3
    last_err = None
    for attempt in range(max_attempts):
        req = urlrequest.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {api_key}")
        req.add_header("Content-Type", "application/json")
        try:
            with urlrequest.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except HTTPError as e:
            if e.code == 429 and attempt < max_attempts - 1:
                backoff = 0.5 * (2 ** attempt)
                logger.warning(f"429 from SuperCarl API, retrying in {backoff}s (attempt {attempt + 1})")
                time.sleep(backoff)
                last_err = RuntimeError("rate limited by SuperCarl API (429)")
                continue
            if e.code == 429:
                raise RuntimeError("rate limited by SuperCarl API (429)")
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8')[:200]}")
        except URLError as e:
            if attempt < max_attempts - 1:
                backoff = 0.5 * (2 ** attempt)
                logger.warning(f"network error {e.reason}, retrying in {backoff}s")
                time.sleep(backoff)
                last_err = RuntimeError(f"network error: {e.reason}")
                continue
            raise RuntimeError(f"network error: {e.reason}")
    raise last_err or RuntimeError("SuperCarl API call failed")


# ─── Deterministic mock data (matches /mock/supercarl-openapi.yaml) ──────────
def _seed(*parts: str) -> int:
    return int(hashlib.sha256("|".join(parts).encode()).hexdigest(), 16)


def mock_people(query: str, count: int = 12) -> dict:
    titles = ["Senior Software Engineer", "Staff Engineer", "Engineering Manager",
              "Head of Talent", "VP Engineering", "Recruiting Lead"]
    companies = ["Northwind Labs", "Acme Cloud", "Helix Systems", "Vertex AI", "Orbit Data"]
    locations = ["Austin, TX", "Remote (US)", "New York, NY", "Seattle, WA", "Denver, CO"]
    results = []
    for i in range(count):
        s = _seed(query, str(i))
        results.append({
            "profile_id": f"p_{s % 10_000_000:07d}",
            "name": f"Candidate {chr(65 + (i % 26))}{i}",
            "title": titles[s % len(titles)],
            "company": companies[s % len(companies)],
            "location": locations[s % len(locations)],
            "match_reason": f"Matches brief: {query[:60]}",
        })
    return {"results": results, "count": count}


def mock_companies(query: str, count: int = 8) -> dict:
    industries = ["SaaS", "Fintech", "Healthtech", "Logistics", "AI Infrastructure"]
    sizes = ["11-50", "51-200", "201-500", "501-1000"]
    results = []
    for i in range(count):
        s = _seed(query, "co", str(i))
        results.append({
            "company_id": f"c_{s % 10_000_000:07d}",
            "name": f"{['North','Helix','Vertex','Orbit','Acme'][s % 5]} {['Labs','Systems','AI','Data','Cloud'][i % 5]}",
            "industry": industries[s % len(industries)],
            "size": sizes[s % len(sizes)],
            "location": ["Austin, TX", "Remote", "NYC", "SF"][s % 4],
            "match_reason": f"Matches BD brief: {query[:60]}",
        })
    return {"results": results, "count": count}


def mock_profile(profile_id: str) -> dict:
    s = _seed(profile_id)
    return {
        "profile_id": profile_id,
        "name": f"Candidate {chr(65 + s % 26)}",
        "title": "Senior Software Engineer",
        "company": "Northwind Labs",
        "location": "Austin, TX",
        "summary": "Backend engineer with cloud + distributed systems experience.",
        "skills": ["Python", "AWS", "Distributed Systems"],
        "match_reason": "Enriched profile from SuperCarl API",
    }


# ─── API-Gateway-shaped responses ────────────────────────────────────────────
def ok_response(body: dict) -> dict:
    return {"statusCode": 200, "body": json.dumps(body)}


def error_response(code: int, message: str) -> dict:
    return {"statusCode": code, "body": json.dumps({"error": message})}

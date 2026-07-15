#!/usr/bin/env bash
# Run SuperCarl locally with no AWS, no credentials, no Docker required.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "Starting SuperCarl local API (mode=local, no AWS)..."
echo "  Health:   curl -s localhost:8080/v1/health"
echo "  Submit:   curl -s -X POST localhost:8080/v1/research \\"
echo "              -d '{\"prompt\":\"Senior backend engineers in Austin\",\"useCase\":\"recruiting\"}'"
echo "  BD loop:  ... -d '{\"prompt\":\"fintech companies in NYC\",\"useCase\":\"bd\"}'"
echo ""
exec python3 "$ROOT/local/local_server.py"

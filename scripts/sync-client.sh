#!/usr/bin/env bash
# Keep the shared SuperCarl client in sync across all Action Group executors.
# CDK bundles each Lambda asset independently, so supercarl_client.py is copied
# into each function dir. people_search holds the canonical copy.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/functions/people_search/supercarl_client.py"
for d in profile_lookup company_search deliver_results; do
  cp "$SRC" "$ROOT/functions/$d/supercarl_client.py"
  echo "synced -> functions/$d/supercarl_client.py"
done

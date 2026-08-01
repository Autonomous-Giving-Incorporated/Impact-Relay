#!/usr/bin/env bash
# Apply an authorized Every.org aggregate_summary into data/impact-state.json.
# Fails unless raisedSource becomes processor_aggregate (OBSERVED).
#
# Usage:
#   ./scripts/apply_live_every_org_aggregate.sh ~/private/every_org_live.json
#   ./scripts/apply_live_every_org_aggregate.sh --dry-run ~/private/every_org_live.json
#   IMPACT_RELAY_EVERY_ORG_AGGREGATE=~/private/every_org_live.json ./scripts/apply_live_every_org_aggregate.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DRY_RUN=0
if [[ "${1:-}" == "--dry-run" || "${1:-}" == "-n" ]]; then
  DRY_RUN=1
  shift
fi

AGG="${1:-${IMPACT_RELAY_EVERY_ORG_AGGREGATE:-}}"
if [[ -z "${AGG}" ]]; then
  echo "Usage: $0 [--dry-run] /path/to/every_org_live.json" >&2
  echo "Or set IMPACT_RELAY_EVERY_ORG_AGGREGATE." >&2
  echo "Copy fixtures/templates/every_org_live_aggregate.template.json and fill authorized totals." >&2
  exit 1
fi
if [[ ! -f "${AGG}" ]]; then
  echo "Aggregate file not found: ${AGG}" >&2
  exit 1
fi

# Refuse obvious pilot/fixture paths.
if [[ "${AGG}" == *fixture* ]] || [[ "${AGG}" == *template* ]]; then
  echo "Refusing path that looks like a fixture/template: ${AGG}" >&2
  echo "Live OBSERVED publish requires an operator-authorized private file." >&2
  exit 1
fi

# Always validate first (no write).
python -m impact_relay --validate-every-org-aggregate "${AGG}"

if [[ "${DRY_RUN}" -eq 1 ]]; then
  echo "OK (dry-run): aggregate is OBSERVED-ready. No files written."
  exit 0
fi

python -m impact_relay \
  --every-org-aggregate "${AGG}" \
  --require-observed \
  --write-impact-state data/impact-state.json

echo "OK: impact-state updated with processor_aggregate / OBSERVED from ${AGG}"
echo "Next: review git diff data/impact-state.json, then PR (aggregate numbers only)."

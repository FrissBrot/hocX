#!/usr/bin/env bash
set -euo pipefail

# Records that the exact candidate tag passed the checks on the bound test host.
# GitHub's deployment API becomes the promotion workflow's machine-readable gate.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/lib/env.sh
source "$REPO_DIR/scripts/lib/env.sh"
# shellcheck source=scripts/lib/github.sh
source "$REPO_DIR/scripts/lib/github.sh"

require_host_environment test

if [ "$EUID" -eq 0 ]; then
  echo "Testnachweise als root sind gesperrt. Bitte hocx-deploy verwenden." >&2
  exit 1
fi

for command in gh jq mktemp; do
  command -v "$command" > /dev/null 2>&1 || {
    echo "Erforderliches Kommando fehlt: $command" >&2
    exit 1
  }
done
ENV_FILE="$REPO_DIR/.env"
load_env_file "$ENV_FILE"
: "${HOCX_VERSION:?HOCX_VERSION fehlt in $ENV_FILE}"
: "${TRAEFIK_DOMAIN:?TRAEFIK_DOMAIN fehlt in $ENV_FILE}"
: "${GHCR_NAMESPACE:?GHCR_NAMESPACE fehlt in $ENV_FILE}"
ensure_github_auth

if [[ ! "$HOCX_VERSION" =~ ^test-[0-9]{8}-([0-9a-f]{7,40})-r[0-9]+$ ]]; then
  echo "Kein gueltiger Candidate-Tag: $HOCX_VERSION" >&2
  exit 1
fi
CANDIDATE_SHA="${BASH_REMATCH[1]}"
FULL_CANDIDATE_SHA="$(gh api "repos/FrissBrot/hocX/commits/${CANDIDATE_SHA}" --jq '.sha')"
[[ "$FULL_CANDIDATE_SHA" = "$CANDIDATE_SHA"* ]] || {
  echo "Candidate-Commit $CANDIDATE_SHA konnte nicht eindeutig aufgeloest werden." >&2
  exit 1
}

request_file="$(mktemp /tmp/hocx-tested-request.XXXXXX)"
response_file="$(mktemp /tmp/hocx-tested-response.XXXXXX)"
trap 'rm -f "$request_file" "$response_file"' EXIT

jq -n \
  --arg ref "$FULL_CANDIDATE_SHA" \
  --arg tag "$HOCX_VERSION" \
  --arg host "$(hostname -f 2>/dev/null || hostname)" \
  '{ref:$ref, task:"hocx-candidate", environment:"test", auto_merge:false,
    required_contexts:[], transient_environment:true, production_environment:false,
    description:"Candidate passed hocX release verification",
    payload:{candidate_tag:$tag, verified_by:"scripts/verify_release.sh", test_host:$host}}' \
  > "$request_file"

gh api --method POST repos/FrissBrot/hocX/deployments \
  --input "$request_file" > "$response_file"
DEPLOYMENT_ID="$(jq -r '.id' "$response_file")"
[[ "$DEPLOYMENT_ID" =~ ^[0-9]+$ ]] || {
  echo "GitHub hat keine gueltige Deployment-ID geliefert." >&2
  exit 1
}

jq -n \
  --arg url "https://${TRAEFIK_DOMAIN}/login" \
  '{state:"success", environment:"test", environment_url:$url,
    auto_inactive:false, description:"All hocX release checks passed"}' \
  > "$request_file"
gh api --method POST "repos/FrissBrot/hocX/deployments/${DEPLOYMENT_ID}/statuses" \
  --input "$request_file" > /dev/null

echo "==> [test] GitHub-Testnachweis fuer $HOCX_VERSION gespeichert (Deployment $DEPLOYMENT_ID)"

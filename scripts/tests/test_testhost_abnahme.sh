#!/usr/bin/env bash
set -euo pipefail

# scripts/testhost/abnahme.sh gegen ein Fake-`docker` im PATH: TH-01 vergleicht das laufende
# Backend-Image (deploy.sh startet per Digest) mit HOCX_BACKEND_IMAGE aus
# .releases/<HOCX_VERSION>.env, und Werte aus .env werden mit einfachen wie doppelten
# Anführungszeichen richtig gelesen (Fund auf dem Test-Host, 2026-11-09).

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR="$(mktemp -d)"
trap 'rm -rf "$TEST_DIR"' EXIT

DIGEST="ghcr.io/example/hocx-backend@sha256:$(printf '%064d' 1)"
OTHER="ghcr.io/example/hocx-backend@sha256:$(printf '%064d' 2)"

mkdir -p "$TEST_DIR/bin" "$TEST_DIR/host/.releases"
cat > "$TEST_DIR/bin/docker" <<FAKE
#!/usr/bin/env bash
case "\$*" in
  "ps -q "*"service=db"*) echo db-id ;;
  "ps -q "*"service=backend"*) echo backend-id ;;
  "ps --filter"*) echo hocx-test-backend-1 ;;
  "inspect backend-id --format {{.Config.Image}}") echo "\$FAKE_IMAGE" ;;
  "inspect hocx-test-backend-1 "*) echo "healthy 0 false" ;;
  run*) printf '%s\n' "\$TH_BASE" > "$TEST_DIR/th_base" ;;
  *) ;;
esac
exit 0
FAKE
chmod +x "$TEST_DIR/bin/docker"
export PATH="$TEST_DIR/bin:$PATH"
export HOCX_HOST_MARKER_FILE="$TEST_DIR/no-marker"
export TH_ENV_FILE="$TEST_DIR/host/.env" TH_CREDENTIALS="$TEST_DIR/none.env"
unset TH_BASE

cat > "$TEST_DIR/host/.env" <<'ENV'
TRAEFIK_DOMAIN='app.test.example'
HOCX_VERSION="test-20261109-abc1234-r52"
ENV
printf "HOCX_VERSION='test-20261109-abc1234-r52'\nHOCX_BACKEND_IMAGE='%s'\n" "$DIGEST" \
  > "$TEST_DIR/host/.releases/test-20261109-abc1234-r52.env"
chmod 600 "$TEST_DIR/host/.env" "$TEST_DIR/host/.releases/"*.env

th01() {
  local out="$TEST_DIR/out-$1"
  TH_OUT="$out" FAKE_IMAGE="$2" "$REPO_DIR/scripts/testhost/abnahme.sh" server > /dev/null 2>&1 || true
  python3 -c 'import json,sys; r=[json.loads(l) for l in open(sys.argv[1])]; t=[x for x in r if x["id"]=="TH-01"][0]; print(t["status"], t["summary"])' \
    "$out/results.jsonl"
}

# Gleicher Digest wie im Manifest: PASS, Meldung nennt Tag und Digest.
RESULT="$(th01 same "$DIGEST")"
[[ "$RESULT" == "PASS "*"test-20261109-abc1234-r52"*"sha256:"* ]] || { echo "erwartet PASS: $RESULT" >&2; exit 1; }

# Anderer Digest: FAIL mit beiden Angaben.
RESULT="$(th01 other "$OTHER")"
[[ "$RESULT" == "FAIL "*"$OTHER"*"test-20261109-abc1234-r52"* ]] || { echo "erwartet FAIL: $RESULT" >&2; exit 1; }

# Manifest fehlt: FAIL mit klarer Meldung statt Vergleich mit dem Hash.
mv "$TEST_DIR/host/.releases/test-20261109-abc1234-r52.env" "$TEST_DIR/manifest.bak"
RESULT="$(th01 missing "$DIGEST")"
[[ "$RESULT" == "FAIL Release-Manifest"*"fehlt"* ]] || { echo "erwartet Manifest-FAIL: $RESULT" >&2; exit 1; }
mv "$TEST_DIR/manifest.bak" "$TEST_DIR/host/.releases/test-20261109-abc1234-r52.env"

# Einfache Anführungszeichen in .env: TH_BASE ohne Quotes.
TH_OUT="$TEST_DIR/out-browser" "$REPO_DIR/scripts/testhost/abnahme.sh" browser > /dev/null 2>&1 || true
test "$(cat "$TEST_DIR/th_base")" = "https://app.test.example"

# Prod-Host: Abbruch, bevor irgendetwas läuft.
printf 'prod\n' > "$TEST_DIR/prod-marker"
if HOCX_HOST_MARKER_FILE="$TEST_DIR/prod-marker" TH_OUT="$TEST_DIR/out-prod" \
  "$REPO_DIR/scripts/testhost/abnahme.sh" server > /dev/null 2>&1; then
  echo "Abnahme lief auf einem Prod-Host" >&2
  exit 1
fi

echo "testhost abnahme tests: ok"

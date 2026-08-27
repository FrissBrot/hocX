#!/usr/bin/env bash
set -euo pipefail

# Kontrolliertes Update des Deploy-Checkouts. Absichtlich getrennt von deploy.sh:
# ein normaler Deploy veraendert seinen eigenen Code niemals stillschweigend.
# Usage: scripts/update_deploy_code.sh [--deploy]

if [ "${HOCX_UPDATE_HELPER_COPY:-0}" != 1 ]; then
  ORIGINAL_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  HELPER_COPY="$(mktemp /tmp/hocx-update-deploy.XXXXXX)"
  install -m 700 "$0" "$HELPER_COPY"
  exec env \
    HOCX_UPDATE_HELPER_COPY=1 \
    HOCX_UPDATE_REPO_DIR="$ORIGINAL_REPO_DIR" \
    HOCX_UPDATE_HELPER_PATH="$HELPER_COPY" \
    "$HELPER_COPY" "$@"
fi

REPO_DIR="${HOCX_UPDATE_REPO_DIR:?Interner Repository-Pfad fehlt}"
HELPER_PATH="${HOCX_UPDATE_HELPER_PATH:?Interner Helper-Pfad fehlt}"
trap 'rm -f "$HELPER_PATH"' EXIT

# shellcheck source=scripts/lib/env.sh
source "$REPO_DIR/scripts/lib/env.sh"
# shellcheck source=scripts/lib/cosign.sh
source "$REPO_DIR/scripts/lib/cosign.sh"
# shellcheck source=scripts/lib/github.sh
source "$REPO_DIR/scripts/lib/github.sh"

DEPLOY_AFTER_UPDATE=false
case "${1:-}" in
  "") ;;
  --deploy)
    DEPLOY_AFTER_UPDATE=true
    ;;
  *)
    echo "Usage: scripts/update_deploy_code.sh [--deploy]" >&2
    exit 1
    ;;
esac

if [ "$EUID" -eq 0 ]; then
  echo "Deploy-Code-Updates als root sind gesperrt. Bitte hocx-deploy verwenden." >&2
  exit 1
fi

HOST_ENVIRONMENT="$(read_host_environment)"

for command in git flock gh docker sha256sum tar; do
  command -v "$command" > /dev/null 2>&1 || {
    echo "Erforderliches Kommando fehlt: $command" >&2
    exit 1
  }
done

exec 9> "$REPO_DIR/.deploy.lock"
if ! flock -n 9; then
  echo "Ein Deploy oder Deploy-Code-Update laeuft bereits." >&2
  exit 1
fi

cd "$REPO_DIR"
REMOTE_URL="$(git remote get-url origin)"
case "$REMOTE_URL" in
  https://github.com/FrissBrot/hocX.git|git@github.com:FrissBrot/hocX.git|ssh://git@github.com/FrissBrot/hocX.git)
    ;;
  *)
    echo "Nicht erlaubte origin-URL: $REMOTE_URL" >&2
    exit 1
    ;;
esac

if [ "$(git branch --show-current)" != main ]; then
  echo "Deploy-Code darf nur auf dem Branch 'main' aktualisiert werden." >&2
  exit 1
fi
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "Tracked Worktree-Aenderungen vorhanden; Update wird nicht vermischt." >&2
  git status --short --untracked-files=no >&2
  exit 1
fi

echo "==> [$HOST_ENVIRONMENT] Hole freigegebenen Deploy-Code von origin/main"
git fetch --prune origin main

if ! git merge-base --is-ancestor HEAD refs/remotes/origin/main; then
  echo "Lokaler Stand ist kein Vorfahr von origin/main; kein Fast-Forward moeglich." >&2
  exit 1
fi

OLD_COMMIT="$(git rev-parse HEAD)"
NEW_COMMIT="$(git rev-parse refs/remotes/origin/main)"

verify_signed_deploy_code() {
  local run_id proof_dir tree_dir signed_commit identity

  ensure_github_auth
  run_id="$(gh run list \
    --repo FrissBrot/hocX \
    --workflow build-test-images.yml \
    --commit "$NEW_COMMIT" \
    --status success \
    --limit 1 \
    --json databaseId \
    --jq '.[0].databaseId')"
  [ -n "$run_id" ] || {
    echo "Kein erfolgreicher Candidate-Build fuer Commit $NEW_COMMIT gefunden." >&2
    return 1
  }

  proof_dir="$(mktemp -d /tmp/hocx-deploy-proof.XXXXXX)"
  tree_dir="$(mktemp -d /tmp/hocx-deploy-tree.XXXXXX)"
  trap 'rm -rf "$proof_dir" "$tree_dir"' RETURN
  gh run download "$run_id" \
    --repo FrissBrot/hocX \
    --name "deploy-code-${NEW_COMMIT}" \
    --dir "$proof_dir"

  signed_commit="$(tr -d '\r\n' < "$proof_dir/deploy-code.commit")"
  [ "$signed_commit" = "$NEW_COMMIT" ] || {
    echo "Signierter Commit ($signed_commit) stimmt nicht mit origin/main ($NEW_COMMIT) ueberein." >&2
    return 1
  }

  ensure_cosign
  identity='(?i)^https://github.com/FrissBrot/hocX/.github/workflows/build-test-images[.]yml@refs/heads/main$'
  "$COSIGN_BIN" verify-blob "$proof_dir/deploy-code.manifest" \
    --bundle "$proof_dir/deploy-code.bundle" \
    --certificate-identity-regexp "$identity" \
    --certificate-oidc-issuer "https://token.actions.githubusercontent.com" \
    > /dev/null

  git archive "$NEW_COMMIT" | tar -x -C "$tree_dir"
  (cd "$tree_dir" && sha256sum --check "$proof_dir/deploy-code.manifest") > /dev/null
  echo "    Signierter Deploy-Code fuer ${NEW_COMMIT:0:12}: ok"
  rm -rf "$proof_dir" "$tree_dir"
  trap - RETURN
}

echo "==> [$HOST_ENVIRONMENT] Verifiziere freigegebenen Deploy-Code"
verify_signed_deploy_code

if [ "$OLD_COMMIT" = "$NEW_COMMIT" ]; then
  echo "    Deploy-Code ist bereits aktuell: ${OLD_COMMIT:0:12}"
else
  echo "    Aktualisiere ${OLD_COMMIT:0:12} -> ${NEW_COMMIT:0:12}"
  git log --oneline --no-decorate "$OLD_COMMIT..$NEW_COMMIT"
  git merge --ff-only refs/remotes/origin/main
fi

bash -n \
  "$REPO_DIR/scripts/lib/env.sh" \
  "$REPO_DIR/scripts/lib/cosign.sh" \
  "$REPO_DIR/scripts/deploy.sh" \
  "$REPO_DIR/scripts/update_deploy_code.sh"
echo "==> Deploy-Code erfolgreich aktualisiert und geprueft"

if [ "$DEPLOY_AFTER_UPDATE" = true ]; then
  flock -u 9
  rm -f "$HELPER_PATH"
  trap - EXIT
  exec "$REPO_DIR/scripts/deploy.sh" "$HOST_ENVIRONMENT"
fi

echo "Naechster Schritt: $REPO_DIR/scripts/deploy.sh $HOST_ENVIRONMENT"

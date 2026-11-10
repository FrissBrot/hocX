#!/usr/bin/env bash
set -euo pipefail

# Kontrolliertes Update des Deploy-Checkouts auf den neuesten signierten Stand von origin/main
# (Candidate-Build von build-test-images.yml). deploy.sh ruft es ab 1.2.4 vor jedem Deploy selbst
# auf (sichtbar, mit Signaturpruefung; Opt-out HOCX_SKIP_DEPLOY_CODE_UPDATE=1), damit nie ein
# veraltetes deploy.sh ein neues Release ausrollt.
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
# ensure_github_auth (lib/github.sh) erwartet PROJECT_DIR vom Aufrufer, um Tokens
# unter .tools/ abzulegen - siehe gleicher Fix in record_tested_candidate.sh.
PROJECT_DIR="$REPO_DIR"
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
  echo "Host-spezifische Anpassungen gehoeren in $HOCX_LOCAL_COMPOSE_FILE (nicht versioniert)." >&2
  exit 1
fi
# Gehoeren Dateien root (z. B. nach einem `git pull` als root), bricht der Fast-Forward sonst
# mittendrin ab und hinterlaesst einen halb aktualisierten Checkout.
require_repo_owned_by_current_user "$REPO_DIR" || exit 1

echo "==> [$HOST_ENVIRONMENT] Hole freigegebenen Deploy-Code von origin/main"
git fetch --prune origin main

if ! git merge-base --is-ancestor HEAD refs/remotes/origin/main; then
  echo "Lokaler Stand ist kein Vorfahr von origin/main; kein Fast-Forward moeglich." >&2
  exit 1
fi

OLD_COMMIT="$(git rev-parse HEAD)"
NEW_COMMIT="$(git rev-parse refs/remotes/origin/main)"
NEW_RUN_ID=""

# Neuester Commit auf origin/main mit erfolgreichem Candidate-Build. Reine Doku-Commits (z. B.
# Changelog) bekommen keinen eigenen Build; dann gilt der neueste signierte Vorgaenger - er muss
# aber mindestens so neu sein wie der aktuelle Stand (kein Zurueckgehen).
select_signed_commit() {
  local tip="$NEW_COMMIT" run_id sha
  ensure_github_auth
  while IFS=' ' read -r run_id sha; do
    [ -n "$sha" ] || continue
    git cat-file -e "$sha^{commit}" 2> /dev/null || continue
    git merge-base --is-ancestor "$sha" "$tip" || continue
    git merge-base --is-ancestor "$OLD_COMMIT" "$sha" || continue
    NEW_COMMIT="$sha"
    NEW_RUN_ID="$run_id"
    break
  done < <(gh run list \
    --repo FrissBrot/hocX \
    --workflow build-test-images.yml \
    --branch main \
    --status success \
    --limit 50 \
    --json databaseId,headSha \
    --jq '.[] | "\(.databaseId) \(.headSha)"')
  [ -n "$NEW_RUN_ID" ] || {
    echo "Kein erfolgreicher Candidate-Build auf origin/main gefunden, der neuer als ${OLD_COMMIT:0:12} ist." >&2
    return 1
  }
  if [ "$NEW_COMMIT" != "$tip" ]; then
    echo "    origin/main (${tip:0:12}) hat keinen eigenen Candidate-Build; neuester signierter Stand: ${NEW_COMMIT:0:12}"
  fi
}

verify_signed_deploy_code() {
  local run_id="$NEW_RUN_ID" proof_dir tree_dir signed_commit identity

  proof_dir="$(mktemp -d /tmp/hocx-deploy-proof.XXXXXX)"
  tree_dir="$(mktemp -d /tmp/hocx-deploy-tree.XXXXXX)"
  trap 'rm -rf "$proof_dir" "$tree_dir"' RETURN
  gh run download "$run_id" \
    --repo FrissBrot/hocX \
    --name "deploy-code-${NEW_COMMIT}" \
    --dir "$proof_dir"

  signed_commit="$(tr -d '\r\n' < "$proof_dir/deploy-code.commit")"
  [ "$signed_commit" = "$NEW_COMMIT" ] || {
    echo "Signierter Commit ($signed_commit) stimmt nicht mit dem Ziel ($NEW_COMMIT) ueberein." >&2
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
select_signed_commit
verify_signed_deploy_code

if [ "$OLD_COMMIT" = "$NEW_COMMIT" ]; then
  echo "    Deploy-Code ist bereits aktuell: ${OLD_COMMIT:0:12}"
else
  echo "    Aktualisiere ${OLD_COMMIT:0:12} -> ${NEW_COMMIT:0:12}"
  git log --oneline --no-decorate "$OLD_COMMIT..$NEW_COMMIT"
  git merge --ff-only "$NEW_COMMIT"
fi

bash -n \
  "$REPO_DIR/scripts/lib/env.sh" \
  "$REPO_DIR/scripts/lib/env_migrate.sh" \
  "$REPO_DIR/scripts/lib/cosign.sh" \
  "$REPO_DIR/scripts/lib/stack.sh" \
  "$REPO_DIR/scripts/deploy.sh" \
  "$REPO_DIR/scripts/backup_db.sh" \
  "$REPO_DIR/scripts/restore_db.sh" \
  "$REPO_DIR/scripts/run_job.sh" \
  "$REPO_DIR/scripts/storage_controller.sh" \
  "$REPO_DIR/scripts/verify_release.sh" \
  "$REPO_DIR/scripts/update_deploy_code.sh" \
  "$REPO_DIR/scripts/lib/storage_gate.sh"
echo "==> Deploy-Code erfolgreich aktualisiert und geprueft"

if [ "$DEPLOY_AFTER_UPDATE" = true ]; then
  flock -u 9
  rm -f "$HELPER_PATH"
  trap - EXIT
  # Der Code ist eben aktualisiert: deploy.sh soll das nicht noch einmal tun (Schleifenschutz).
  exec env HOCX_DEPLOY_CODE_UPDATED=1 "$REPO_DIR/scripts/deploy.sh" "$HOST_ENVIRONMENT"
fi

# Aufruf aus deploy.sh: das startet sich danach selbst neu, kein Hinweis noetig
[ "${HOCX_DEPLOY_CODE_UPDATE_FROM_DEPLOY:-0}" = 1 ] || echo "Naechster Schritt: $REPO_DIR/scripts/deploy.sh $HOST_ENVIRONMENT"

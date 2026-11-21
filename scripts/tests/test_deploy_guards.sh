#!/usr/bin/env bash
# Deploy-Schutz nach dem 1.5.0-Vorfall (r91 auf dem Test-Host):
# 1. dynamic_config_files_check erlaubt alle versionierten Dateien (maintenance.yml kam mit 1.5.0
#    dazu und liess jedes Deploy scheitern) und host-eigene Dateien nur über TRAEFIK_HOST_DYNAMIC_FILES.
# 2. Nach ausgeführten Migrationen rollt deploy.sh die Images nicht mehr zurück (das alte Release
#    startet gegen die migrierte DB nicht).
set -euo pipefail
cd "$(dirname "$0")/../.."
REPO="$PWD"
fail() { echo "FEHLER: $*" >&2; exit 1; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
git -C "$work" init -q
mkdir -p "$work/infra/traefik/dynamic"
for file in $(git ls-files infra/traefik/dynamic); do cp "$file" "$work/$file"; done
git -C "$work" add -A
git -C "$work" -c user.email=t@example.invalid -c user.name=t commit -qm init
echo "# generiert" > "$work/infra/traefik/dynamic/tenant-domains.yml"
echo "# generiert" > "$work/infra/traefik/dynamic/admin-gate.yml"

check() { REPO_DIR="$work" TRAEFIK_HOST_DYNAMIC_FILES="${1:-}" bash -c "source '$REPO/scripts/lib/traefik_checks.sh'; dynamic_config_files_check" > /dev/null 2>&1; }

check || fail "versionierte + generierte Dateien (inkl. maintenance.yml) werden abgelehnt"
echo "x" > "$work/infra/traefik/dynamic/test-ziti-tls.yml"
check && fail "host-eigene Datei ohne Freigabe akzeptiert"
check "test-ziti-tls.yml" || fail "freigegebene Host-Datei abgelehnt"
check "a.yml, test-ziti-tls.yml" || fail "Komma-Liste nicht verstanden"
check "../escape.yml" && fail "Pfad in TRAEFIK_HOST_DYNAMIC_FILES akzeptiert"
ln -s /etc/hostname "$work/infra/traefik/dynamic/link.yml"
check "test-ziti-tls.yml link.yml" && fail "Symlink als Host-Datei akzeptiert"
rm "$work/infra/traefik/dynamic/link.yml"
mkdir "$work/infra/traefik/dynamic/sub"
check "test-ziti-tls.yml" && fail "Unterverzeichnis akzeptiert"
rmdir "$work/infra/traefik/dynamic/sub"
echo "# geändert" >> "$work/infra/traefik/dynamic/security.yml"
check "test-ziti-tls.yml" && fail "veränderte versionierte Datei akzeptiert"
git -C "$work" checkout -q -- infra/traefik/dynamic
grep -q 'TRAEFIK_HOST_DYNAMIC_FILES' scripts/lib/env.sh || fail "TRAEFIK_HOST_DYNAMIC_FILES fehlt in der env-Allowlist"
echo "traefik dynamic files: ok"

python3 - <<'PY'
text = open("scripts/deploy.sh").read()
rollback = text.split("rollback_apps() {", 1)[1].split("\n}\n", 1)[0]
assert rollback.index('MIGRATIONS_APPLIED:-0}" = 1') < rollback.index("rollback_app_images"), "Migrationen prüfen vor Image-Rollback"
assert "hold_release_after_migration" in rollback
hold = text.split("hold_release_after_migration() {", 1)[1].split("\n}\n", 1)[0]
assert '.releases/current.env' in hold, "neues Release muss Rollback-Ziel werden"
assert "rollback_app_images" not in hold
migration = text.split("MIGRATIONS_APPLIED=0", 1)[1].split("Datenbankmigration fehlgeschlagen", 1)[0]
assert "Running upgrade" in migration and "MIGRATIONS_APPLIED=1" in migration
assert text.index("MIGRATIONS_APPLIED=0") < text.index('echo "==> [$ENVIRONMENT] Deploy"')
print("deploy rollback guard: ok")
PY

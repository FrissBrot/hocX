#!/usr/bin/env bash
set -euo pipefail

# Einmalige Host-Vorbereitung fuer hocX. Dieses Skript wird als root direkt aus dem
# geklonten Repository ausgefuehrt; regulaere Deployments laufen danach ausschliesslich
# als hocx-deploy. Usage: scripts/provision_deploy_user.sh <test|prod>

DEPLOY_USER="hocx-deploy"
DEPLOY_GROUP=""
STORAGE_GROUP_ID=5001
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENVIRONMENT="${1:-}"
ENVIRONMENT_DIR=/etc/hocx
ENVIRONMENT_FILE="$ENVIRONMENT_DIR/environment"

if [ "$EUID" -ne 0 ]; then
  echo "Dieses Provisioning-Skript muss als root ausgefuehrt werden." >&2
  exit 1
fi

case "$ENVIRONMENT" in
  test|prod) ;;
  *)
    echo "Usage: $0 <test|prod>" >&2
    exit 1
    ;;
esac

if ! command -v docker > /dev/null 2>&1; then
  echo "Docker muss vor dem hocX-Provisioning installiert werden." >&2
  exit 1
fi
if ! getent group docker > /dev/null; then
  echo "Die Gruppe 'docker' fehlt. Docker Engine bitte vollstaendig installieren." >&2
  exit 1
fi
docker compose version > /dev/null || {
  echo "Docker Compose Plugin ist nicht verfuegbar." >&2
  exit 1
}

if [ -e "$ENVIRONMENT_FILE" ]; then
  if [ ! -f "$ENVIRONMENT_FILE" ] || [ -L "$ENVIRONMENT_FILE" ]; then
    echo "$ENVIRONMENT_FILE muss eine regulaere Datei sein." >&2
    exit 1
  fi
  EXISTING_ENVIRONMENT="$(sed -n '1p' "$ENVIRONMENT_FILE")"
  if [ "$EXISTING_ENVIRONMENT" != "$ENVIRONMENT" ]; then
    echo "Dieser Host ist bereits als '$EXISTING_ENVIRONMENT' gebunden." >&2
    echo "Eine automatische Umstellung auf '$ENVIRONMENT' wird abgelehnt." >&2
    exit 1
  fi
else
  install -d -m 755 -o root -g root "$ENVIRONMENT_DIR"
  ENVIRONMENT_TMP="$(mktemp "$ENVIRONMENT_DIR/.environment.tmp.XXXXXX")"
  trap 'rm -f "$ENVIRONMENT_TMP"' EXIT
  printf '%s\n' "$ENVIRONMENT" > "$ENVIRONMENT_TMP"
  chown root:root "$ENVIRONMENT_TMP"
  chmod 444 "$ENVIRONMENT_TMP"
  mv "$ENVIRONMENT_TMP" "$ENVIRONMENT_FILE"
  trap - EXIT
fi

if ! id "$DEPLOY_USER" > /dev/null 2>&1; then
  echo "==> Erstelle Deploy-Benutzer $DEPLOY_USER"
  useradd --create-home --shell /bin/bash --user-group "$DEPLOY_USER"
else
  echo "==> Deploy-Benutzer $DEPLOY_USER existiert bereits"
fi
DEPLOY_GROUP="$(id -gn "$DEPLOY_USER")"

usermod --append --groups docker "$DEPLOY_USER"

echo "==> Richte Repository und private Deploy-Verzeichnisse ein"
chown -R "$DEPLOY_USER:$DEPLOY_GROUP" "$REPO_DIR"
install -d -m 700 -o "$DEPLOY_USER" -g "$DEPLOY_GROUP" \
  "$REPO_DIR/.tools" \
  "$REPO_DIR/.releases" \
  "$REPO_DIR/backups" \
  "$REPO_DIR/infra/traefik/letsencrypt"
if [ ! -e "$REPO_DIR/.deploy.lock" ]; then
  install -m 600 -o "$DEPLOY_USER" -g "$DEPLOY_GROUP" /dev/null "$REPO_DIR/.deploy.lock"
else
  chown "$DEPLOY_USER:$DEPLOY_GROUP" "$REPO_DIR/.deploy.lock"
  chmod 600 "$REPO_DIR/.deploy.lock"
fi

if [ -f "$REPO_DIR/.env" ]; then
  if [ -L "$REPO_DIR/.env" ]; then
    echo ".env darf kein Symlink sein." >&2
    exit 1
  fi
  chown "$DEPLOY_USER:$DEPLOY_GROUP" "$REPO_DIR/.env"
  chmod 600 "$REPO_DIR/.env"
fi

echo "==> Richte Runtime-Verzeichnisse fuer Non-Root-Container ein"
install -d -m 2770 -o "$DEPLOY_USER" -g "$STORAGE_GROUP_ID" \
  "$REPO_DIR/storage" \
  "$REPO_DIR/storage/abgabebox-uploads" \
  "$REPO_DIR/infra/traefik/dynamic"

for runtime_dir in "$REPO_DIR/storage" "$REPO_DIR/infra/traefik/dynamic"; do
  if find "$runtime_dir" -type l -print -quit | grep -q .; then
    echo "Symlinks im Runtime-Verzeichnis werden aus Sicherheitsgruenden abgelehnt: $runtime_dir" >&2
    exit 1
  fi
  chown -R "$DEPLOY_USER:$STORAGE_GROUP_ID" "$runtime_dir"
  chmod -R u+rwX,g+rwX,o-rwx "$runtime_dir"
  find "$runtime_dir" -type d -exec chmod g+s {} +
done

echo
echo "Provisioning abgeschlossen. Regulaere Deployments nicht als root starten."
echo "Dieser Host ist dauerhaft als '$ENVIRONMENT' gebunden ($ENVIRONMENT_FILE)."
echo
echo "Jetzt in den neu erstellten Benutzer wechseln:"
echo "  sudo -iu $DEPLOY_USER"
echo
echo "Danach den ersten Deploy ausfuehren:"
echo "  cd $REPO_DIR"
echo "  ./scripts/deploy.sh $ENVIRONMENT"
echo
echo "Hinweis: Die docker-Gruppe besitzt bei klassischem Docker Root-Level-Rechte."

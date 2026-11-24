# shellcheck shell=bash
# Geführte Wiederherstellung auf einem neuen Server: ./scripts/deploy.sh <test|prod> --restore-from-backup
#
# Ablauf (eingebunden in scripts/deploy.sh, Details docs-site/docs/technik/backup/restore.md):
#   1. restore_guard          nur auf einem leeren Server (oder Fortsetzung eines abgebrochenen Laufs)
#   2. restore_prepare_env    .env aus der Notfallmappe übernehmen (oder neu, dann die Schlüssel abfragen)
#   3. restore_setup_backup   Zugang zur Storage Box: Werte, neuer SSH-Schlüssel, Host-Key prüfen
#   4. (deploy.sh)            Images ziehen und prüfen, Secret-Dateien schreiben
#   5. restore_run            Punkt wählen, restore-full ins lokale S3, Datenbank an ihren Platz
#   6. (deploy.sh)            Migrationen, Start, Smoke-Checks; danach restore_finish
#
# Ein abgebrochener Lauf lässt sich mit demselben Befehl fortsetzen: der gewählte Punkt steht in
# .releases/restore-in-progress, restore-full --resume übernimmt eine vollständig
# wiederhergestellte Datenbank und überträgt nur noch fehlende Objekte.
#
# Erwartet: DC (Compose-Aufruf als Array), PROJECT_DIR, PROJECT_NAME, ENV_FILE, ENVIRONMENT.
# Eingaben kommen von RESTORE_TTY (Standard /dev/tty), damit Tests sie vorgeben können.

RESTORE_TARGET_DB="hocx_restored"
RESTORE_EMPTY_DB="hocx_leer_vor_restore"
RESTORE_CONFIRM_WORD="WIEDERHERSTELLEN"

restore_marker_file() {
  printf '%s/.releases/restore-in-progress' "$PROJECT_DIR"
}

# Eingabe einmal öffnen und fortlaufend lesen (Terminal oder in Tests eine Datei mit Antworten).
restore_read() {
  local variable="$1" secret="${2:-false}" line=""
  if [ -z "${RESTORE_TTY_FD:-}" ]; then
    exec {RESTORE_TTY_FD}< "${RESTORE_TTY:-/dev/tty}" || return 1
  fi
  if [ "$secret" = true ]; then
    IFS= read -r -s -u "$RESTORE_TTY_FD" line || return 1
    printf '\n' >&2
  else
    IFS= read -r -u "$RESTORE_TTY_FD" line || return 1
  fi
  printf -v "$variable" '%s' "$line"
}

restore_say() {
  printf '%s\n' "$*" >&2
}

# restore_ask VAR "Frage" [Vorgabe] [secret]
restore_ask() {
  local variable="$1" label="$2" default_value="${3:-}" secret="${4:-false}" value=""
  while true; do
    if [ -n "$default_value" ]; then
      printf '  %s [%s]: ' "$label" "$default_value" >&2
    else
      printf '  %s: ' "$label" >&2
    fi
    restore_read value "$secret" || return 1
    value="${value:-$default_value}"
    if [ -z "$value" ]; then
      restore_say "    Der Wert darf nicht leer sein."
    elif [[ "$value" == *"'"* ]]; then
      restore_say "    Einfache Anführungszeichen sind nicht erlaubt."
    else
      printf -v "$variable" '%s' "$value"
      return 0
    fi
  done
}

restore_confirm() {
  local answer=""
  printf '  %s [ja/NEIN]: ' "$1" >&2
  restore_read answer || return 1
  case "$answer" in ja|Ja|JA|j|J|yes|y) return 0 ;; *) return 1 ;; esac
}

# KEY in der .env setzen (ersetzen oder anhängen) und in der Shell exportieren.
restore_set_env() {
  local key="$1" value="$2" temp_file
  temp_file="$(mktemp "${ENV_FILE}.tmp.XXXXXX")"
  grep -Ev "^[[:space:]]*(export[[:space:]]+)?${key}=" "$ENV_FILE" > "$temp_file" || true
  printf "%s='%s'\n" "$key" "$value" >> "$temp_file"
  chmod 600 "$temp_file"
  mv "$temp_file" "$ENV_FILE"
  printf -v "$key" '%s' "$value"
  # shellcheck disable=SC2163  # exportiert bewusst die Variable, deren Name in $key steht
  export "$key"
}

# Nur auf einem Server ohne hocX-Daten - ein laufender Server wird über das Admin-Portal
# wiederhergestellt («Vollständige Wiederherstellung», mit Rettungspunkt und Rücktausch).
restore_guard() {
  if [ -f "$(restore_marker_file)" ]; then
    restore_say "==> [$ENVIRONMENT] Abgebrochene Wiederherstellung wird fortgesetzt ($(restore_marker_file))."
    return 0
  fi
  local reason=""
  if [ -f "$PROJECT_DIR/.releases/current.env" ]; then
    reason="auf diesem Server läuft bereits ein hocX-Release (.releases/current.env)"
  else
    local volume
    for volume in postgres18_data postgres_data; do
      if docker volume inspect "${PROJECT_NAME}_${volume}" > /dev/null 2>&1; then
        reason="die Datenbank ${PROJECT_NAME}_${volume} existiert bereits"
        break
      fi
    done
  fi
  if [ -n "$reason" ]; then
    restore_say "Wiederherstellung abgebrochen: $reason."
    restore_say "Der geführte Restore ist nur für einen neuen, leeren Server gedacht. Eine laufende Installation"
    restore_say "stellst du im Admin-Portal wieder her: System › Backups › Wiederherstellung (mit Rettungspunkt)."
    return 1
  fi
}

# .env aus der Notfallmappe übernehmen. Ohne sie legt deploy.sh eine neue an (create_env_file);
# danach fragt restore_import_keys die Schlüssel ab, ohne die alte Daten nicht lesbar wären.
restore_prepare_env() {
  [ ! -f "$ENV_FILE" ] || return 0
  restore_say "==> [$ENVIRONMENT] Wiederherstellung: Konfiguration"
  restore_say "    Am besten die .env aus der Notfallmappe (Passwortmanager): sie enthält die Schlüssel,"
  restore_say "    mit denen Zwei-Faktor-Anmeldungen und gespeicherte Zugangsdaten verschlüsselt sind."
  local source=""
  printf '  Pfad zur gesicherten .env (leer = neu anlegen): ' >&2
  restore_read source || return 1
  if [ -z "$source" ]; then
    RESTORE_NEW_ENV=1
    return 0
  fi
  if [ ! -f "$source" ] || [ -L "$source" ]; then
    restore_say "    $source ist keine reguläre Datei."
    return 1
  fi
  install -m 600 "$source" "$ENV_FILE"
  restore_say "    .env übernommen (Dateirechte 600)."
}

# Nach create_env_file: die Schlüssel der alten Installation eintragen, soweit vorhanden.
restore_import_keys() {
  [ "${RESTORE_NEW_ENV:-0}" = 1 ] || return 0
  restore_say "    Neue .env: Schlüssel der alten Installation eintragen (leer = neu, Folgen in Klammern)."
  local key label value
  for key in ADMIN_AUTH_SECRET STORAGE_CREDENTIALS_KEY EXPORT_ENCRYPTION_KEY; do
    case "$key" in
      ADMIN_AUTH_SECRET) label="ADMIN_AUTH_SECRET (sonst müssen alle Zwei-Faktor-Apps neu eingerichtet werden)" ;;
      STORAGE_CREDENTIALS_KEY) label="STORAGE_CREDENTIALS_KEY (sonst sind gespeicherte S3-/ntfy-Zugangsdaten neu einzugeben)" ;;
      EXPORT_ENCRYPTION_KEY) label="EXPORT_ENCRYPTION_KEY (sonst lassen sich alte Exporte ohne Passwort nicht öffnen)" ;;
    esac
    value=""
    printf '  %s: ' "$label" >&2
    restore_read value true || return 1
    [ -z "$value" ] || restore_set_env "$key" "$value"
  done
}

# Zugang zum Borg-Repository: Werte aus der .env (fehlende werden abgefragt), ein neuer SSH-Schlüssel
# für diesen Server und der Host-Key der Storage Box - nie ungeprüft übernommen.
restore_setup_backup() {
  restore_say "==> [$ENVIRONMENT] Wiederherstellung: Zugang zur Storage Box"
  local value
  if [ -z "${BACKUP_STORAGEBOX_HOST:-}" ]; then restore_ask value "Storage-Box-Host (z. B. u123456-sub3.your-storagebox.de)"; restore_set_env BACKUP_STORAGEBOX_HOST "$value"; fi
  if [ -z "${BACKUP_STORAGEBOX_USER:-}" ]; then restore_ask value "Storage-Box-Benutzer (z. B. u123456-sub3)"; restore_set_env BACKUP_STORAGEBOX_USER "$value"; fi
  if [ -z "${BACKUP_PASSPHRASE:-}" ]; then restore_ask value "Borg-Passphrase (Notfallmappe)" "" true; restore_set_env BACKUP_PASSPHRASE "$value"; fi
  if [ -z "${BACKUP_REPOSITORY_ID:-}" ]; then
    restore_ask value "Repository-ID (64 Hex-Zeichen, Notfallmappe/Admin-Portal)"
    if [[ ! "$value" =~ ^[0-9a-fA-F]{64}$ ]]; then
      restore_say "    Die Repository-ID muss aus 64 Hex-Zeichen bestehen."
      return 1
    fi
    restore_set_env BACKUP_REPOSITORY_ID "$value"
  fi
  # Nach dem Restore sichert der Server weiter in dasselbe Repository.
  [ "${BACKUP_ENABLED:-false}" = true ] || restore_set_env BACKUP_ENABLED true

  local key_path="${BACKUP_SSH_KEY_PATH:-$HOME/.hocx-backup/id_backup}"
  local repo_path="${BACKUP_REPOSITORY_PATH:-hocx-borg}"
  repo_path="${repo_path#./}"
  if [ ! -f "$key_path" ]; then
    mkdir -p "$(dirname "$key_path")"
    chmod 700 "$(dirname "$key_path")"
    ssh-keygen -q -t ed25519 -N "" -C "hocx-backup $(hostname)" -f "$key_path" || return 1
    chmod 600 "$key_path"
    restore_say ""
    restore_say "    Neuer Backup-Schlüssel für diesen Server. In der Storage Box (Hetzner Robot oder mit dem"
    restore_say "    Wartungsschlüssel) in .ssh/authorized_keys als eigene Zeile eintragen - nur anhängen und"
    restore_say "    nur dieses Repository, wie der Schlüssel des alten Servers:"
    restore_say ""
    printf 'command="borg-1.4 serve --append-only --restrict-to-repository /home/%s",restrict %s\n' "$repo_path" "$(cat "${key_path}.pub")" >&2
    restore_say ""
    restore_say "    Den Schlüssel des alten Servers danach entfernen."
    restore_confirm "Ist der Schlüssel eingetragen?" || { restore_say "    Abgebrochen. Später mit demselben Befehl fortsetzen."; return 1; }
  fi
  restore_set_env BACKUP_SSH_KEY_PATH "$key_path"

  local known_hosts="${BACKUP_KNOWN_HOSTS_PATH:-$HOME/.hocx-backup/known_hosts}"
  if [ ! -f "$known_hosts" ]; then
    local port="${BACKUP_STORAGEBOX_PORT:-23}" scanned
    scanned="$(mktemp)"
    if ! ssh-keyscan -p "$port" -t ed25519 "$BACKUP_STORAGEBOX_HOST" > "$scanned" 2> /dev/null || [ ! -s "$scanned" ]; then
      rm -f "$scanned"
      restore_say "    Host-Key von $BACKUP_STORAGEBOX_HOST:$port nicht lesbar - Host und Netzwerk prüfen."
      return 1
    fi
    restore_say "    Host-Key der Storage Box:"
    ssh-keygen -lf "$scanned" >&2
    restore_say "    Mit dem Fingerabdruck aus der Notfallmappe bzw. der Hetzner-Dokumentation vergleichen."
    if ! restore_confirm "Stimmt der Fingerabdruck genau überein?"; then
      rm -f "$scanned"
      restore_say "    Abgebrochen: ein unbekannter Host-Key wird nie übernommen (möglicher Angriff oder falsches Ziel)."
      return 1
    fi
    mkdir -p "$(dirname "$known_hosts")"
    install -m 600 "$scanned" "$known_hosts"
    rm -f "$scanned"
  fi
  restore_set_env BACKUP_KNOWN_HOSTS_PATH "$known_hosts"
}

# Recovery-CLI im backup-worker-Image, ohne laufendes Backend. Die Passwörter der Laufzeitrollen
# (restore-full legt fehlende an) und die Zugangsdaten des lokalen S3 gehen als Umgebung hinein,
# nie als Argument.
restore_cli() {
  "${DC[@]}" run --rm --no-deps -T \
    -e APP_DB_PASSWORD -e ABGABEBOX_DB_PASSWORD -e PHOTO_WORKER_DB_PASSWORD -e GEO_DB_PASSWORD \
    -e LOCAL_S3_ACCESS_KEY -e LOCAL_S3_SECRET_KEY -e LOCAL_S3_ABGABEBOX_ACCESS_KEY -e LOCAL_S3_ABGABEBOX_SECRET_KEY \
    --entrypoint python backup-worker -m app.backup.cli "$@"
}

restore_psql() {
  "${DC[@]}" exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -At -c "$1"
}

restore_database_exists() {
  [ "$(restore_psql "SELECT 1 FROM pg_database WHERE datname = '$1'")" = 1 ]
}

# Liste der Punkte (neueste zuerst, ohne ungültige) als "archiv<TAB>zeit<TAB>version<TAB>objekte".
restore_list_points() {
  restore_cli list --details --tsv | awk -F '\t' 'NF >= 5 && $5 != "True" { print $1 "\t" $2 "\t" $3 "\t" $4 }' | sort -t $'\t' -k2,2r
}

restore_choose_point() {
  local points count index=1 line choice
  points="$(restore_list_points)" || return 1
  count="$(printf '%s\n' "$points" | grep -c . || true)"
  if [ "$count" -eq 0 ]; then
    restore_say "    Im Repository gibt es keinen gültigen Wiederherstellungspunkt."
    return 1
  fi
  restore_say "    Wiederherstellungspunkte (neueste zuerst):"
  while IFS=$'\t' read -r archive snapshot version objects; do
    [ "$index" -le 15 ] || break
    restore_say "    $(printf '%2d' "$index")) ${snapshot%%.*}  hocX ${version:-?}  ${objects:-?} Objekte  ($archive)"
    index=$((index + 1))
  done <<< "$points"
  restore_ask choice "Welcher Punkt?" 1
  if [[ ! "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt "$count" ]; then
    restore_say "    Ungültige Auswahl."
    return 1
  fi
  line="$(printf '%s\n' "$points" | sed -n "${choice}p")"
  RESTORE_ARCHIVE="${line%%$'\t'*}"
  RESTORE_ARCHIVE_VERSION="$(printf '%s' "$line" | cut -f3)"
}

restore_run() {
  local marker
  marker="$(restore_marker_file)"
  RESTORE_ARCHIVE=""
  if [ -f "$marker" ]; then
    RESTORE_ARCHIVE="$(sed -n 's/^ARCHIVE=//p' "$marker")"
  fi

  restore_say "==> [$ENVIRONMENT] Wiederherstellung: Datenbank und lokales S3 starten"
  "${DC[@]}" up -d --pull never db || return 1
  local attempt
  for attempt in $(seq 1 60); do
    "${DC[@]}" exec -T db pg_isready -U "$POSTGRES_USER" > /dev/null 2>&1 && break
    [ "$attempt" -lt 60 ] || { restore_say "    Datenbank startet nicht."; return 1; }
    sleep 2
  done
  if service_exists local-s3; then
    "${DC[@]}" up -d --pull never local-s3 || return 1
    "${DC[@]}" run --rm --no-deps --pull never storage-init > /dev/null || { restore_say "    Lokales S3 liess sich nicht einrichten."; return 1; }
  fi

  restore_say "==> [$ENVIRONMENT] Wiederherstellung: Repository prüfen"
  restore_cli info || { restore_say "    Repository nicht erreichbar oder Repository-ID passt nicht (siehe oben)."; return 1; }

  if [ -z "$RESTORE_ARCHIVE" ]; then
    restore_choose_point || return 1
  fi
  local state upgrade=()
  state="$(restore_cli show "$RESTORE_ARCHIVE" --schema-state | tail -n 1)" || return 1
  case "$state" in
    same) ;;
    upgrade)
      restore_say "    Der Punkt stammt von einer älteren hocX-Version (${RESTORE_ARCHIVE_VERSION:-?}); nach dem Restore wird die"
      restore_say "    Datenbank kontrolliert auf $HOCX_VERSION migriert."
      restore_confirm "So fortfahren?" || return 1
      upgrade=(--allow-schema-upgrade)
      ;;
    *)
      printf 'ARCHIVE=%s\n' "$RESTORE_ARCHIVE" > "$marker"
      restore_say "    Der Punkt ist neuer als $HOCX_VERSION (Schema: $state). In $ENV_FILE HOCX_VERSION auf die Version"
      restore_say "    des Backups setzen (${RESTORE_ARCHIVE_VERSION:+v$RESTORE_ARCHIVE_VERSION}) und denselben Befehl erneut starten - der Punkt ist vorgemerkt."
      return 1
      ;;
  esac
  printf 'ARCHIVE=%s\n' "$RESTORE_ARCHIVE" > "$marker"

  local resume=()
  if restore_database_exists "$RESTORE_TARGET_DB"; then
    restore_say "    Fortsetzung: $RESTORE_TARGET_DB ist schon da (restore-full übernimmt sie nur, wenn sie vollständig ist)."
    resume=(--resume)
  else
    restore_say ""
    restore_say "    Punkt $RESTORE_ARCHIVE wird in eine neue Datenbank und das lokale S3 dieses Servers"
    restore_say "    wiederhergestellt. Danach startet hocX in Wartung, bis du sie im Admin-Portal freigibst."
    local word=""
    printf '  Zum Bestätigen %s eingeben: ' "$RESTORE_CONFIRM_WORD" >&2
    restore_read word || return 1
    [ "$word" = "$RESTORE_CONFIRM_WORD" ] || { restore_say "    Abgebrochen."; return 1; }
  fi

  restore_say "==> [$ENVIRONMENT] Wiederherstellung: Daten aus dem Backup holen (kann dauern)"
  local rc=0
  restore_cli restore-full --archive "$RESTORE_ARCHIVE" --target-db "$RESTORE_TARGET_DB" --local-s3 --yes ${upgrade[@]+"${upgrade[@]}"} ${resume[@]+"${resume[@]}"} || rc=$?
  if [ "$rc" -eq 2 ]; then
    restore_say "    Achtung: Die Referenzprüfung meldet Abweichungen (Bericht oben, z. B. fehlende Objekte)."
    restore_confirm "Trotzdem übernehmen?" || return 1
  elif [ "$rc" -ne 0 ]; then
    restore_say "    Wiederherstellung fehlgeschlagen (siehe oben). Mit demselben Befehl fortsetzen."
    return 1
  fi

  restore_say "==> [$ENVIRONMENT] Wiederherstellung: Datenbank an ihren Platz"
  restore_cli swap-database --live "$POSTGRES_DB" --restored "$RESTORE_TARGET_DB" --keep-as "$RESTORE_EMPTY_DB" --yes || return 1
  # Die beim ersten Start angelegte, leere Datenbank wird nicht gebraucht.
  if restore_database_exists "$RESTORE_EMPTY_DB"; then
    "${DC[@]}" exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$RESTORE_EMPTY_DB" -At \
      -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'" 2> /dev/null | grep -qx 0 \
      && restore_psql "DROP DATABASE \"$RESTORE_EMPTY_DB\"" > /dev/null
  fi
}

restore_finish() {
  rm -f "$(restore_marker_file)"
  cat >&2 <<EOF

==> [$ENVIRONMENT] Wiederherstellung abgeschlossen. Jetzt:
    1. DNS der Domains auf diesen Server zeigen lassen (Zertifikate holt Traefik selbst).
    2. Im Admin-Portal anmelden (Konten und Zwei-Faktor wie vorher), Stichproben in den Organisationen.
    3. System › Wartung: die Wartung «Wiederherstellung per Recovery-CLI» freigeben.
    4. System › Backups: «Backup jetzt starten» - der Server sichert ab jetzt weiter in dasselbe Repository.
    5. Den SSH-Schlüssel des alten Servers aus authorized_keys der Storage Box entfernen.
    6. ./scripts/verify_release.sh $ENVIRONMENT
EOF
}

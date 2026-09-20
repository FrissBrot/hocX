#!/usr/bin/env bash

# Bringt eine bestehende .env auf das Schema des aktuellen Release-Stands, damit ein
# Update ohne manuelles Nachpflegen durchlaeuft. Wird von deploy.sh vor dem Laden der .env
# aufgerufen; ohne noetige Aenderung passiert nichts (idempotent).
#
# Ablauf pro Release, das neue Pflichtvariablen einfuehrt oder alte entfernt:
#   1. Eintrag in ENV_RETIRED_KEYS bzw. in migrate_env_file() ergaenzen.
#   2. scripts/tests/test_env_migrate.sh (Fixture: scripts/tests/fixtures/) erweitern.
# Die .env wird nie ueber `source` gelesen (siehe lib/env.sh), sondern nur als Daten.

# ENV_RETIRED_KEYS und is_retired_env_key stehen in lib/env.sh (das auch verify_release.sh
# nutzt); dieses File setzt voraus, dass env.sh bereits geladen ist.

env_file_has_key() {
  grep -Eq "^[[:space:]]*(export[[:space:]]+)?$2=" "$1"
}

# Gibt den (geparsten) Wert einer Variable aus; leer, wenn sie fehlt.
env_file_value() {
  local env_file="$1" key="$2"
  (
    load_env_file "$env_file" > /dev/null || exit 1
    printf '%s' "${!key-}"
  )
}

migrate_env_file() {
  local env_file="$1"
  local tmp_file backup_file key password photo_url
  local changed=false
  local -a notes=()

  if [ ! -f "$env_file" ] || [ -L "$env_file" ]; then
    echo "Env-Datei $env_file muss eine regulaere Datei und darf kein Symlink sein." >&2
    return 1
  fi
  # Rechte und erlaubte Schluessel prueft load_env_file; scheitert es hier, bricht der
  # Deploy mit derselben Meldung ab wie sonst auch - vor jeder Aenderung.
  env_file_value "$env_file" HOCX_VERSION > /dev/null || {
    echo "Env-Datei $env_file konnte nicht gelesen werden (siehe Meldung oben)." >&2
    return 1
  }

  local umask_before
  umask_before="$(umask)"
  umask 077
  tmp_file="$(mktemp "$env_file.tmp.XXXXXX")"

  cp -p "$env_file" "$tmp_file"

  for key in "${ENV_RETIRED_KEYS[@]}"; do
    if env_file_has_key "$tmp_file" "$key"; then
      grep -Ev "^[[:space:]]*(export[[:space:]]+)?$key=" "$tmp_file" > "$tmp_file.next" || true
      mv "$tmp_file.next" "$tmp_file"
      notes+=("entfernt: $key (existiert nicht mehr)")
      changed=true
    fi
  done

  # 1.1.0: eigene DB-Rolle fuer den photo-analysis-worker (Migration 0067).
  password="$(env_file_value "$env_file" PHOTO_WORKER_DB_PASSWORD)"
  if [ -z "$password" ]; then
    command -v openssl > /dev/null 2>&1 || {
      rm -f "$tmp_file"
      umask "$umask_before"
      echo "openssl wird zum sicheren Erzeugen der Secrets benoetigt." >&2
      return 1
    }
    password="$(openssl rand -hex 32)"
    grep -Ev "^[[:space:]]*(export[[:space:]]+)?PHOTO_WORKER_DB_PASSWORD=" "$tmp_file" > "$tmp_file.next" || true
    mv "$tmp_file.next" "$tmp_file"
    printf "PHOTO_WORKER_DB_PASSWORD='%s'\n" "$password" >> "$tmp_file"
    notes+=("ergaenzt: PHOTO_WORKER_DB_PASSWORD (neu erzeugt)")
    changed=true
  fi
  photo_url="$(env_file_value "$env_file" PHOTO_WORKER_DATABASE_URL)"
  if [ -z "$photo_url" ]; then
    grep -Ev "^[[:space:]]*(export[[:space:]]+)?PHOTO_WORKER_DATABASE_URL=" "$tmp_file" > "$tmp_file.next" || true
    mv "$tmp_file.next" "$tmp_file"
    printf "PHOTO_WORKER_DATABASE_URL='postgresql+psycopg://hocx_photo_worker:%s@db:5432/%s'\n" \
      "$password" "$(env_file_value "$env_file" POSTGRES_DB)" >> "$tmp_file"
    notes+=("ergaenzt: PHOTO_WORKER_DATABASE_URL")
    changed=true
  fi

  if [ "$changed" = true ]; then
    backup_file="$env_file.bak-$(date +%Y%m%d-%H%M%S)"
    cp -p "$env_file" "$backup_file"
    chmod 600 "$tmp_file" "$backup_file"
    mv "$tmp_file" "$env_file"
    echo "    .env auf aktuelles Schema migriert (Sicherung: $backup_file):"
    printf '      - %s\n' "${notes[@]}"
  else
    rm -f "$tmp_file"
  fi
  umask "$umask_before"
}

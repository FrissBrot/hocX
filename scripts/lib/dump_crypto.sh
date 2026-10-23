#!/usr/bin/env bash
# Verschlüsselung lokaler Datenbank-Dumps (Pre-Deploy, Cron-Backup) - Datenschutz-Audit PRIV-009.
#
# Der Server kennt nur den öffentlichen GPG-Schlüssel (BACKUP_DUMP_PUBLIC_KEY_PATH, Standard
# ~/.hocx-backup/dump-public.asc). Den privaten Schlüssel gibt es nur in der Notfallmappe: wer die
# Dumps kopiert, kann sie ohne ihn nicht lesen. Eingerichtet wird das in RUNBOOK Abschnitt 10.
#
# Ohne Schlüssel bleibt es beim bisherigen gzip-Dump, mit einer deutlichen Warnung.
# HOCX_REQUIRE_DUMP_ENCRYPTION=true macht den Schlüssel zur Pflicht (Abbruch ohne Schlüssel).

# Temporären GPG-Schlüsselbund samt gestartetem gpg-agent entfernen.
_drop_gnupg_home() {
  GNUPGHOME="$1" gpgconf --kill gpg-agent > /dev/null 2>&1 || true
  rm -rf "$1"
}

dump_public_key_path() {
  printf '%s\n' "${BACKUP_DUMP_PUBLIC_KEY_PATH:-$HOME/.hocx-backup/dump-public.asc}"
}

dump_encryption_available() {
  [ -s "$(dump_public_key_path)" ] && command -v gpg > /dev/null 2>&1
}

# Endung des Dumps: .sql.gz.gpg (verschlüsselt) oder .sql.gz
dump_suffix() {
  if dump_encryption_available; then printf '.sql.gz.gpg\n'; else printf '.sql.gz\n'; fi
}

# Prüft vor dem Schreiben: Pflicht ohne Schlüssel -> Fehler (Rückgabe 1), sonst nur Warnung.
check_dump_encryption() {
  if dump_encryption_available; then
    return 0
  fi
  if [ "${HOCX_REQUIRE_DUMP_ENCRYPTION:-false}" = true ]; then
    echo "FEHLER: Dump-Verschlüsselung verlangt, aber kein öffentlicher Schlüssel unter $(dump_public_key_path) (oder gpg fehlt)." >&2
    return 1
  fi
  echo "WARNUNG: Dump wird unverschlüsselt geschrieben - öffentlichen Schlüssel unter $(dump_public_key_path) ablegen (RUNBOOK Abschnitt 10)." >&2
  return 0
}

# stdin (SQL) -> gzip -> optional GPG -> Datei. Der Aufrufer prüft vorher check_dump_encryption.
write_dump() {
  local target="$1" gnupg_home status
  if dump_encryption_available; then
    gnupg_home="$(mktemp -d)"
    chmod 700 "$gnupg_home"
    gzip | GNUPGHOME="$gnupg_home" gpg --batch --yes --quiet --trust-model always \
      --recipient-file "$(dump_public_key_path)" --output "$target" --encrypt
    status=$?
    _drop_gnupg_home "$gnupg_home"
    return "$status"
  fi
  gzip > "$target"
}

# Entschlüsselt einen .gpg-Dump nach <Ziel> (weiterhin gzip). Braucht den privaten Schlüssel
# (BACKUP_DUMP_PRIVATE_KEY_PATH oder im GPG-Schlüsselbund des Aufrufers).
decrypt_dump_to() {
  local source="$1" target="$2" gnupg_home status
  command -v gpg > /dev/null 2>&1 || { echo "FEHLER: gpg fehlt - verschlüsselter Dump nicht lesbar." >&2; return 1; }
  if [ -n "${BACKUP_DUMP_PRIVATE_KEY_PATH:-}" ]; then
    gnupg_home="$(mktemp -d)"
    chmod 700 "$gnupg_home"
    if ! GNUPGHOME="$gnupg_home" gpg --batch --quiet --import "$BACKUP_DUMP_PRIVATE_KEY_PATH"; then
      _drop_gnupg_home "$gnupg_home"
      return 1
    fi
    GNUPGHOME="$gnupg_home" gpg --quiet --yes --output "$target" --decrypt "$source"
    status=$?
    _drop_gnupg_home "$gnupg_home"
    return "$status"
  fi
  gpg --quiet --yes --output "$target" --decrypt "$source"
}

# Löscht Dateien nach Muster, die älter als <Tage> sind; die neueste bleibt immer erhalten
# (Rollback braucht mindestens einen Stand).
prune_dumps_older_than() {
  local dir="$1" pattern="$2" days="$3" newest
  [[ "$days" =~ ^[1-9][0-9]*$ ]] || return 0
  newest="$(find "$dir" -maxdepth 1 -type f -name "$pattern" -printf '%f\n' | sort -r | head -n 1)"
  find "$dir" -maxdepth 1 -type f -name "$pattern" -mtime "+$days" -printf '%f\n' | while IFS= read -r file; do
    [ "$file" = "$newest" ] && continue
    rm -f -- "$dir/$file"
    echo "    Alter Dump entfernt: $file"
  done
}

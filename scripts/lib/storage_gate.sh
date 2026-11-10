# shellcheck shell=bash
# Upgrade-Tor «nur noch S3» (Migration 0168_s3_only), ausgeführt von scripts/deploy.sh, solange
# noch das bisherige Release läuft - nur dieses kann den Dateisystem-Bestand (Generation 0)
# bereinigen. Die Migration prüft dieselben Bedingungen noch einmal (Sicherheitsnetz für
# Deployments ohne dieses Skript).
#
# Ablauf:
# - Datenbank läuft nicht (erster Deploy) oder Objektspeicher-Tabellen fehlen: siehe unten.
# - Dateisystem noch aktiv und Dateien vorhanden, oder eine Storage-Migration offen: Abbruch.
# - Dateisystem-Generation in der Rückfallfrist: Warnung, Frage «Frist jetzt beenden?»;
#   nicht interaktiv nur mit HOCX_SKIP_STORAGE_FALLBACK=1. Frist abgelaufen: ohne Frage.
#   Dann Bereinigung anfordern und warten, bis der storage-worker des bisherigen Releases sie
#   erledigt hat (entfernt nur Dateien, deren Kopie die Erstmigration verifiziert hat).
#
# Erwartet: DC (Compose-Aufruf als Array), POSTGRES_USER, POSTGRES_DB.

STORAGE_GATE_POLL_SECONDS="${STORAGE_GATE_POLL_SECONDS:-10}"

storage_gate_sql() {
  "${DC[@]}" exec -T db psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -F '|' -c "$1"
}

storage_gate_confirm() {
  local answer
  case "${HOCX_SKIP_STORAGE_FALLBACK:-}" in
    1|true|yes|ja) echo "    HOCX_SKIP_STORAGE_FALLBACK gesetzt: Rückfallfrist wird beendet."; return 0 ;;
    "") ;;
    *) echo "    HOCX_SKIP_STORAGE_FALLBACK=${HOCX_SKIP_STORAGE_FALLBACK} wird nicht erkannt (erlaubt: 1)." >&2; return 1 ;;
  esac
  # STORAGE_GATE_INTERACTIVE=1 nur für scripts/tests/test_storage_gate.sh (Antwort über stdin).
  if [ ! -t 0 ] && [ "${STORAGE_GATE_INTERACTIVE:-}" != 1 ]; then
    echo "    Nicht interaktiv: zum Überspringen HOCX_SKIP_STORAGE_FALLBACK=1 setzen." >&2
    return 1
  fi
  read -r -p "    Rückfallfrist jetzt beenden und den Dateisystem-Bestand bereinigen? [j/N] " answer
  case "$answer" in
    j|J|ja|Ja|JA|y|Y|yes) return 0 ;;
    *) return 1 ;;
  esac
}

storage_upgrade_gate() {
  local timeout="${HOCX_STORAGE_PURGE_TIMEOUT:-3600}"
  # Nur Ganzzahlen: ein Tippfehler liesse sonst die Warteschleife nie enden, und $(( )) wertet
  # Ausdrücke aus.
  if ! [[ "$timeout" =~ ^[0-9]+$ && "$STORAGE_GATE_POLL_SECONDS" =~ ^[0-9]+$ ]]; then
    echo "Update abgebrochen: HOCX_STORAGE_PURGE_TIMEOUT und STORAGE_GATE_POLL_SECONDS müssen ganze Sekunden sein." >&2
    return 1
  fi
  if [ -z "$("${DC[@]}" ps db --status running -q 2> /dev/null)" ]; then
    echo "    Datenbank läuft noch nicht (erster Deploy) - die Migration richtet das lokale S3 direkt ein."
    return 0
  fi
  local has_storage
  has_storage="$(storage_gate_sql "SELECT to_regclass('public.storage_state') IS NOT NULL")" || return 1
  if [ "$has_storage" != t ]; then
    local has_tenant
    has_tenant="$(storage_gate_sql "SELECT to_regclass('public.tenant') IS NOT NULL")" || return 1
    if [ "$has_tenant" = t ]; then
      echo "Upgrade gesperrt: diese Instanz läuft noch auf einem Release vor 1.2 (ohne Objektspeicher)." >&2
      echo "Zuerst auf 1.2.2 aktualisieren und dort die Erstmigration auf S3 ausführen, dann erneut deployen." >&2
      return 1
    fi
    return 0
  fi

  local active open_migration
  active="$(storage_gate_sql "SELECT p.provider FROM storage_state s JOIN storage_profile p ON p.id = s.active_profile_id WHERE s.id = 1")" || return 1
  open_migration="$(storage_gate_sql "SELECT kind || ' (' || state || ')' FROM storage_migration WHERE state NOT IN ('completed', 'failed', 'cancelled') LIMIT 1")" || return 1
  if [ -n "$open_migration" ]; then
    echo "Upgrade gesperrt: Storage-Migration $open_migration ist noch offen." >&2
    echo "Erst im Adminportal (System → Storage) abschliessen oder abbrechen, dann erneut deployen." >&2
    return 1
  fi
  if [ "$active" = filesystem ]; then
    local has_files
    has_files="$(storage_gate_sql "SELECT EXISTS (SELECT 1 FROM storage_object) OR EXISTS (SELECT 1 FROM stored_file) OR EXISTS (SELECT 1 FROM document_asset) OR EXISTS (SELECT 1 FROM tenant WHERE profile_image_path IS NOT NULL)")" || return 1
    if [ "$has_files" = t ]; then
      echo "Upgrade gesperrt: hocX speichert ab dieser Version nur noch in S3, die Dateien liegen aber noch im Dateisystem." >&2
      echo "Zuerst mit dem laufenden Release die Erstmigration ausführen (Adminportal → System → Storage →" >&2
      echo "Migration vorbereiten, Ziel «Lokales S3»), dann erneut deployen." >&2
      return 1
    fi
    echo "    Noch keine Dateien gespeichert - die Migration stellt direkt auf das lokale S3 um."
    return 0
  fi

  # Dateisystem-Generationen, die noch nicht bereinigt sind: Generation|Status|in Frist (t/f)|Frist bis
  local rows
  rows="$(storage_gate_sql "SELECT g.generation, g.status, (g.status = 'retained' AND g.retain_until IS NOT NULL AND g.retain_until > NOW()), COALESCE(to_char(g.retain_until AT TIME ZONE 'UTC', 'DD.MM.YYYY HH24:MI'), '') FROM storage_generation g JOIN storage_profile p ON p.id = g.profile_id WHERE p.provider = 'filesystem' AND g.status NOT IN ('purged', 'abandoned') ORDER BY g.generation")" || return 1
  [ -n "$rows" ] || return 0

  # Zeilen zuerst einlesen: die Rückfrage in der Schleife braucht stdin (Terminal) - ein
  # «while read ... <<< $rows» hätte ihr den Here-String als stdin untergeschoben.
  local generation status in_window until line request=() lines=()
  mapfile -t lines <<< "$rows"
  for line in "${lines[@]}"; do
    IFS='|' read -r generation status in_window until <<< "$line"
    [ -n "$generation" ] || continue
    if ! [[ "$generation" =~ ^[0-9]+$ ]]; then
      echo "Unerwartete Generationsnummer: $generation" >&2
      return 1
    fi
    if [ "$in_window" = t ]; then
      echo "" >&2
      echo "    WARNUNG: Der bisherige Dateisystem-Bestand (Generation g$generation) ist noch in der Rückfallfrist" >&2
      echo "    bis $until UTC. Ab dieser Version gibt es keinen Rückweg mehr auf das Dateisystem; vor dem Update" >&2
      echo "    muss der Bestand bereinigt werden. Bereinigt werden nur Dateien, deren Kopie in S3 die" >&2
      echo "    Erstmigration verifiziert hat. Ohne Bestätigung bricht das Update ab und das bisherige" >&2
      echo "    Release läuft weiter." >&2
      if ! storage_gate_confirm; then
        echo "Update abgebrochen: Rückfallfrist nicht übersprungen. Nach ihrem Ablauf erneut deployen." >&2
        return 1
      fi
    elif [ "$status" = retained ]; then
      echo "    Rückfallfrist der Dateisystem-Generation g$generation ist abgelaufen - Bestand wird bereinigt."
    else
      echo "    Bereinigung der Dateisystem-Generation g$generation läuft bereits ($status)."
    fi
    [ "$status" = retained ] && request+=("$generation")
  done

  local generation_id
  for generation_id in ${request[@]+"${request[@]}"}; do
    # Wie storage_migration_service.request_generation_purge, aber ohne Frist (bewusst übersprungen).
    storage_gate_sql "UPDATE storage_generation SET status = 'purge_requested', retain_until = LEAST(retain_until, NOW()), purge_requested_by = 'deploy.sh', purge_requested_at = NOW(), purge_error = NULL WHERE generation = $((generation_id)) AND status = 'retained' AND profile_id IN (SELECT id FROM storage_profile WHERE provider = 'filesystem')" > /dev/null || return 1
  done

  echo "    Warte auf die Bereinigung durch den storage-worker des bisherigen Releases (max. ${timeout}s) ..."
  local waited=0 remaining errors
  while :; do
    remaining="$(storage_gate_sql "SELECT count(*) FROM storage_generation g JOIN storage_profile p ON p.id = g.profile_id WHERE p.provider = 'filesystem' AND g.status NOT IN ('purged', 'abandoned')")" || return 1
    [ "$remaining" = 0 ] && break
    errors="$(storage_gate_sql "SELECT string_agg('g' || g.generation || ': ' || g.purge_error, '; ') FROM storage_generation g JOIN storage_profile p ON p.id = g.profile_id WHERE p.provider = 'filesystem' AND g.purge_error IS NOT NULL AND g.status NOT IN ('purged', 'abandoned')")" || return 1
    if [ -n "$errors" ]; then
      echo "    Bereinigung meldet einen Fehler (wird wiederholt): $errors" >&2
    fi
    if [ "$waited" -ge "$timeout" ]; then
      echo "Update abgebrochen: die Bereinigung ist nach ${timeout}s nicht fertig. Läuft der storage-worker?" >&2
      echo "Fortschritt im Adminportal (System → Storage); danach erneut deployen." >&2
      return 1
    fi
    sleep "$STORAGE_GATE_POLL_SECONDS"
    waited=$((waited + STORAGE_GATE_POLL_SECONDS))
  done
  echo "    Dateisystem-Bestand bereinigt."
}

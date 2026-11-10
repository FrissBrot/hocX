# shellcheck shell=bash
# Hauptversions-Upgrade der Datenbank (PostgreSQL 16 -> 18) für deploy.sh und dev.sh.
#
# Ab hocX 1.2.0 läuft der Dienst `db` mit PostgreSQL 18 auf dem Volume `postgres18_data`
# (gemountet unter /var/lib/postgresql, Datenverzeichnis /var/lib/postgresql/18/docker wie im
# offiziellen Image ab 18). Bis 1.1.x lag ein PostgreSQL-16-Cluster im Volume `postgres_data`.
# Ein Cluster einer älteren Hauptversion startet unter 18 nicht; Daten wandern deshalb per
# pg_dumpall (alter Server) -> psql (neuer Server) in das neue Volume.
#
# Ablauf (pg_upgrade_major_if_needed):
#   1. Altes Volume ohne fertiges neues Volume? Sonst nichts zu tun.
#   2. Alle Container des Projekts ausser Traefik und lokalem S3 stoppen (keine Schreibzugriffe).
#   3. Alten und neuen Server als Wegwerf-Container ohne Netz starten, Dump direkt streamen
#      (kein unverschlüsselter Dump auf der Platte).
#   4. Datenbanken, Rollen und die exakte Zeilenzahl jeder Tabelle vergleichen, Statistiken
#      neu erheben, Abschlussmarke ins neue Volume schreiben.
# Das alte Volume wird nur gelesen und nie gelöscht: es bleibt der Rückweg, bis es von Hand
# entfernt wird. Schlägt ein Schritt fehl, wird das halb gefüllte neue Volume entfernt und
# die gestoppten Container laufen wieder wie vorher.

PG_UPGRADE_LEGACY_IMAGE="postgres:16@sha256:d4d4f1579fcfba19c2257326f6a93f4bcf677a430619f084ced704e18eb428ce"
PG_UPGRADE_LEGACY_VOLUME_KEY=postgres_data
PG_UPGRADE_TARGET_VOLUME_KEY=postgres18_data
PG_UPGRADE_TARGET_MAJOR=18
PG_UPGRADE_MARKER=.hocx-pg-upgrade-complete
# Nach einem erfolgreichen Upgrade: die dafür gestoppten Container (IDs). Der Aufrufer kann sie
# wieder starten, falls danach etwas scheitert (alte App läuft auch mit PostgreSQL 18).
PG_UPGRADE_STOPPED_CONTAINERS=()

# Volume eines Compose-Projekts über die Labels, die Compose selbst setzt (unabhängig davon,
# ob ein eigener Name konfiguriert ist).
pg_upgrade_volume_of() {
  docker volume ls -q --filter "label=com.docker.compose.project=$1" --filter "label=com.docker.compose.volume=$2" | head -n 1
}

# Zeilenzahl jeder Tabelle, Datenbanken und Rollen eines Servers - muss vor und nach dem
# Upgrade identisch sein. Superuser umgeht RLS, die Zählung ist also vollständig.
pg_upgrade_fingerprint() {
  local container="$1" superuser="$2" database="$3"
  docker exec "$container" psql -X -At -v ON_ERROR_STOP=1 -U "$superuser" -d postgres -c \
    "SELECT 'db ' || datname FROM pg_database WHERE datname NOT IN ('template0') ORDER BY 1" || return 1
  docker exec "$container" psql -X -At -v ON_ERROR_STOP=1 -U "$superuser" -d postgres -c \
    "SELECT 'role ' || rolname || ' ' || rolsuper || rolcanlogin || rolbypassrls FROM pg_roles WHERE rolname !~ '^pg_' ORDER BY 1" || return 1
  docker exec "$container" psql -X -At -v ON_ERROR_STOP=1 -U "$superuser" -d "$database" -c \
    "SELECT 'table ' || n.nspname || '.' || c.relname || ' ' ||
            (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', n.nspname, c.relname), false, true, '')))[1]::text
       FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
      WHERE c.relkind IN ('r', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema') AND n.nspname !~ '^pg_toast'
      ORDER BY 1" || return 1
}

# Kennung und letzter Checkpoint des alten Clusters (nur lesend aus dem Volume). Die
# Abschlussmarke hält diesen Stand fest: lief danach wieder PostgreSQL 16 auf dem alten Volume
# (Rückweg auf 1.1.x), weicht er ab, und das neue Volume ist veraltet.
pg_upgrade_legacy_state() {
  docker run --rm --pull missing --network none -v "$1:/old:ro" --entrypoint sh "$PG_UPGRADE_LEGACY_IMAGE" -c \
    'pg_controldata /old | sed -n "s/^Database system identifier: *//p; s/^Latest checkpoint location: *//p" | tr "\n" " "'
}

pg_upgrade_wait() {
  local container="$1" superuser="$2" host_args="$3" _
  for _ in $(seq 1 90); do
    # shellcheck disable=SC2086 # host_args ist leer oder "-h 127.0.0.1"
    if docker exec "$container" pg_isready -q $host_args -U "$superuser" -d postgres > /dev/null 2>&1; then
      return 0
    fi
    if [ "$(docker inspect -f '{{.State.Running}}' "$container" 2> /dev/null)" != true ]; then
      break
    fi
    sleep 2
  done
  echo "    PostgreSQL in $container ist nicht bereit geworden:" >&2
  docker logs --tail 30 "$container" >&2 2> /dev/null || true
  return 1
}

# Aufruf: pg_upgrade_major_if_needed <compose-projekt> <superuser> <datenbank> <ziel-image>
# Rückgabe 0: nichts zu tun oder Upgrade erfolgreich (App-Container sind dann gestoppt und
# werden vom Aufrufer neu gestartet). Rückgabe 1: Upgrade nicht möglich/fehlgeschlagen,
# alter Zustand wiederhergestellt.
pg_upgrade_major_if_needed() {
  local project="$1" superuser="$2" database="$3" target_image="$4"
  local legacy target target_created=false legacy_version target_state
  local old_container="${project}-pgupgrade-old" new_container="${project}-pgupgrade-new"
  local -a stopped=()

  legacy="$(pg_upgrade_volume_of "$project" "$PG_UPGRADE_LEGACY_VOLUME_KEY")"
  [ -n "$legacy" ] || return 0

  if [[ ! "$superuser" =~ ^[a-z_][a-z0-9_]{0,62}$ ]] || [[ ! "$database" =~ ^[a-z_][a-z0-9_]{0,62}$ ]]; then
    echo "POSTGRES_USER/POSTGRES_DB muessen fuer das Datenbank-Upgrade einfache Namen sein (a-z, 0-9, _)." >&2
    return 1
  fi

  target="$(pg_upgrade_volume_of "$project" "$PG_UPGRADE_TARGET_VOLUME_KEY")"
  if [ -n "$target" ]; then
    target_state="$(docker run --rm --pull never --network none -v "$target:/t:ro" --entrypoint sh "$target_image" -c \
      "if [ -f /t/$PG_UPGRADE_MARKER ]; then echo done; sed -n 's/^legacy=//p' /t/$PG_UPGRADE_MARKER; elif [ -f /t/$PG_UPGRADE_TARGET_MAJOR/docker/PG_VERSION ]; then echo data; else echo empty; fi")" || return 1
    case "$target_state" in
      done*)
        local recorded current
        recorded="$(printf '%s\n' "$target_state" | sed -n 2p)"
        current="$(pg_upgrade_legacy_state "$legacy")" || return 1
        if [ -n "$current" ] && [ "$recorded" != "$current" ]; then
          echo "Das alte Volume $legacy wurde nach dem Upgrade weiter benutzt (z. B. Rueckweg auf 1.1.x); $target ist veraltet." >&2
          echo "Neueren Stand pruefen. Sollen die Daten aus $legacy gelten: docker volume rm $target - danach erneut deployen (Upgrade laeuft neu)." >&2
          return 1
        fi
        echo "    Datenbank laeuft auf PostgreSQL $PG_UPGRADE_TARGET_MAJOR; das alte Volume $legacy kann nach einer Pruefung entfernt werden (docker volume rm $legacy)."
        return 0
        ;;
      data)
        echo "Das Volume $target enthaelt bereits eine Datenbank, aber kein abgeschlossenes Upgrade aus $legacy." >&2
        echo "Entweder ein frueherer Upgrade-Versuch wurde abgebrochen oder der Stack lief ohne deploy.sh/dev.sh mit PostgreSQL $PG_UPGRADE_TARGET_MAJOR." >&2
        echo "Inhalt pruefen; ist er entbehrlich: docker volume rm $target - danach erneut starten. Die alten Daten in $legacy sind unveraendert." >&2
        return 1
        ;;
    esac
  fi

  legacy_version="$(docker run --rm --pull missing --network none -v "$legacy:/old:ro" --entrypoint sh "$PG_UPGRADE_LEGACY_IMAGE" -c \
    'cat /old/PG_VERSION 2> /dev/null || true')" || return 1
  case "$legacy_version" in
    "") return 0 ;;
    16) ;;
    *)
      echo "Unerwartete PostgreSQL-Version im Volume $legacy: $legacy_version (erwartet 16)." >&2
      return 1
      ;;
  esac

  echo "==> Datenbank-Upgrade PostgreSQL $legacy_version -> $PG_UPGRADE_TARGET_MAJOR ($legacy -> ${target:-${project}_$PG_UPGRADE_TARGET_VOLUME_KEY})"
  local legacy_kb available_kb docker_root
  legacy_kb="$(docker run --rm --pull never --network none -v "$legacy:/old:ro" --entrypoint du "$PG_UPGRADE_LEGACY_IMAGE" -sk /old | awk '{print $1}')" || return 1
  docker_root="$(docker info --format '{{.DockerRootDir}}' 2> /dev/null || true)"
  available_kb="$(df -Pk "${docker_root:-/}" 2> /dev/null | awk 'NR == 2 {print $4}' || true)"
  if [[ "$available_kb" =~ ^[0-9]+$ ]] && [ "$available_kb" -lt $((legacy_kb + legacy_kb / 2 + 1048576)) ]; then
    echo "Zu wenig freier Speicher fuer das Datenbank-Upgrade: ${available_kb} KiB frei, benoetigt etwa $((legacy_kb + legacy_kb / 2 + 1048576)) KiB." >&2
    return 1
  fi

  pg_upgrade_cleanup() {
    docker rm -f "$old_container" "$new_container" > /dev/null 2>&1 || true
  }
  pg_upgrade_fail() {
    echo "Datenbank-Upgrade fehlgeschlagen: $1" >&2
    pg_upgrade_cleanup
    if [ "$target_created" = true ]; then
      docker volume rm "$target" > /dev/null 2>&1 || echo "    Halb gefuelltes Volume $target bitte von Hand entfernen." >&2
    fi
    if [ "${#stopped[@]}" -gt 0 ]; then
      echo "    Starte die vorher laufenden Container wieder." >&2
      docker start "${stopped[@]}" > /dev/null || echo "    Neustart fehlgeschlagen; bitte pruefen: docker ps -a" >&2
    fi
    echo "    Die bisherige Datenbank im Volume $legacy ist unveraendert." >&2
    return 1
  }

  local id service
  while read -r id service; do
    case "$service" in
      traefik|local-s3|"") ;;
      *) stopped+=("$id") ;;
    esac
  done < <(docker ps --filter "label=com.docker.compose.project=$project" --format '{{.ID}} {{.Label "com.docker.compose.service"}}')
  if [ "${#stopped[@]}" -gt 0 ]; then
    echo "    Stoppe ${#stopped[@]} Container des Projekts (Wartungsfenster beginnt)"
    docker stop -t 60 "${stopped[@]}" > /dev/null || { pg_upgrade_fail "Container liessen sich nicht stoppen"; return 1; }
  fi
  pg_upgrade_cleanup

  if [ -z "$target" ]; then
    target="${project}_$PG_UPGRADE_TARGET_VOLUME_KEY"
    docker volume create --label "com.docker.compose.project=$project" \
      --label "com.docker.compose.volume=$PG_UPGRADE_TARGET_VOLUME_KEY" "$target" > /dev/null ||
      { pg_upgrade_fail "Volume $target liess sich nicht anlegen"; return 1; }
    target_created=true
  fi

  echo "    Starte PostgreSQL $legacy_version (alte Daten) und $PG_UPGRADE_TARGET_MAJOR (neues Volume) ohne Netzwerk"
  docker run -d --name "$old_container" --pull never --network none \
    -v "$legacy:/var/lib/postgresql/data" "$PG_UPGRADE_LEGACY_IMAGE" > /dev/null ||
    { pg_upgrade_fail "alter Server startet nicht"; return 1; }
  # Das Initialpasswort ist nur ein Platzhalter: der Dump setzt Passwort-Hashes aller Rollen,
  # auch des Superusers, auf die bisherigen Werte.
  docker run -d --name "$new_container" --pull never --network none \
    -e POSTGRES_USER="$superuser" -e POSTGRES_DB=postgres -e POSTGRES_PASSWORD="$(openssl rand -hex 24)" \
    -v "$target:/var/lib/postgresql" "$target_image" > /dev/null ||
    { pg_upgrade_fail "neuer Server startet nicht"; return 1; }
  pg_upgrade_wait "$old_container" "$superuser" "" || { pg_upgrade_fail "alter Server nicht bereit"; return 1; }
  # Über TCP erst nach Abschluss der Initialisierung erreichbar (der Init-Server lauscht nur lokal).
  pg_upgrade_wait "$new_container" "$superuser" "-h 127.0.0.1" || { pg_upgrade_fail "neuer Server nicht bereit"; return 1; }

  local before after
  before="$(pg_upgrade_fingerprint "$old_container" "$superuser" "$database")" ||
    { pg_upgrade_fail "Bestandsaufnahme der alten Datenbank"; return 1; }

  echo "    Uebertrage Rollen und Datenbanken (pg_dumpall -> psql)"
  # CREATE ROLE des Superusers entfällt, weil es ihn im neuen Cluster schon gibt; das folgende
  # ALTER ROLE übernimmt Attribute und Passwort-Hash.
  docker exec "$old_container" pg_dumpall -U "$superuser" |
    sed -E "/^CREATE ROLE \"?$superuser\"?;$/d" |
    docker exec -i "$new_container" psql -X -q -v ON_ERROR_STOP=1 -U "$superuser" -d postgres > /dev/null
  local -a status=("${PIPESTATUS[@]}")
  if [ "${status[0]}" -ne 0 ] || [ "${status[1]}" -ne 0 ] || [ "${status[2]}" -ne 0 ]; then
    pg_upgrade_fail "Dump/Restore (Exitcodes ${status[*]})"
    return 1
  fi

  docker exec "$new_container" vacuumdb -q -U "$superuser" --all --analyze-only ||
    { pg_upgrade_fail "Statistiken (vacuumdb)"; return 1; }
  after="$(pg_upgrade_fingerprint "$new_container" "$superuser" "$database")" ||
    { pg_upgrade_fail "Bestandsaufnahme der neuen Datenbank"; return 1; }
  if [ "$before" != "$after" ]; then
    diff <(printf '%s\n' "$before") <(printf '%s\n' "$after") | head -n 20 >&2 || true
    pg_upgrade_fail "Datenbanken, Rollen oder Zeilenzahlen weichen ab"
    return 1
  fi
  echo "    Pruefung: $(printf '%s\n' "$after" | grep -c '^table ') Tabellen, Zeilenzahlen identisch"

  local legacy_state
  docker stop -t 60 "$old_container" > /dev/null || { pg_upgrade_fail "alter Server liess sich nicht sauber beenden"; return 1; }
  legacy_state="$(pg_upgrade_legacy_state "$legacy")" && [ -n "$legacy_state" ] ||
    { pg_upgrade_fail "Zustand des alten Clusters (pg_controldata)"; return 1; }
  docker exec "$new_container" sh -c "printf 'from=%s\nlegacy=%s\nat=%s\n' '$legacy_version' '$legacy_state' \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" > /var/lib/postgresql/$PG_UPGRADE_MARKER" ||
    { pg_upgrade_fail "Abschlussmarke"; return 1; }
  docker stop -t 60 "$new_container" > /dev/null || { pg_upgrade_fail "neuer Server liess sich nicht sauber beenden"; return 1; }
  pg_upgrade_cleanup
  # shellcheck disable=SC2034 # liest der Aufrufer (deploy.sh)
  PG_UPGRADE_STOPPED_CONTAINERS=("${stopped[@]}")
  echo "    Datenbank-Upgrade abgeschlossen. Altes Volume bleibt als Rueckweg erhalten: $legacy"
  return 0
}

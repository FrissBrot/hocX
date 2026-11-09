#!/usr/bin/env bash
set -euo pipefail

# Abnahme eines Candidates auf dem Test-Host: Server- und Browser-Prüfungen, die in der CI nicht
# möglich sind (echtes Traefik, Release-Images, echte Datenbank). Auswertung und Ablauf: Skill
# .claude/skills/testhost-abnahme/SKILL.md. Ergebnisse: $TH_OUT/results.jsonl + shots/.
#
# Usage: scripts/testhost/abnahme.sh [server|browser|all]
# Zugangsdaten stehen in ~/.hocx-testhost.env (Vorlage im Skill), nie im Repository.

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MODE="${1:-all}"
case "$MODE" in
  server | browser | all) ;;
  *)
    echo "Usage: $0 [server|browser|all]" >&2
    exit 2
    ;;
esac

CREDENTIALS="${TH_CREDENTIALS:-$HOME/.hocx-testhost.env}"
if [ -f "$CREDENTIALS" ]; then
  # Rechte prüfen, bevor die Datei gelesen wird: sie enthält Passwörter
  if [ -n "$(find "$CREDENTIALS" -perm /077)" ]; then
    echo "$CREDENTIALS ist für andere lesbar: chmod 600 $CREDENTIALS" >&2
    exit 2
  fi
fi

# Nie auf Prod: Die Prüfungen laden die Instanz und legen Testdaten an.
HOST_MARKER="$(cat /etc/hocx/environment 2>/dev/null || true)"
if [ "$HOST_MARKER" = prod ] || [ "$HOST_MARKER" = production ]; then
  echo "Dieser Host ist als Prod markiert, die Abnahme läuft nur auf dem Test-Host." >&2
  exit 2
fi

env_value() {
  [ -f "$REPO_DIR/.env" ] || return 0
  # Nur einzelne, nicht geheime Werte; ein fehlender Eintrag ist kein Fehler (pipefail).
  { grep -E "^$1=" "$REPO_DIR/.env" || true; } | tail -1 | cut -d= -f2- | tr -d '"'
}

TH_PROJECT="${TH_PROJECT:-hocx-test}"
TH_BASE="${TH_BASE:-https://$(env_value TRAEFIK_DOMAIN)}"
TH_OUT="${TH_OUT:-$HOME/hocx-testhost-results/$(date +%Y%m%d-%H%M%S)}"
PLAYWRIGHT_VERSION="$(sed -n 's/.*"@playwright\/test": "^\{0,1\}\([0-9.]*\)".*/\1/p' "$REPO_DIR/frontend/package.json")"
mkdir -p "$TH_OUT/shots"
export TH_OUT TH_PROJECT

record() {
  python3 - "$TH_OUT/results.jsonl" "$1" "$2" "$3" <<'PY'
import json, sys
path, check, status, summary = sys.argv[1:5]
with open(path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"id": check, "status": status, "summary": summary}, ensure_ascii=False) + "\n")
print(f"[{status}] {check}: {summary}")
PY
}

container_of() {
  docker ps -q --filter "label=com.docker.compose.project=$TH_PROJECT" --filter "label=com.docker.compose.service=$1" | head -1
}

server_checks() {
  local db frontend_list names state unhealthy restarted image_tag expected running
  db="$(container_of db)"
  if [ -z "$db" ]; then
    record TH-01 FAIL "Kein laufender db-Container im Projekt $TH_PROJECT (TH_PROJECT prüfen)"
    return 0
  fi
  sql() { docker exec -i "$db" sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA' <<<"$1"; }

  # TH-01: Container gesund und aus dem erwarteten Candidate
  names="$(docker ps --filter "label=com.docker.compose.project=$TH_PROJECT" --format '{{.Names}}')"
  unhealthy=""
  restarted=""
  while read -r name; do
    [ -n "$name" ] || continue
    state="$(docker inspect "$name" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} {{.RestartCount}} {{.State.OOMKilled}}')"
    case "$state" in
      unhealthy* | starting*) unhealthy="$unhealthy $name" ;;
    esac
    case "$state" in
      *" 0 false") ;;
      *) restarted="$restarted $name(${state#* })" ;;
    esac
  done <<<"$names"
  expected="$(env_value HOCX_VERSION)"
  running="$(docker inspect "$(container_of backend)" --format '{{.Config.Image}}' 2>/dev/null || true)"
  image_tag="${running##*:}"
  if [ -n "$unhealthy" ]; then
    record TH-01 FAIL "Nicht gesund:$unhealthy"
  elif [ -n "$expected" ] && [ "$image_tag" != "$expected" ]; then
    record TH-01 FAIL "Backend läuft mit $image_tag, .env verlangt $expected"
  else
    record TH-01 PASS "Alle Container gesund, Backend-Image $image_tag"
  fi

  # TH-02: Migrationen auf dem Stand des Checkouts
  local current head
  current="$(sql 'select version_num from alembic_version' | head -1)"
  # Reine Merge-Köpfe gibt es hier nicht: Die Kette ist linear, die höchste Nummer ist der Kopf.
  head="$(find "$REPO_DIR/backend/alembic/versions" -maxdepth 1 -name '[0-9]*.py' -printf '%f\n' | sort | tail -1 | sed 's/\.py$//')"
  if [ "$current" = "$head" ]; then
    record TH-02 PASS "Migration $current ist der Kopf des Checkouts"
  else
    record TH-02 FAIL "Datenbank auf $current, Checkout auf $head (Deploy-Code und Image passen nicht zusammen?)"
  fi

  # TH-03: 0166 wirksam (überflüssige Indizes weg, record_job_run mit max(id))
  local leftovers function_ok
  leftovers="$(sql "select string_agg(indexname, ', ') from pg_indexes where indexname in ('idx_protocol_element_block_configuration_gin','idx_protocol_element_block_sort','idx_protocol_element_protocol_sort','idx_audit_log_tenant')")"
  function_ok="$(sql "select prosrc ilike '%max(r2.id)%' from pg_proc where proname = 'record_job_run'")"
  if [ -n "$leftovers" ]; then
    record TH-03 FAIL "Indizes noch vorhanden: $leftovers"
  elif [ "$function_ok" != t ]; then
    record TH-03 FAIL "record_job_run nutzt nicht max(id)"
  else
    record TH-03 PASS "Überflüssige Indizes entfernt, record_job_run mit max(id)"
  fi

  # TH-04: Jobs laufen weiter und zügig (record_job_run wurde umgeschrieben)
  local job_rows job_failed
  job_rows="$(sql "select count(*) from system_job_status where last_finished_at > now() - interval '1 hour'" 2>/dev/null || echo error)"
  job_failed="$(sql "select string_agg(job_name, ', ') from system_job_status where last_status = 'failure' and last_finished_at > now() - interval '1 hour'" 2>/dev/null || echo error)"
  if [ "$job_rows" = error ] || [ "$job_failed" = error ]; then
    record TH-04 WARN "system_job_status nicht auswertbar, Spalten prüfen"
  elif [ "$job_rows" = 0 ]; then
    record TH-04 FAIL "Kein Job hat in der letzten Stunde seinen Lauf erfasst"
  elif [ -n "$job_failed" ]; then
    record TH-04 WARN "$job_rows Jobs aktiv, zuletzt fehlgeschlagen: $job_failed"
  else
    record TH-04 PASS "$job_rows Jobs in der letzten Stunde erfolgreich erfasst"
  fi

  # TH-05: neue Postgres-Parameter aktiv
  local settings
  settings="$(sql "select string_agg(name || '=' || setting, ' ' order by name) from pg_settings where name in ('random_page_cost','effective_io_concurrency','max_wal_size','pg_stat_statements.track')")"
  case "$settings" in
    *"effective_io_concurrency=200 "*"max_wal_size=2048 "*"pg_stat_statements.track=top "*"random_page_cost=1.1"*)
      record TH-05 PASS "$settings"
      ;;
    *) record TH-05 FAIL "Parameter nicht wie erwartet: $settings" ;;
  esac

  # TH-06: Stabilität: Neustarts/OOM der Container, Tracebacks seit dem Start
  local tracebacks
  tracebacks="$(docker logs --since 2h "$(container_of backend)" 2>&1 | grep -c '^Traceback' || true)"
  if [ -n "$restarted" ]; then
    record TH-06 WARN "Neustarts oder OOM (Neustarts, OOMKilled):$restarted; Backend-Tracebacks 2 h: $tracebacks"
  elif [ "$tracebacks" -gt 0 ]; then
    record TH-06 WARN "Keine Neustarts, aber $tracebacks Backend-Tracebacks in 2 h"
  else
    record TH-06 PASS "Keine Neustarts, kein OOM, keine Backend-Tracebacks in 2 h"
  fi

  # TH-07: Speicher der Frontends im Normalbetrieb (compress: false, Bereichs-CSS)
  frontend_list="$(docker stats --no-stream --format '{{.Name}}={{.MemUsage}}' | grep -E "^$TH_PROJECT.*frontend" | cut -d' ' -f1 | tr '\n' ' ' || true)"
  record TH-07 INFO "Speicher Frontends: ${frontend_list:-unbekannt}"
}

browser_checks() {
  if [ -z "$TH_BASE" ] || [ "$TH_BASE" = "https://" ]; then
    record TH-20 FAIL "TH_BASE unbekannt: weder gesetzt noch TRAEFIK_DOMAIN in .env"
    return 0
  fi
  # Als aufrufender Benutzer: Ergebnisdateien gehören sonst root, und HOME ist im Image nicht schreibbar.
  local args=(--rm --network host --memory="${TH_MEMORY:-3g}" --user "$(id -u):$(id -g)" -e HOME=/tmp
    -v "$REPO_DIR/scripts/testhost:/checks:ro" -v "$REPO_DIR/frontend/app/styles:/repo/frontend/app/styles:ro"
    -v "$REPO_DIR/frontend/messages:/repo/frontend/messages:ro" -v "$REPO_DIR/i18n:/repo/i18n:ro" -v "$TH_OUT:/out"
    -e TH_BASE -e TH_ADMIN_BASE -e TH_WRITE -e TH_PROTOCOL_ID -e TH_MAX_PAGES -e TH_MAX_CLICKS -e TH_ONLY
    -e TH_OUT=/out -e TH_REPO=/repo)
  [ -f "$CREDENTIALS" ] && args+=(--env-file "$CREDENTIALS")
  # Private Bindung ohne DNS: TH_ADD_HOSTS="test.hocx.ch:127.0.0.1 admin.test.hocx.ch:127.0.0.1"
  local entry
  for entry in ${TH_ADD_HOSTS:-}; do
    args+=(--add-host "$entry")
  done
  export TH_BASE TH_ADMIN_BASE="${TH_ADMIN_BASE:-}" TH_WRITE="${TH_WRITE:-0}" TH_PROTOCOL_ID="${TH_PROTOCOL_ID:-}" TH_ONLY="${TH_ONLY:-}"
  export TH_MAX_PAGES="${TH_MAX_PAGES:-70}" TH_MAX_CLICKS="${TH_MAX_CLICKS:-14}"
  # Die Modulauflösung geht vom Skriptordner aus, darum läuft eine Kopie neben node_modules.
  docker run "${args[@]}" "mcr.microsoft.com/playwright:v$PLAYWRIGHT_VERSION-noble" sh -c \
    "mkdir -p /tmp/pw && cd /tmp/pw && npm init -y >/dev/null && npm install --no-audit --no-fund --silent playwright@$PLAYWRIGHT_VERSION >/dev/null && cp /checks/browser-checks.mjs . && node browser-checks.mjs" \
    || record TH-29 FAIL "Browser-Prüfungen abgebrochen, Exit $? (Protokoll oben)"
}

if [ "$MODE" != browser ]; then
  server_checks
fi
if [ "$MODE" != server ]; then
  browser_checks
fi

echo
echo "Ergebnisse: $TH_OUT/results.jsonl"
python3 - "$TH_OUT/results.jsonl" <<'PY'
import collections, json, sys
counts = collections.Counter(json.loads(line)["status"] for line in open(sys.argv[1], encoding="utf-8"))
print("Zusammenfassung:", ", ".join(f"{key} {value}" for key, value in sorted(counts.items())))
sys.exit(1 if counts["FAIL"] else 0)
PY

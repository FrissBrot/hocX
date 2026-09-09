#!/usr/bin/env bash
set -uo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ACTION="${1:-all}"
KEEP_CONTAINERS="${KEEP_CONTAINERS:-0}"

TEST_DC=(docker compose -p hocx-tests -f "$REPO_DIR/docker-compose.tests.yml" --project-directory "$REPO_DIR")

if [[ -t 1 && "${NO_COLOR:-0}" != "1" ]]; then
  BLUE=$'\033[1;34m'; GREEN=$'\033[1;32m'; RED=$'\033[1;31m'; YELLOW=$'\033[1;33m'; RESET=$'\033[0m'
else
  BLUE=""; GREEN=""; RED=""; YELLOW=""; RESET=""
fi

declare -a SUITE_NAMES=()
declare -a SUITE_RESULTS=()
declare -a SUITE_DURATIONS=()

usage() {
  cat <<EOF
Aufruf: $0 [backend|abgabebox-backend|frontend|abgabebox-frontend|scripts|e2e|unit|all]

  unit  Alle Unit-/Integrations- und Skript-Tests, ohne Browser-E2E
  all   Wirklich alle Tests inklusive Browser-E2E (Standard)

Optionale Umgebungsvariablen:
  KEEP_CONTAINERS=1  Test-Container/Volumes nach dem Lauf behalten
  NO_COLOR=1         Farbausgabe deaktivieren
EOF
}

cleanup() {
  if [[ "$KEEP_CONTAINERS" != "1" ]]; then
    printf '\n%sBereinige Test-Container und Volumes ...%s\n' "$BLUE" "$RESET"
    "${TEST_DC[@]}" --profile tests down --volumes --remove-orphans || true
  fi
}

require_tools() {
  command -v docker >/dev/null 2>&1 || { echo "Fehlt: docker" >&2; exit 1; }
  docker compose version >/dev/null 2>&1 || { echo "Fehlt: docker compose" >&2; exit 1; }
  docker info >/dev/null 2>&1 || { echo "Docker-Daemon ist nicht erreichbar." >&2; exit 1; }
}

show_containers() {
  printf '%sContainer-Status:%s\n' "$BLUE" "$RESET"
  "${TEST_DC[@]}" --profile tests ps -a || true
}

run_suite() {
  local name="$1"
  shift
  local started ended status
  started=$(date +%s)
  printf '\n%s================================================================%s\n' "$BLUE" "$RESET"
  printf '%sSTART  %s%s\n' "$BLUE" "$name" "$RESET"
  printf '%sBefehl:%s ' "$YELLOW" "$RESET"
  printf '%q ' "$@"
  printf '\n'

  "$@"
  status=$?
  ended=$(date +%s)
  SUITE_NAMES+=("$name")
  SUITE_DURATIONS+=("$((ended - started))")
  if (( status == 0 )); then
    SUITE_RESULTS+=("BESTANDEN")
    printf '%sENDE   %s: BESTANDEN (%ss)%s\n' "$GREEN" "$name" "$((ended - started))" "$RESET"
  else
    SUITE_RESULTS+=("FEHLGESCHLAGEN ($status)")
    printf '%sENDE   %s: FEHLGESCHLAGEN, Exit-Code %s (%ss)%s\n' "$RED" "$name" "$status" "$((ended - started))" "$RESET"
  fi
  show_containers
  return 0
}

run_compose_suite() {
  local label="$1" service="$2"
  run_suite "$label" "${TEST_DC[@]}" --profile tests run --rm --build "$service"
}

run_script_tests() {
  run_suite "Skripte: Env-Loader" "$REPO_DIR/scripts/tests/test_env.sh"
  run_suite "Skripte: Release-Konfiguration" "$REPO_DIR/scripts/tests/test_release_config.sh"
}

run_e2e() {
  run_suite "Browser-E2E (Playwright)" "$REPO_DIR/scripts/e2e.sh" all
}

print_summary() {
  local passed=0 failed=0 i result
  printf '\n%s===================== GESAMTERGEBNIS =====================%s\n' "$BLUE" "$RESET"
  printf '%-38s %-24s %s\n' "Testsuite" "Ergebnis" "Dauer"
  printf '%-38s %-24s %s\n' "--------------------------------------" "------------------------" "------"
  for i in "${!SUITE_NAMES[@]}"; do
    result="${SUITE_RESULTS[$i]}"
    printf '%-38s %-24s %ss\n' "${SUITE_NAMES[$i]}" "$result" "${SUITE_DURATIONS[$i]}"
    if [[ "$result" == "BESTANDEN" ]]; then ((passed += 1)); else ((failed += 1)); fi
  done
  printf '\nSuites: %s bestanden, %s fehlgeschlagen, %s insgesamt.\n' "$passed" "$failed" "$((passed + failed))"
  printf 'Die genaue Anzahl einzelner Tests steht in den pytest/Vitest/Playwright-Zusammenfassungen oben.\n'
  (( failed == 0 ))
}

run_unit() {
  run_compose_suite "Backend (pytest)" backend-test
  run_compose_suite "Abgabebox-Backend (pytest)" abgabebox-backend-test
  run_compose_suite "Frontend (Vitest)" frontend-test
  run_compose_suite "Abgabebox-Frontend (Vitest)" abgabebox-frontend-test
  run_script_tests
}

case "$ACTION" in
  -h|--help) usage; exit 0 ;;
  backend|abgabebox-backend|frontend|abgabebox-frontend|scripts|e2e|unit|all) ;;
  *) usage >&2; exit 2 ;;
esac

require_tools
trap cleanup EXIT INT TERM

case "$ACTION" in
  backend) run_compose_suite "Backend (pytest)" backend-test ;;
  abgabebox-backend) run_compose_suite "Abgabebox-Backend (pytest)" abgabebox-backend-test ;;
  frontend) run_compose_suite "Frontend (Vitest)" frontend-test ;;
  abgabebox-frontend) run_compose_suite "Abgabebox-Frontend (Vitest)" abgabebox-frontend-test ;;
  scripts) run_script_tests ;;
  e2e) run_e2e ;;
  unit) run_unit ;;
  all) run_unit; run_e2e ;;
esac

print_summary

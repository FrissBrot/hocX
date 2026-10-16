#!/usr/bin/env bash

# Bestimmt Compose-Projekt und -Dateien der hocX-Instanz dieses Checkouts fuer Hilfsskripte
# (backup_db.sh, restore_db.sh, run_job.sh). Frueher riefen diese `docker compose` ohne -p/-f auf
# und trafen nur zufaellig das richtige Projekt, weil der Verzeichnisname `hocX` zu `hocx`
# normalisiert wird (Audit MAIN-OPS-010). Die Zuordnung entspricht deploy.sh/verify_release.sh:
#
#   Host-Marker prod   -> Release-Stack, Projekt hocx
#   Host-Marker test   -> Release-Stack + Test-Overlay, Projekt hocx-test
#   kein Host-Marker   -> Instanz aus dem Quellcode (docker-compose.yml), Projekt aus
#                         HOCX_COMPOSE_PROJECT (Default: hocx, wie bisher implizit). Laeuft die
#                         Instanz ueber scripts/dev.sh, HOCX_COMPOSE_PROJECT=hocx-dev setzen; dann
#                         wird auch docker-compose.dev.yml geladen (wie in dev.sh).
#
# Setzt STACK_KIND (prod|test|server), STACK_PROJECT und das Array STACK_COMPOSE_ARGS.
# Voraussetzung: scripts/lib/env.sh ist geladen (read_host_environment).
# HOCX_HOST_MARKER_FILE ueberschreibt den Pfad der Host-Markierung (nur fuer Skripttests; die
# Markierung wird trotzdem auf Eigentuemer und Rechte geprueft).
resolve_hocx_stack() {
  local repo_dir="$1"
  local marker="${HOCX_HOST_MARKER_FILE:-/etc/hocx/environment}"

  if [ -e "$marker" ] || [ -L "$marker" ]; then
    STACK_KIND="$(read_host_environment "$marker")" || return 1
  else
    STACK_KIND=server
  fi

  case "$STACK_KIND" in
    prod)
      STACK_PROJECT=hocx
      STACK_COMPOSE_ARGS=(
        -f "$repo_dir/docker-compose.release.yml"
        -f "$repo_dir/docker-compose.clamav.yml"
        -f "$repo_dir/docker-compose.traefik.yml"
        --project-directory "$repo_dir"
      )
      ;;
    test)
      STACK_PROJECT=hocx-test
      STACK_COMPOSE_ARGS=(
        -f "$repo_dir/docker-compose.release.yml"
        -f "$repo_dir/docker-compose.clamav.yml"
        -f "$repo_dir/docker-compose.traefik.yml"
        -f "$repo_dir/docker-compose.test.yml"
        --project-directory "$repo_dir"
      )
      ;;
    server)
      STACK_PROJECT="${HOCX_COMPOSE_PROJECT:-hocx}"
      if [[ ! "$STACK_PROJECT" =~ ^[a-z0-9][a-z0-9_-]*$ ]]; then
        echo "Ungueltiger HOCX_COMPOSE_PROJECT: $STACK_PROJECT" >&2
        return 1
      fi
      STACK_COMPOSE_ARGS=(-f "$repo_dir/docker-compose.yml")
      if [ "$STACK_PROJECT" = hocx-dev ]; then
        STACK_COMPOSE_ARGS+=(-f "$repo_dir/docker-compose.dev.yml")
      fi
      STACK_COMPOSE_ARGS+=(--project-directory "$repo_dir")
      ;;
  esac
}

# shellcheck shell=bash
# Traefik-Datei infra/traefik/dynamic/admin-gate.yml (Auth-Audit SEC-AUTH-001, Reviews M1/L4).
# Benutzt von deploy.sh (schreiben) und verify_release.sh (vergleichen).
#
# Inhalt: Middleware admin-gate = Kette aus
#   admin-gate-source  ipAllowList - nur die Quelle des OpenZiti-Tunnels. Er trifft
#                      127.0.0.1:<TRAEFIK_ADMIN_PORT> auf dem Host; über die Docker-Portweiterleitung
#                      sieht Traefik dann die Gateway-Adresse des Netzes "<projekt>_edge" (live
#                      geprüft, docker-proxy). Ein Container im selben Netz, der traefik:8443 direkt
#                      anspricht, kommt mit seiner eigenen Adresse und wird abgewiesen.
#   admin-gate-header  setzt X-Hocx-Admin-Gate auf ADMIN_GATE_SECRET; das Backend nimmt /api/admin nur
#                      damit an (backend/app/core/admin_gate.py).
# Abweichende Tunnel-Endpunkte: HOCX_ADMIN_SOURCE_CIDRS (Komma-Liste, IPv4 mindestens /16, IPv6
# mindestens /48 - nie ein ganzes Netz wie 0.0.0.0/0).
#
# Der Wert steht in einer Dateiprovider-Datei statt in einem Docker-Label (Labels zeigt jedes
# `docker inspect`). Rechte 0640, Besitzer Deploy-Benutzer, Gruppe 5001 (setgid-Verzeichnis):
# Traefik liest über die Gruppe, das Backend (ebenfalls Gruppe 5001) kann sie wegen Sticky-Bit und
# 0640 weder ändern noch ersetzen. Nicht im Repo (.gitignore).

ADMIN_GATE_MIN_PREFIX_V4=16
ADMIN_GATE_MIN_PREFIX_V6=48

admin_source_cidrs() {
  local gateway
  if [ -n "${HOCX_ADMIN_SOURCE_CIDRS:-}" ]; then
    printf '%s\n' "$HOCX_ADMIN_SOURCE_CIDRS"
    return 0
  fi
  gateway="$(docker network inspect "${PROJECT_NAME}_edge" --format '{{range .IPAM.Config}}{{.Gateway}} {{end}}' 2> /dev/null)" || gateway=""
  gateway="${gateway%% *}"
  [ -n "$gateway" ] || return 1
  case "$gateway" in
    *:*) printf '%s/128\n' "$gateway" ;;
    *) printf '%s/32\n' "$gateway" ;;
  esac
}

# Prüft einen CIDR-Eintrag: Format und Mindestpräfix (Review: kein /0, keine Riesennetze).
admin_source_cidr_valid() {
  local cidr="$1" prefix
  prefix="${cidr##*/}"
  if [[ "$cidr" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$ ]]; then
    [ "$prefix" -ge "$ADMIN_GATE_MIN_PREFIX_V4" ] && [ "$prefix" -le 32 ]
  elif [[ "$cidr" =~ ^[0-9a-fA-F:]*:[0-9a-fA-F:.]*/[0-9]{1,3}$ ]]; then
    [ "$prefix" -ge "$ADMIN_GATE_MIN_PREFIX_V6" ] && [ "$prefix" -le 128 ]
  else
    return 1
  fi
}

# Inhalt der Datei auf stdout (für Schreiben und Vergleich).
admin_gate_traefik_content() {
  local cidrs cidr
  local -a cidr_list
  # Nur unkritische Zeichen: der Wert landet in YAML (in einfachen Anführungszeichen).
  if ! [[ "${ADMIN_GATE_SECRET:-}" =~ ^[A-Za-z0-9._~+/=-]{32,}$ ]]; then
    echo "ADMIN_GATE_SECRET fehlt oder ist ungueltig (mindestens 32 Zeichen, nur A-Z a-z 0-9 . _ ~ + / = -)." >&2
    return 1
  fi
  if ! cidrs="$(admin_source_cidrs)"; then
    echo "Quelladresse des Admin-Zugangs nicht ermittelbar (Netz ${PROJECT_NAME}_edge fehlt?); HOCX_ADMIN_SOURCE_CIDRS setzen." >&2
    return 1
  fi
  IFS=',' read -r -a cidr_list <<< "$cidrs"
  [ "${#cidr_list[@]}" -gt 0 ] || return 1
  for cidr in "${cidr_list[@]}"; do
    if ! admin_source_cidr_valid "$cidr"; then
      echo "Ungueltiger Eintrag in den Admin-Quelladressen: $cidr (IPv4 mindestens /$ADMIN_GATE_MIN_PREFIX_V4, IPv6 mindestens /$ADMIN_GATE_MIN_PREFIX_V6)" >&2
      return 1
    fi
  done
  printf '# Automatisch durch scripts/deploy.sh erzeugt (ADMIN_GATE_SECRET). Nicht bearbeiten, nicht committen.\n'
  printf '# Verwendet von den Admin-Routern in docker-compose.release.yml (admin-gate@file).\n'
  printf 'http:\n  middlewares:\n    admin-gate:\n      chain:\n        middlewares:\n'
  printf '          - admin-gate-source\n          - admin-gate-header\n'
  printf '    admin-gate-source:\n      ipAllowList:\n        sourceRange:\n'
  for cidr in "${cidr_list[@]}"; do
    printf "          - '%s'\n" "$cidr"
  done
  printf '    admin-gate-header:\n      headers:\n        customRequestHeaders:\n'
  printf "          X-Hocx-Admin-Gate: '%s'\n" "$ADMIN_GATE_SECRET"
}

# Läuft nach `compose up` (das Netz muss existieren); bis dahin gilt die Datei des letzten Deploys.
write_admin_gate_traefik_config() {
  local dir="$PROJECT_DIR/infra/traefik/dynamic" file temp_file
  file="$dir/admin-gate.yml"
  if [ -L "$dir" ] || [ -L "$file" ]; then
    echo "Runtime-Pfad darf kein Symlink sein: $file" >&2
    return 1
  fi
  # Endung ohne .yml: Traefik ignoriert die halb geschriebene Datei.
  temp_file="$(mktemp "$dir/.admin-gate.tmp.XXXXXX")"
  if ! admin_gate_traefik_content > "$temp_file"; then
    rm -f "$temp_file"
    return 1
  fi
  chmod 640 "$temp_file"
  mv "$temp_file" "$file"
  echo "    Traefik-Admin-Gate: $file"
}

# verify_release.sh (Review L4): Die Datei entspricht genau dem, was deploy.sh aus .env und Netz
# erzeugen würde - eine von dritter Seite veränderte Datei fällt auf.
admin_gate_traefik_config_check() {
  local file="${REPO_DIR:-.}/infra/traefik/dynamic/admin-gate.yml" expected
  expected="$(admin_gate_traefik_content)" || return 1
  if [ ! -r "$file" ] || [ "$(cat "$file")" != "$expected" ]; then
    echo "    admin-gate.yml fehlt oder weicht vom erwarteten Inhalt ab - scripts/deploy.sh erneut ausführen." >&2
    return 1
  fi
}

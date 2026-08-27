#!/usr/bin/env bash

# Configure and validate the server-side GitHub credential without putting it in .env.
# PROJECT_DIR must be set by the caller. GHCR_NAMESPACE is used for registry login.
ensure_github_auth() {
  local api_token="" registry_token="" tools_dir api_file registry_file token_file

  command -v gh > /dev/null 2>&1 || {
    echo "GitHub CLI (gh) fehlt. Provisioning erneut ausfuehren oder gh installieren." >&2
    return 1
  }

  tools_dir="$PROJECT_DIR/.tools"
  api_file="$tools_dir/github-api-token"
  registry_file="$tools_dir/ghcr-read-token"
  mkdir -p "$tools_dir"
  chmod 700 "$tools_dir"
  for token_file in "$api_file" "$registry_file"; do
    if [ -L "$token_file" ]; then
      echo "Token-Datei darf kein Symlink sein: $token_file" >&2
      return 1
    fi
    if [ -e "$token_file" ] && [ "$(stat -c '%u' "$token_file")" != "$EUID" ]; then
      echo "Token-Datei gehoert nicht dem Deploy-Benutzer: $token_file" >&2
      return 1
    fi
  done

  if [ -f "$api_file" ] && [ ! -L "$api_file" ]; then
    chmod 600 "$api_file"
    IFS= read -r api_token < "$api_file"
    export GH_TOKEN="$api_token"
  elif ! gh auth status --hostname github.com > /dev/null 2>&1; then
    if ! exec 8<> /dev/tty; then
      echo "GitHub-Anmeldung fehlt und es ist kein interaktives Terminal verfuegbar." >&2
      return 1
    fi
    echo "==> GitHub-Zugriff einrichten" >&8
    echo "    Empfohlen: Fine-grained PAT nur fuer FrissBrot/hocX mit" >&8
    echo "    Contents/Actions read und Deployments read/write." >&8
    printf "    GitHub API Token: " >&8
    IFS= read -r -s api_token <&8 || return 1
    printf '\n' >&8
    exec 8>&-
    [ -n "$api_token" ] || {
      echo "GitHub-Token darf nicht leer sein." >&2
      return 1
    }
    export GH_TOKEN="$api_token"
  fi

  echo "==> Pruefe GitHub-Token"
  gh api repos/FrissBrot/hocX --jq '.full_name' | grep -Fxq FrissBrot/hocX || {
    echo "Token hat keinen Zugriff auf das Repository FrissBrot/hocX." >&2
    return 1
  }
  gh run list --repo FrissBrot/hocX --limit 1 > /dev/null || {
    echo "Token kann GitHub-Actions-Laeufe nicht lesen." >&2
    return 1
  }
  gh api 'repos/FrissBrot/hocX/deployments?per_page=1' > /dev/null || {
    echo "Token kann GitHub-Deployments nicht lesen." >&2
    return 1
  }

  if [ -n "$api_token" ] && [ ! -f "$api_file" ]; then
    token_file="$(mktemp "$tools_dir/.github-api-token.XXXXXX")"
    printf '%s\n' "$api_token" > "$token_file"
    chmod 600 "$token_file"
    mv "$token_file" "$api_file"
  fi

  if [ -f "$registry_file" ] && [ ! -L "$registry_file" ]; then
    chmod 600 "$registry_file"
    IFS= read -r registry_token < "$registry_file"
  else
    if ! exec 8<> /dev/tty; then
      echo "GHCR-Token fehlt und es ist kein interaktives Terminal verfuegbar." >&2
      return 1
    fi
    echo "==> GHCR-Zugriff einrichten" >&8
    echo "    Classic PAT mit ausschliesslich read:packages verwenden." >&8
    printf "    GHCR Read Token: " >&8
    IFS= read -r -s registry_token <&8 || return 1
    printf '\n' >&8
    exec 8>&-
    [ -n "$registry_token" ] || {
      echo "GHCR-Token darf nicht leer sein." >&2
      return 1
    }
  fi

  printf '%s\n' "$registry_token" | docker login ghcr.io \
    --username "${GHCR_NAMESPACE:-FrissBrot}" \
    --password-stdin > /dev/null || {
      echo "Token konnte nicht fuer GHCR eingerichtet werden (read:packages pruefen)." >&2
      return 1
    }
  if [ ! -f "$registry_file" ]; then
    token_file="$(mktemp "$tools_dir/.ghcr-read-token.XXXXXX")"
    printf '%s\n' "$registry_token" > "$token_file"
    chmod 600 "$token_file"
    mv "$token_file" "$registry_file"
  fi
  registry_token=""
  echo "    GitHub Repository, Actions und Deployments: Zugriff ok"
}

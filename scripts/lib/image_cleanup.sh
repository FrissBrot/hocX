# shellcheck shell=bash
# Alte hocX-Images nach einem erfolgreichen Update entfernen. Jedes Update zieht sechs App-Images
# (ghcr.io/<namespace>/hocx-*), ohne Aufräumen füllten sie mit der Zeit die Platte.
#
# Behalten werden immer:
#   - alle Images, die ein Container verwendet (laufend oder gestoppt),
#   - das aktuelle Release (.releases/current.env),
#   - die Images der letzten KEEP Release-Manifeste (.releases/<version>.env, neueste zuerst) -
#     Ziele für ein manuelles Zurückgehen per HOCX_VERSION (RUNBOOK).
# Entfernt werden nur Images aus ghcr.io/<namespace>/hocx-*, nie fremde (postgres, redis, traefik
# …) und kein globales `docker image prune` (der Host kann andere Projekte tragen). Ohne `-f`: ein
# Image, das Docker noch braucht, bleibt einfach stehen. Build-Cache bleibt unberührt.

# Image-Referenzen (Wert von HOCX_*_IMAGE) aus einem Manifest, ohne es auszuführen.
_manifest_image_refs() {
  sed -n "s/^HOCX_[A-Z_]*_IMAGE='\{0,1\}\([^']*\)'\{0,1\}$/\1/p" "$1"
}

# Manifeste, deren Images bleiben: current.env und die KEEP neuesten weiteren.
_kept_manifests() {
  local releases="$1" keep="$2" file count=0
  [ -f "$releases/current.env" ] && printf '%s\n' "$releases/current.env"
  while IFS= read -r file; do
    [ "$(basename "$file")" = current.env ] && continue
    [ "$count" -lt "$keep" ] || break
    printf '%s\n' "$file"
    count=$((count + 1))
  done < <(ls -1t "$releases"/*.env 2> /dev/null || true)
}

# cleanup_old_release_images <projektverzeichnis> <ghcr-namespace> [keep]
cleanup_old_release_images() {
  local project_dir="$1" namespace="$2" keep="${3:-3}"
  local releases="$project_dir/.releases" prefix manifest ref id repository removed=0
  local -A keep_ids=()
  if ! [[ "$keep" =~ ^[0-9]+$ ]]; then
    echo "    HOCX_IMAGE_KEEP_RELEASES muss eine Zahl sein - keine Bereinigung." >&2
    return 1
  fi
  [ -n "$namespace" ] || return 1
  prefix="ghcr.io/${namespace}/hocx-"

  while IFS= read -r manifest; do
    while IFS= read -r ref; do
      [ -n "$ref" ] || continue
      id="$(docker image inspect "$ref" --format '{{.Id}}' 2> /dev/null || true)"
      [ -z "$id" ] || keep_ids["$id"]=1
    done < <(_manifest_image_refs "$manifest")
  done < <(_kept_manifests "$releases" "$keep")
  while IFS= read -r id; do
    [ -z "$id" ] || keep_ids["$id"]=1
  done < <(docker ps -aq | xargs -r docker inspect --format '{{.Image}}' 2> /dev/null || true)

  # Ohne ein einziges behaltenes Image stimmt etwas nicht (z. B. Manifeste fehlen): nichts löschen.
  if [ "${#keep_ids[@]}" -eq 0 ]; then
    echo "    Kein laufendes oder vorgemerktes Image gefunden - Image-Bereinigung übersprungen." >&2
    return 0
  fi

  local -A seen=()
  while read -r id repository; do
    [[ "$repository" == "$prefix"* ]] || continue
    [ -z "${keep_ids[$id]:-}" ] || continue
    [ -z "${seen[$id]:-}" ] || continue
    seen["$id"]=1
    # Alle Namen (Tags und Digests) entfernen; erst danach ist das Image weg. Ohne -f.
    while IFS= read -r ref; do
      [ -n "$ref" ] || continue
      docker image rm "$ref" > /dev/null 2>&1 || true
    done < <(docker image inspect "$id" --format '{{range .RepoTags}}{{println .}}{{end}}{{range .RepoDigests}}{{println .}}{{end}}' 2> /dev/null || true)
    if ! docker image inspect "$id" > /dev/null 2>&1; then
      removed=$((removed + 1))
    fi
  done < <(docker image ls --no-trunc --format '{{.ID}} {{.Repository}}')

  echo "    Alte hocX-Images entfernt: $removed (behalten: laufende, aktuelles Release und die letzten $keep Releases)."
}

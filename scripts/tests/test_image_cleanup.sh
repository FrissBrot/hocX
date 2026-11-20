#!/usr/bin/env bash
# Image-Bereinigung nach dem Update (scripts/lib/image_cleanup.sh): entfernt nur alte
# hocX-App-Images, behält laufende, das aktuelle Release und die letzten KEEP Releases.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=scripts/lib/image_cleanup.sh
source "$REPO_DIR/scripts/lib/image_cleanup.sh"
WORK="$(mktemp -d)"
trap 'rm -rf -- "$WORK"' EXIT
NS=verein
mkdir -p "$WORK/.releases" "$WORK/bin" "$WORK/state"

# Images: id|repository|tag|digest. v1..v5 je ein Backend-Image, dazu postgres und ein dangling.
cat > "$WORK/state/images" <<EOF
sha256:v1|ghcr.io/$NS/hocx-backend|v1|ghcr.io/$NS/hocx-backend@sha256:d1
sha256:v2|ghcr.io/$NS/hocx-backend|v2|ghcr.io/$NS/hocx-backend@sha256:d2
sha256:v3|ghcr.io/$NS/hocx-backend|v3|ghcr.io/$NS/hocx-backend@sha256:d3
sha256:v4|ghcr.io/$NS/hocx-backend|v4|ghcr.io/$NS/hocx-backend@sha256:d4
sha256:v5|ghcr.io/$NS/hocx-backend|v5|ghcr.io/$NS/hocx-backend@sha256:d5
sha256:old|ghcr.io/$NS/hocx-frontend|v0|ghcr.io/$NS/hocx-frontend@sha256:d0
sha256:pg|postgres|17|postgres@sha256:pg
sha256:run|ghcr.io/$NS/hocx-docs|v0|ghcr.io/$NS/hocx-docs@sha256:drun
EOF
: > "$WORK/state/removed"; : > "$WORK/state/pruned"

# docker-Stub: liest/ändert state/images
cat > "$WORK/bin/docker" <<'EOF'
#!/usr/bin/env bash
S="$STUB_STATE"
case "$1 $2" in
  "ps -aq") echo c1 ;;
  "inspect --format") echo sha256:run ;;
  "image ls") awk -F'|' '{print $1, $2}' "$S/images" ;;
  "image prune") echo pruned >> "$S/pruned" ;;
  "image inspect")
    ref="$3"
    line="$(awk -F'|' -v r="$ref" '$1==r || $2":"$3==r || $4==r' "$S/images" | head -n 1)"
    [ -n "$line" ] || exit 1
    IFS='|' read -r id repo tag digest <<< "$line"
    case "${5:-}" in
      '{{.Id}}') echo "$id" ;;
      '') ;;
      *) echo "$repo:$tag"; echo "$digest" ;;
    esac ;;
  "image rm")
    ref="$3"
    awk -F'|' -v r="$ref" '!($2":"$3==r || $4==r)' "$S/images" > "$S/images.new"
    if ! cmp -s "$S/images" "$S/images.new"; then echo "$ref" >> "$S/removed"; fi
    mv "$S/images.new" "$S/images" ;;
  *) echo "unerwarteter Aufruf: $*" >&2; exit 2 ;;
esac
EOF
chmod +x "$WORK/bin/docker"
export PATH="$WORK/bin:$PATH" STUB_STATE="$WORK/state"

# Manifeste v2..v5, v5 = aktuell; ältere zuerst anlegen (ls -t sortiert nach Zeit)
for v in v2 v3 v4 v5; do
  printf "HOCX_VERSION='%s'\nHOCX_BACKEND_IMAGE='ghcr.io/%s/hocx-backend@sha256:d%s'\n" "$v" "$NS" "${v#v}" > "$WORK/.releases/$v.env"
  touch -d "2026-11-0${v#v} 12:00" "$WORK/.releases/$v.env"
done
cp "$WORK/.releases/v5.env" "$WORK/.releases/current.env"

# keep=2: behalten current (v5) + v5.env, v4.env (die zwei neuesten) -> v3, v2, v1, alter Frontend weg
cleanup_old_release_images "$WORK" "$NS" 2 > /dev/null
images="$(cut -d'|' -f1 "$WORK/state/images" | tr '\n' ' ')"
for kept in sha256:v4 sha256:v5 sha256:pg sha256:run; do
  [[ " $images " == *" $kept "* ]] || { echo "Fall 1: $kept fälschlich entfernt ($images)" >&2; exit 1; }
done
for gone in sha256:v1 sha256:v2 sha256:v3 sha256:old; do
  [[ " $images " != *" $gone "* ]] || { echo "Fall 1: $gone nicht entfernt ($images)" >&2; exit 1; }
done
grep -q pruned "$WORK/state/pruned" || { echo "Fall 1: dangling Images nicht bereinigt" >&2; exit 1; }

# 2. Ungültiges KEEP: nichts löschen, Fehler melden
if cleanup_old_release_images "$WORK" "$NS" abc 2> /dev/null; then
  echo "Fall 2: ungültiges KEEP akzeptiert" >&2; exit 1
fi

# 3. Fremder Namespace: nichts von hocX gilt als eigenes Image
before="$(cat "$WORK/state/images")"
cleanup_old_release_images "$WORK" anderer 0 > /dev/null
[ "$before" = "$(cat "$WORK/state/images")" ] || { echo "Fall 3: Images eines anderen Namespace entfernt" >&2; exit 1; }
echo "Image-Bereinigung: ok"

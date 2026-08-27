#!/usr/bin/env bash

# Installs the repository-pinned Cosign binary below .tools after verifying its
# published binary checksum. Callers set PROJECT_DIR and receive COSIGN_BIN.
COSIGN_VERSION="v3.0.2"
COSIGN_BIN=""

ensure_cosign() {
  local architecture asset checksum tools_dir temp_file

  case "$(uname -m)" in
    x86_64|amd64)
      architecture=amd64
      checksum=46dbdcb5467a3dfec2526923d0b3365e40c8d9dc00ec23d5aca3437449e8cbfd
      ;;
    aarch64|arm64)
      architecture=arm64
      checksum=17fd784737ca54d7d8a343c82da6c5d6dbdee971e66644d923d1b057fb97d7ed
      ;;
    *)
      echo "Keine gepinnte Cosign-Version fuer Architektur $(uname -m) hinterlegt." >&2
      return 1
      ;;
  esac

  tools_dir="$PROJECT_DIR/.tools"
  COSIGN_BIN="$tools_dir/cosign-${COSIGN_VERSION}-linux-${architecture}"
  if [ -x "$COSIGN_BIN" ] && printf '%s  %s\n' "$checksum" "$COSIGN_BIN" | sha256sum --check --status; then
    return
  fi

  for command in curl sha256sum install; do
    command -v "$command" > /dev/null 2>&1 || {
      echo "$command wird fuer die verifizierte Cosign-Installation benoetigt." >&2
      return 1
    }
  done
  mkdir -p "$tools_dir"
  chmod 700 "$tools_dir"
  asset="cosign-linux-${architecture}"
  temp_file="$(mktemp "$tools_dir/.cosign.tmp.XXXXXX")"
  trap 'rm -f "$temp_file"' RETURN
  echo "==> Installiere Cosign $COSIGN_VERSION lokal"
  curl --fail --silent --show-error --location \
    --proto '=https' --tlsv1.2 --retry 3 --connect-timeout 15 --max-time 300 \
    "https://github.com/sigstore/cosign/releases/download/${COSIGN_VERSION}/${asset}" \
    --output "$temp_file"
  printf '%s  %s\n' "$checksum" "$temp_file" | sha256sum --check --status || {
    echo "Pruefsumme des heruntergeladenen Cosign-Binaries stimmt nicht." >&2
    return 1
  }
  install -m 755 "$temp_file" "$COSIGN_BIN"
  rm -f "$temp_file"
  trap - RETURN
}

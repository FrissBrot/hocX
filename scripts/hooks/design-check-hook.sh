#!/usr/bin/env bash
# Claude-Code-Hook (PostToolUse fuer Edit/Write): prueft geaenderte Frontend-Dateien gegen die
# Design-Regeln. Bei Verstoessen Exit 2 + Meldung auf stderr, damit Claude sie sofort behebt.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
file="$(python3 -c 'import json,sys; print((json.load(sys.stdin).get("tool_input") or {}).get("file_path",""))' 2>/dev/null || true)"

case "$file" in
  "$ROOT"/frontend/*.tsx|"$ROOT"/frontend/*.css|"$ROOT"/abgabebox-frontend/*.tsx|"$ROOT"/abgabebox-frontend/*.css) ;;
  *) exit 0 ;;
esac
case "$file" in */node_modules/*|*/.next/*|*/tokens.css) exit 0 ;; esac

if ! out="$(python3 "$ROOT/scripts/check-design-rules.py" "$file" 2>&1)"; then
  echo "Design-Regeln verletzt (siehe design/DESIGN.md):" >&2
  echo "$out" >&2
  exit 2
fi

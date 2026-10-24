#!/usr/bin/env bash
# Claude-Code-Hook (PostToolUse fuer Edit/Write): prueft die geaenderte Datei gegen SECURITY-RULES.md
# (nur neu eingefuehrte Verstoesse, scripts/check-security-rules.py). Bei Verstoessen Exit 2 +
# Meldung auf stderr, damit Claude sie sofort behebt - wie design-check-hook.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
file="$(python3 -c 'import json,sys; print((json.load(sys.stdin).get("tool_input") or {}).get("file_path",""))' 2>/dev/null || true)"
[ -n "$file" ] || exit 0

if ! out="$(python3 "$ROOT/scripts/check-security-rules.py" --exit-code 2 "$file" 2>&1)"; then
  echo "$out" >&2
  exit 2
fi

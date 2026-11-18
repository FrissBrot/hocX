#!/usr/bin/env python3
"""npm audit mit begründeten Ausnahmen (.github/npm-audit-allowlist.json).

    npm-audit-gate.py <app-verzeichnis> [...]

Scheitert bei jedem Advisory ab «high», das nicht in der Ausnahmeliste steht oder dessen
Ausnahme abgelaufen ist. Folgemeldungen («Depends on vulnerable versions of …») zählen nicht
einzeln: entscheidend sind die eigentlichen Advisories. Ausgabe als Markdown (Step-Summary).
"""

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST = ROOT / ".github" / "npm-audit-allowlist.json"
BLOCKING = {"high", "critical"}


def advisory_id(entry: dict) -> str:
    url = entry.get("url") or ""
    return url.rsplit("/", 1)[-1] if url else str(entry.get("source"))


def load_allowlist(today: date) -> tuple[dict[str, dict], list[str]]:
    data = json.loads(ALLOWLIST.read_text(encoding="utf-8")) if ALLOWLIST.exists() else {"advisories": []}
    allowed: dict[str, dict] = {}
    expired: list[str] = []
    for item in data.get("advisories", []):
        if date.fromisoformat(item["until"]) < today:
            expired.append(f"{item['id']} ({item.get('package', '?')}) - Ausnahme abgelaufen am {item['until']}")
        else:
            allowed[item["id"]] = item
    return allowed, expired


def audit(app: Path) -> list[dict]:
    result = subprocess.run(
        ["npm", "audit", "--json", "--package-lock-only"], cwd=app, capture_output=True, text=True, check=False
    )
    report = json.loads(result.stdout or "{}")
    found: dict[str, dict] = {}
    for name, vulnerability in (report.get("vulnerabilities") or {}).items():
        for via in vulnerability.get("via", []):
            if isinstance(via, dict) and via.get("severity") in BLOCKING:
                found.setdefault(advisory_id(via), {"package": via.get("name", name), "severity": via["severity"], "title": via.get("title", ""), "range": via.get("range", "")})
    return [{"id": key, **value} for key, value in sorted(found.items())]


def main(apps: list[str]) -> int:
    allowed, expired = load_allowlist(date.today())
    failed = bool(expired)
    for message in expired:
        print(f"- FEHLER: {message}")
    for app in apps:
        print(f"## npm audit: {app}")
        advisories = audit(ROOT / app)
        if not advisories:
            print("Keine Advisories ab «high».")
        for item in advisories:
            if item["id"] in allowed:
                print(f"- ausgenommen: {item['id']} {item['package']} {item['range']} - {allowed[item['id']]['reason']} (bis {allowed[item['id']]['until']})")
            else:
                failed = True
                print(f"- FEHLER: {item['id']} {item['package']} {item['range']} ({item['severity']}): {item['title']}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["frontend", "abgabebox-frontend"]))

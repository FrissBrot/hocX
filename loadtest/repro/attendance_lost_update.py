#!/usr/bin/env python3
"""Reproduktion CONC-005: gleichzeitige Anwesenheits-Klicks im selben Block überschreiben sich.

ProtocolElementService.set_attendance_status liest configuration_snapshot_json ohne Zeilensperre,
ändert einen Eintrag und schreibt das ganze JSON zurück (Read-Modify-Write unter READ COMMITTED).
Das Skript setzt für K verschiedene Teilnehmende parallel einen Status und zählt danach, wie viele
Einträge tatsächlich gespeichert sind. Erwartet: K. Bei Lost Updates: weniger.

Nur gegen den isolierten Lasttest-Stack (Seed: loadtest/seed/seed_loadtest.py):
    python3 attendance_lost_update.py --base http://localhost:18000 --tokens ../tokens.json --rounds 20
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor


def call(base: str, cookie: str, method: str, path: str, body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{base}{path}", data=data, method=method, headers={"Cookie": cookie, "Content-Type": "application/json", "Origin": base})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read() or b"null")


def main() -> None:
    if os.environ.get("HOCX_LOADTEST_TARGET_CONFIRMED") != "isolated":
        sys.exit("HOCX_LOADTEST_TARGET_CONFIRMED=isolated fehlt")
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--tokens", required=True)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--parallel", type=int, default=8)
    args = parser.parse_args()
    seed = json.load(open(args.tokens, encoding="utf-8"))
    tenant = seed["tenants"][0]
    cookies = [f"{seed['cookie_name']}={token}" for token in tenant["sessions"]]
    protocols = call(args.base, cookies[0], "GET", "/api/protocols?limit=20")
    protocols = protocols if isinstance(protocols, list) else protocols.get("items", [])
    block = next(
        (b["id"] for p in protocols for e in call(args.base, cookies[0], "GET", f"/api/protocols/{p['id']}/elements") for b in e.get("blocks", []) if b.get("element_type_id") == 9),
        None,
    )
    if block is None:
        sys.exit("Kein Anwesenheitsblock in einem offenen Protokoll gefunden")
    participants = call(args.base, cookies[0], "GET", "/api/participants")
    participants = [p["id"] for p in (participants if isinstance(participants, list) else participants.get("items", []))]
    lost_rounds = 0
    for round_no in range(args.rounds):
        chosen = random.sample(participants, min(args.parallel, len(participants)))
        status = random.choice(["present", "late", "excused", "absent"])
        with ThreadPoolExecutor(len(chosen)) as pool:
            list(pool.map(lambda pair: call(args.base, cookies[pair[0] % len(cookies)], "POST",
                                            f"/api/protocol-element-blocks/{block}/attendance/{pair[1]}", {"status": status}),
                          enumerate(chosen)))
        elements = [b for p in protocols for e in call(args.base, cookies[0], "GET", f"/api/protocols/{p['id']}/elements") for b in e.get("blocks", []) if b["id"] == block]
        entries = (elements[0].get("configuration_snapshot_json") or {}).get("attendance_entries", []) if elements else []
        saved = {str(entry.get("participant_id")): entry.get("status") for entry in entries}
        missing = [pid for pid in chosen if saved.get(str(pid)) != status]
        lost_rounds += bool(missing)
        print(f"Runde {round_no + 1}: {len(chosen) - len(missing)}/{len(chosen)} Status gespeichert" + (f"  VERLOREN: {len(missing)}" if missing else ""))
    print(f"\nRunden mit Lost Update: {lost_rounds}/{args.rounds}")


if __name__ == "__main__":
    main()

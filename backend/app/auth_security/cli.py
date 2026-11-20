"""Notfallzugang Anmeldeschutz (RUNBOOK «Anmeldeschutz»), im Backend-Container:

    docker compose exec backend python -m app.auth_security.cli list
    docker compose exec backend python -m app.auth_security.cli unblock <subject>
    docker compose exec backend python -m app.auth_security.cli unblock-ip <ip>
    docker compose exec backend python -m app.auth_security.cli reset-account <email>
    docker compose exec backend python -m app.auth_security.cli attack-mode-off

``reset-account`` löscht die Fehlversuchszähler eines Kontos (L5) - z. B. wenn die Inhaberin
ohne bekanntes Gerät dringend Zugang braucht. ``attack-mode-off`` setzt den Angriffsmodus (L7) für eine Stunde aus. Jeder Eingriff wird als Ereignis
``block.clear`` protokolliert.
"""
from __future__ import annotations

import sys
import time

from app.auth_security import blocks, events
from app.core.auth_pseudonym import subject_hash
from app.core.rate_limit import redis_key
from app.core.redis_client import get_redis_sync


def _reset_account(email: str) -> int:
    client = get_redis_sync()
    deleted = 0
    for scope in ("login-account",):
        for key in client.scan_iter(f"{redis_key(scope, subject_hash(email))}*", count=200):
            deleted += client.delete(key)
    events.record(event_type="block.clear", outcome="info", subject_hash=subject_hash(email), details={"reason": "cli_reset_account"})
    return deleted


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    command, *rest = argv
    if command == "list":
        now = int(time.time())
        for block in blocks.active_blocks():
            print(f"{block.subject}\t{block.scope}\tnoch {max(0, block.until - now) // 60} min\t{'manuell' if block.manual else 'automatisch'}\t{block.reason}")
        return 0
    if command == "unblock" and rest:
        print("aufgehoben" if blocks.clear(rest[0]) else "keine Sperre gefunden")
        return 0
    if command == "unblock-ip" and rest:
        cleared = [blocks.clear(blocks.subject_for(rest[0], scope)) for scope in ("source", "net")]
        print("aufgehoben" if any(cleared) else "keine Sperre gefunden")
        return 0
    if command == "reset-account" and rest:
        print(f"{_reset_account(rest[0])} Zähler gelöscht")
        return 0
    if command == "attack-mode-off":
        from app.auth_security.guard import ATTACK_OVERRIDE_KEY

        get_redis_sync().set(ATTACK_OVERRIDE_KEY, "1", ex=3600)
        events.record(event_type="block.clear", outcome="info", details={"reason": "cli_attack_mode_off"})
        print("Angriffsmodus für höchstens 1 h ausgesetzt")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

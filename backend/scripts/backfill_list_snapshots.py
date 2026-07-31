"""One-time backfill: give every non-abgeschlossen protocol's list-linked blocks an
initial list_snapshot, computed from current live data, so nothing shows a false
"Daten aktualisieren" hint immediately after this feature deploys.

abgeschlossen protocols are deliberately left untouched - they keep rendering via the
live-lookup fallback in export_service.py/focused-element-editor.tsx forever, so a
backfill run can never silently alter already-finalized PDF content.

Usage:
    python3 -m scripts.backfill_list_snapshots            # dry run, prints what it would do
    python3 -m scripts.backfill_list_snapshots --apply    # actually writes the snapshots
"""
from __future__ import annotations

import sys

from app.core.db import SessionLocal
from app.models import Protocol
from app.services import list_snapshot_service


def run(apply: bool) -> None:
    db = SessionLocal()
    try:
        protocols = db.query(Protocol).filter(Protocol.status != "abgeschlossen").all()
        touched_protocols = 0
        touched_blocks = 0
        for protocol in protocols:
            blocks = list_snapshot_service.list_linked_blocks_for_protocol(db, protocol.id)
            if not blocks:
                continue
            touched_protocols += 1
            touched_blocks += len(blocks)
            print(f"protocol {protocol.id} ({protocol.protocol_number}): {len(blocks)} list-linked block(s)")
            if apply:
                for block in blocks:
                    list_snapshot_service.refresh_block_list_snapshot(db, block, keep_undo=False)
        print(f"\n{'Applied' if apply else 'Would touch'}: {touched_protocols} protocol(s), {touched_blocks} block(s).")
        if not apply:
            print("Dry run only - re-run with --apply to write the snapshots.")
    finally:
        db.close()


if __name__ == "__main__":
    run(apply="--apply" in sys.argv)

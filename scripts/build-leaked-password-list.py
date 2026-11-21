#!/usr/bin/env python3
"""Erzeugt die lokale Rückfall-Liste geleakter Passwörter (SEC-AUTH-015).

    python3 scripts/build-leaked-password-list.py            # herunterladen, prüfen, schreiben
    python3 scripts/build-leaked-password-list.py --check    # nur prüfen, ob die Datei passt

Die Liste dient nur als Rückfall, wenn die HIBP-Range-API nicht erreichbar oder abgeschaltet ist
(``PASSWORD_LEAK_CHECK=local-only``), siehe ``backend/app/core/password_leak.py``.

Quellen (SecLists, MIT-Lizenz, Commit fest gepinnt, Inhalt per SHA-256 geprüft):
- ``100k-most-used-passwords-NCSC.txt`` (UK NCSC, aus Pwned Passwords abgeleitet)
- ``xato-net-10-million-passwords-1000000.txt``
- ``Pwdb_top-1000000.txt``

Nur Einträge ab ``MIN_LENGTH`` Zeichen (kürzere lehnt die Passwortregel ohnehin ab). Im Repo
liegen keine Klartext-Passwörter, nur die ersten ``PREFIX_BYTES`` Bytes ihres SHA-1, sortiert.
Bei 48 Bit und rund 75 000 Einträgen ist ein zufälliger Fehltreffer praktisch ausgeschlossen
(~3·10⁻¹⁰ je Prüfung).

Dateiformat ``backend/app/core/leaked_passwords.bin``: ``b"HXLP1\\n"``, Anzahl (uint32, big
endian), Präfixlänge (uint8), danach die sortierten Präfixe ohne Trenner.
"""
from __future__ import annotations

import hashlib
import struct
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "backend/app/core/leaked_passwords.bin"
MAGIC = b"HXLP1\n"
MIN_LENGTH = 12
PREFIX_BYTES = 6
SECLISTS_COMMIT = "913b327317496d062bcc7cace524aaad8a693be2"
BASE = f"https://raw.githubusercontent.com/danielmiessler/SecLists/{SECLISTS_COMMIT}/Passwords/Common-Credentials/"
SOURCES = {
    "100k-most-used-passwords-NCSC.txt": "c2e5696882c603b76bb67a47ee970897e5a76fc4c3f5547abe3d0ca340c576e0",  # gitleaks:allow - SHA-256 der öffentlichen Liste, kein Secret
    "xato-net-10-million-passwords-1000000.txt": "424a3e03a17df0a2bc2b3ca749d81b04e79d59cb7aeec8876a5a3f308d0caf51",  # gitleaks:allow - SHA-256 der öffentlichen Liste, kein Secret
    "Pwdb_top-1000000.txt": "e9a88f67aafe65496682dc374559ee714e978bee50314767494c3e37a18c9fc8",  # gitleaks:allow - SHA-256 der öffentlichen Liste, kein Secret
}


def _download(name: str, expected: str) -> bytes:
    request = urllib.request.Request(BASE + name, headers={"User-Agent": "hocx-build"})
    with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310 - feste HTTPS-URL
        data = response.read(64 * 1024 * 1024)
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise SystemExit(f"{name}: SHA-256 {actual} statt {expected}")
    return data


def build() -> bytes:
    prefixes: set[bytes] = set()
    for name, expected in SOURCES.items():
        for line in _download(name, expected).decode("utf-8", "replace").splitlines():
            if len(line) >= MIN_LENGTH:
                prefixes.add(hashlib.sha1(line.encode("utf-8")).digest()[:PREFIX_BYTES])  # noqa: S324 - HIBP-kompatibel
    ordered = sorted(prefixes)
    return MAGIC + struct.pack(">IB", len(ordered), PREFIX_BYTES) + b"".join(ordered)


def main() -> int:
    content = build()
    if "--check" in sys.argv:
        if not TARGET.exists() or TARGET.read_bytes() != content:
            print(f"{TARGET.relative_to(ROOT)} veraltet (python3 scripts/build-leaked-password-list.py)", file=sys.stderr)
            return 1
        print("Leak-Liste: ok")
        return 0
    TARGET.write_bytes(content)
    count = struct.unpack(">I", content[len(MAGIC):len(MAGIC) + 4])[0]
    print(f"{TARGET.relative_to(ROOT)}: {count} Einträge, {len(content)} Bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Testdateien für die Upload-Szenarien erzeugen (im Backend-Image ausführen, dort ist Pillow da).

    docker run --rm -v "$PWD/loadtest/fixtures:/out" hocx-tests-backend-test:latest \
        python /out/make_fixtures.py --out /out

Erzeugt: photo-1mb.jpg, photo-8mb.jpg, photo-25mb.jpg (Rauschen, kaum komprimierbar - realistische
Decode-/Scan-Kosten) und gallery-200.zip (200 Bilder à ~1 MB, gespeichert ohne Kompression).
"""
from __future__ import annotations

import argparse
import io
import os
import zipfile
from pathlib import Path

from PIL import Image


def noise_jpeg(target_bytes: int) -> bytes:
    # Kantenlänge so wählen, dass das JPEG (Qualität 95, Rauschen) ungefähr target_bytes gross wird.
    side = max(256, int((target_bytes / 1.6) ** 0.5))
    image = Image.frombytes("RGB", (side, side), os.urandom(side * side * 3))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=95)
    return buffer.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("."))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for label, size in (("1mb", 1 << 20), ("8mb", 8 << 20), ("25mb", 25 << 20)):
        data = noise_jpeg(size)
        (args.out / f"photo-{label}.jpg").write_bytes(data)
        print(f"photo-{label}.jpg {len(data) / 1e6:.1f} MB")
    with zipfile.ZipFile(args.out / "gallery-200.zip", "w", compression=zipfile.ZIP_STORED) as archive:
        for index in range(200):
            archive.writestr(f"lager/IMG_{index:04d}.jpg", noise_jpeg(1 << 20))
    print(f"gallery-200.zip {(args.out / 'gallery-200.zip').stat().st_size / 1e6:.0f} MB")


if __name__ == "__main__":
    main()

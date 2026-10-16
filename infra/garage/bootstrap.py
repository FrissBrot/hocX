"""Idempotente Einrichtung des lokalen Garage-S3 über die Admin-API v2.

Läuft als Init-Container (storage-init) bei jedem Deployment: legt Layout, Zugangsschlüssel und
Buckets an, falls sie fehlen, und ändert nie etwas an vorhandenen Daten. Zwei Schlüssel:
- LOCAL_S3_ACCESS_KEY: Backend, Worker, Foto-Worker - Lesen/Schreiben auf beide Buckets.
- LOCAL_S3_ABGABEBOX_ACCESS_KEY: öffentliche Abgabebox - nur ihr eigener Bucket.

Nur Python-Standardbibliothek (läuft im Backend-Image).
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

ADMIN_URL = os.environ.get("GARAGE_ADMIN_URL", "http://local-s3:3903").rstrip("/")
TOKEN = os.environ.get("GARAGE_ADMIN_TOKEN", "")
CAPACITY = os.environ.get("GARAGE_CAPACITY", "100G")


def _read_secret(name: str) -> str:
    value = os.environ.get(name, "")
    path = os.environ.get(f"{name}_FILE")
    if not value and path:
        with open(path, encoding="utf-8") as handle:
            value = handle.read().strip()
    return value


def call(method: str, path: str, body: dict | None = None, *, allow_404: bool = False):
    request = urllib.request.Request(
        f"{ADMIN_URL}{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            raw = response.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        if allow_404 and exc.code in (400, 404):
            return None
        raise SystemExit(f"Garage-Admin-API {method} {path}: HTTP {exc.code} {exc.read()[:300]!r}") from exc


def wait_ready() -> dict:
    deadline = time.monotonic() + 120
    while True:
        try:
            return call("GET", "/v2/GetClusterStatus")
        except (urllib.error.URLError, ConnectionError, OSError, SystemExit):
            if time.monotonic() > deadline:
                raise SystemExit("Garage ist nach 120 s nicht erreichbar")
            time.sleep(2)


def ensure_layout(status: dict) -> None:
    layout = call("GET", "/v2/GetClusterLayout")
    if layout.get("roles"):
        return
    node_id = status["nodes"][0]["id"]
    capacity = _parse_capacity(CAPACITY)
    call("POST", "/v2/UpdateClusterLayout", {"roles": [{"id": node_id, "zone": "dc1", "capacity": capacity, "tags": ["hocx"]}]})
    call("POST", "/v2/ApplyClusterLayout", {"version": int(layout.get("version", 0)) + 1})
    print(f"Layout angelegt: Knoten {node_id[:16]}, Kapazität {CAPACITY}")


def _parse_capacity(value: str) -> int:
    units = {"K": 1000, "M": 1000**2, "G": 1000**3, "T": 1000**4}
    value = value.strip().upper()
    if value and value[-1] in units:
        return int(float(value[:-1]) * units[value[-1]])
    return int(value)


def ensure_key(name: str, access_key: str, secret_key: str) -> None:
    if call("GET", f"/v2/GetKeyInfo?id={access_key}", allow_404=True) is not None:
        return
    call("POST", "/v2/ImportKey", {"accessKeyId": access_key, "secretAccessKey": secret_key, "name": name})
    print(f"Schlüssel {name} importiert")


def ensure_bucket(alias: str) -> str:
    info = call("GET", f"/v2/GetBucketInfo?globalAlias={alias}", allow_404=True)
    if info is None:
        info = call("POST", "/v2/CreateBucket", {"globalAlias": alias})
        print(f"Bucket {alias} angelegt")
    return info["id"]


def allow(bucket_id: str, access_key: str, *, owner: bool) -> None:
    call("POST", "/v2/AllowBucketKey", {
        "bucketId": bucket_id, "accessKeyId": access_key,
        "permissions": {"read": True, "write": True, "owner": owner},
    })


def main() -> None:
    main_key, main_secret = os.environ.get("LOCAL_S3_ACCESS_KEY", ""), _read_secret("LOCAL_S3_SECRET_KEY")
    box_key, box_secret = os.environ.get("LOCAL_S3_ABGABEBOX_ACCESS_KEY", ""), _read_secret("LOCAL_S3_ABGABEBOX_SECRET_KEY")
    main_bucket = os.environ.get("LOCAL_S3_BUCKET", "hocx-main")
    box_bucket = os.environ.get("LOCAL_S3_ABGABEBOX_BUCKET", "hocx-abgabebox")
    if not TOKEN or not main_key or not main_secret:
        print("LOCAL_S3_* bzw. GARAGE_ADMIN_TOKEN nicht gesetzt - lokales S3 wird nicht eingerichtet")
        return
    status = wait_ready()
    ensure_layout(status)
    ensure_key("hocx-backend", main_key, main_secret)
    main_id = ensure_bucket(main_bucket)
    box_id = ensure_bucket(box_bucket)
    allow(main_id, main_key, owner=True)
    allow(box_id, main_key, owner=True)
    if box_key and box_secret:
        ensure_key("hocx-abgabebox", box_key, box_secret)
        allow(box_id, box_key, owner=False)
    print("Lokales S3 bereit")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        if exc.code not in (None, 0):
            print(exc, file=sys.stderr)
        raise

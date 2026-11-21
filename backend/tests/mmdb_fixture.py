"""Kleine MaxMind-DB (MMDB) für Tests der Länder-Geolocation (app/core/geoip.py).

Schreibt das Format von https://maxmind.github.io/MaxMind-DB/ direkt (IPv6-Baum, Recordgrösse 24),
gerade genug für ``{"country": {"iso_code": "CH"}}``-Einträge - so testen die Tests die echte
Leselogik (maxminddb) ohne Netzzugriff und ohne die echte DB-IP-Datei.
"""
from __future__ import annotations

import ipaddress
from datetime import UTC, datetime
from pathlib import Path

METADATA_MARKER = b"\xab\xcd\xefMaxMind.com"


def _control(type_id: int, size: int) -> bytes:
    if size >= 29:
        raise ValueError("Testwerte sind kurz")
    if type_id <= 7:
        return bytes([(type_id << 5) | size])
    return bytes([size, type_id - 7])


class _U:
    """Ganzzahl mit festem MMDB-Typ (libmaxminddb prüft die Typen der Metadaten streng)."""

    def __init__(self, value: int, type_id: int) -> None:
        self.value, self.type_id = value, type_id


def _encode(value) -> bytes:
    if isinstance(value, _U):
        data = value.value.to_bytes((value.value.bit_length() + 7) // 8, "big") if value.value else b""
        return _control(value.type_id, len(data)) + data
    if isinstance(value, str):
        data = value.encode()
        return _control(2, len(data)) + data
    if isinstance(value, bool):
        return _control(14, int(value))
    if isinstance(value, int):
        data = value.to_bytes((value.bit_length() + 7) // 8, "big") if value else b""
        if value < 1 << 16:
            return _control(5, len(data)) + data
        if value < 1 << 32:
            return _control(6, len(data)) + data
        return _control(9, len(data)) + data
    if isinstance(value, dict):
        return _control(7, len(value)) + b"".join(_encode(k) + _encode(v) for k, v in value.items())
    if isinstance(value, list):
        return _control(11, len(value)) + b"".join(_encode(v) for v in value)
    raise TypeError(type(value))


def _network_bits(network: str) -> tuple[int, int]:
    net = ipaddress.ip_network(network)
    if net.version == 4:
        return int(net.network_address), 96 + net.prefixlen
    return int(net.network_address), net.prefixlen


def write_mmdb(
    path: Path, networks: dict[str, str], *, database_type: str = "DBIP-Country-Lite", build: datetime | None = None,
    pad_nodes: int = 0,
) -> Path:
    """``networks``: {"81.0.0.0/8": "CH", "2001:db8::/32": "DE"}. ``pad_nodes`` hängt ungenutzte
    Knoten an (für die Grössenprüfung von ``validate_file``)."""
    data = bytearray()
    offsets: dict[str, int] = {}
    for code in sorted(set(networks.values())):
        offsets[code] = len(data)
        data += _encode({"country": {"iso_code": code}})
    nodes: list[list[object]] = [[None, None]]
    for network, code in networks.items():
        value, length = _network_bits(network)
        node = 0
        for depth in range(length):
            bit = (value >> (127 - depth)) & 1
            if depth == length - 1:
                nodes[node][bit] = ("data", code)
                break
            child = nodes[node][bit]
            if not isinstance(child, int):
                nodes.append([None, None])
                child = len(nodes) - 1
                nodes[node][bit] = child
            node = child
    node_count = len(nodes) + pad_nodes
    tree = bytearray()
    for left_right in nodes + [[None, None]] * pad_nodes:
        for record in left_right:
            if record is None:
                number = node_count
            elif isinstance(record, int):
                number = record
            else:
                number = node_count + 16 + offsets[record[1]]
            tree += number.to_bytes(3, "big")
    built = build or datetime.now(UTC)
    metadata = {
        "binary_format_major_version": _U(2, 5),
        "binary_format_minor_version": _U(0, 5),
        "build_epoch": _U(int(built.timestamp()), 9),
        "database_type": database_type,
        "description": {"en": "hocX test database"},
        "ip_version": _U(6, 5),
        "languages": ["en"],
        "node_count": _U(node_count, 6),
        "record_size": _U(24, 5),
    }
    path.write_bytes(bytes(tree) + b"\x00" * 16 + bytes(data) + METADATA_MARKER + _encode(metadata))
    return path


from __future__ import annotations


def scan_bytes(content: bytes, *, host: str, port: int = 3310) -> str:
    """Scan file bytes via clamd stream. Returns 'clean', 'infected', or 'pending'.

    'pending' is returned when clamd is unreachable — the file is quarantined for later
    rescanning by the main backend. This prevents a clamd outage from blocking all uploads.
    """
    try:
        import pyclamd
        cd = pyclamd.ClamdNetworkSocket(host=host, port=port, timeout=30)
        result = cd.scan_stream(content)
        # result is None when clean; {'stream': ('FOUND', 'VirusName')} when infected
        return "clean" if result is None else "infected"
    except Exception:
        return "pending"

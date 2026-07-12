from __future__ import annotations

from pathlib import Path


def scan_bytes(content: bytes, *, host: str, port: int = 3310) -> str:
    """Scan file bytes via clamd stream. Returns 'clean', 'infected', or 'pending'."""
    try:
        import pyclamd
        cd = pyclamd.ClamdNetworkSocket(host=host, port=port, timeout=30)
        result = cd.scan_stream(content)
        return "clean" if result is None else "infected"
    except Exception:
        return "pending"


def scan_file(path: str | Path, *, host: str, port: int = 3310) -> str:
    """Read file from disk and scan via clamd. Returns 'clean', 'infected', or 'pending'."""
    try:
        content = Path(path).read_bytes()
    except OSError:
        return "pending"
    return scan_bytes(content, host=host, port=port)

from __future__ import annotations


class CborDecodeError(ValueError):
    pass


# Passkey-Antworten verschachteln höchstens wenige Ebenen (Attestation -> attStmt -> x5c). Ohne
# Grenze liess tief verschachteltes CBOR aus dem Request-Body Python mit RecursionError abbrechen
# (500 statt Eingabefehler, Bug-Bounty 2026-11-22).
MAX_DEPTH = 16


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.depth = 0

    def _take(self, size: int) -> bytes:
        if self.pos + size > len(self.data):
            raise CborDecodeError("Unexpected end of CBOR payload")
        chunk = self.data[self.pos : self.pos + size]
        self.pos += size
        return chunk

    def _read_uint(self, additional_info: int) -> int:
        if additional_info < 24:
            return additional_info
        if additional_info == 24:
            return self._take(1)[0]
        if additional_info == 25:
            return int.from_bytes(self._take(2), "big")
        if additional_info == 26:
            return int.from_bytes(self._take(4), "big")
        if additional_info == 27:
            return int.from_bytes(self._take(8), "big")
        raise CborDecodeError(f"Unsupported CBOR additional-info value {additional_info}")

    def decode(self):
        if self.depth >= MAX_DEPTH:
            raise CborDecodeError("CBOR payload is nested too deeply")
        self.depth += 1
        try:
            return self._decode_item()
        finally:
            self.depth -= 1

    def _decode_item(self):
        initial = self._take(1)[0]
        major = initial >> 5
        additional_info = initial & 0x1F

        if major == 0:
            return self._read_uint(additional_info)
        if major == 1:
            return -1 - self._read_uint(additional_info)
        if major == 2:
            return self._take(self._read_uint(additional_info))
        if major == 3:
            try:
                return self._take(self._read_uint(additional_info)).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise CborDecodeError("CBOR text string is not valid UTF-8") from exc
        if major == 4:
            return [self.decode() for _ in range(self._read_uint(additional_info))]
        if major == 5:
            count = self._read_uint(additional_info)
            result: dict = {}
            for _ in range(count):
                key = self.decode()
                value = self.decode()
                try:
                    result[key] = value
                except TypeError as exc:
                    # A CBOR map key can legally decode to a list/map (major type 4/5),
                    # which Python can't use as a dict key - map that to the same
                    # CborDecodeError every other malformed-input case raises instead of
                    # letting an unclassified TypeError propagate as an unhandled 500
                    # (audit finding, 2026-08-25).
                    raise CborDecodeError("CBOR map key is not hashable") from exc
            return result
        if major == 7:
            if additional_info == 20:
                return False
            if additional_info == 21:
                return True
            if additional_info == 22:
                return None
        raise CborDecodeError(f"Unsupported CBOR major type {major}")


def decode_cbor(data: bytes):
    value, consumed = decode_cbor_prefix(data)
    if consumed != len(data):
        raise CborDecodeError("Trailing bytes in CBOR payload")
    return value


def decode_cbor_prefix(data: bytes):
    reader = _Reader(data)
    value = reader.decode()
    return value, reader.pos

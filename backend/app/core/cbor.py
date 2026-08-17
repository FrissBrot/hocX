from __future__ import annotations


class CborDecodeError(ValueError):
    pass


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

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
            return self._take(self._read_uint(additional_info)).decode("utf-8")
        if major == 4:
            return [self.decode() for _ in range(self._read_uint(additional_info))]
        if major == 5:
            return {self.decode(): self.decode() for _ in range(self._read_uint(additional_info))}
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

"""Zero-dependency streaming Redis RESP2 protocol encoder & incremental decoder."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class RespProtocolError(ValueError):
    """Raised when an incoming RESP2 byte stream violates wire framing rules."""


@dataclass(frozen=True)
class SimpleString:
    """Explicit RESP2 Simple String (`+OK\\r\\n`) wrapper."""

    value: str


@dataclass(frozen=True)
class RespErrorValue:
    """Explicit RESP2 Error (`-ERR ...\\r\\n`) wrapper."""

    message: str


_CRLF = b"\r\n"


def encode_resp(value: Any) -> bytes:
    """Serialize a Python value into RESP2 wire bytes."""
    if value is None:
        return b"$-1\r\n"
    if isinstance(value, SimpleString):
        return b"+" + value.value.encode("utf-8") + _CRLF
    if isinstance(value, RespErrorValue):
        return b"-" + value.message.encode("utf-8") + _CRLF
    if isinstance(value, bool):
        raise TypeError("Booleans are not a native RESP2 type; pass int or str.")
    if isinstance(value, int):
        return f":{value}\r\n".encode("ascii")
    if isinstance(value, bytes):
        return f"${len(value)}\r\n".encode("ascii") + value + _CRLF
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return f"${len(raw)}\r\n".encode("ascii") + raw + _CRLF
    if isinstance(value, (list, tuple)):
        parts = [f"*{len(value)}\r\n".encode("ascii")]
        parts.extend(encode_resp(item) for item in value)
        return b"".join(parts)
    raise TypeError(f"Unsupported RESP2 value type: {type(value).__name__}")


class _NeedMoreData(Exception):
    """Internal control-flow signal when buffer contains an incomplete frame."""


class RespStreamDecoder:
    """Incremental RESP2 frame parser safe against arbitrary TCP chunk splits."""

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, chunk: bytes) -> None:
        """Append raw bytes received from a socket or stream."""
        self._buf.extend(chunk)

    def _read_line(self, pos: int) -> tuple[bytes, int]:
        end = self._buf.find(_CRLF, pos)
        if end == -1:
            raise _NeedMoreData
        return bytes(self._buf[pos:end]), end + 2

    def _parse_int(self, raw: bytes) -> int:
        try:
            return int(raw.decode("ascii"))
        except ValueError as exc:
            raise RespProtocolError(f"Invalid RESP2 integer: {raw!r}") from exc

    def _parse_at(self, pos: int) -> tuple[Any, int]:
        if pos >= len(self._buf):
            raise _NeedMoreData
        prefix = chr(self._buf[pos])
        cursor = pos + 1

        if prefix == "+":
            line, next_pos = self._read_line(cursor)
            return SimpleString(line.decode("utf-8")), next_pos

        if prefix == "-":
            line, next_pos = self._read_line(cursor)
            return RespErrorValue(line.decode("utf-8")), next_pos

        if prefix == ":":
            line, next_pos = self._read_line(cursor)
            return self._parse_int(line), next_pos

        if prefix == "$":
            line, next_pos = self._read_line(cursor)
            length = self._parse_int(line)
            if length == -1:
                return None, next_pos
            if length < -1:
                raise RespProtocolError(f"Invalid bulk string length: {length}")
            end_payload = next_pos + length
            if len(self._buf) < end_payload + 2:
                raise _NeedMoreData
            if self._buf[end_payload : end_payload + 2] != _CRLF:
                raise RespProtocolError("Bulk string missing trailing CRLF")
            payload = bytes(self._buf[next_pos:end_payload])
            try:
                return payload.decode("utf-8"), end_payload + 2
            except UnicodeDecodeError:
                return payload, end_payload + 2

        if prefix == "*":
            line, next_pos = self._read_line(cursor)
            count = self._parse_int(line)
            if count == -1:
                return None, next_pos
            if count < -1:
                raise RespProtocolError(f"Invalid array length: {count}")
            items: list[Any] = []
            for _ in range(count):
                item, next_pos = self._parse_at(next_pos)
                items.append(item)
            return items, next_pos

        raise RespProtocolError(f"Unknown RESP2 type prefix: {prefix!r}")

    def try_pop(self) -> tuple[bool, Any]:
        """Decode one complete frame if available; otherwise return (False, None)."""
        try:
            value, consumed = self._parse_at(0)
        except _NeedMoreData:
            return False, None
        del self._buf[:consumed]
        return True, value

    def pop_all(self) -> list[Any]:
        """Decode all complete frames currently buffered."""
        frames: list[Any] = []
        while True:
            ok, frame = self.try_pop()
            if not ok:
                break
            frames.append(frame)
        return frames


if __name__ == "__main__":
    pipeline = encode_resp(["SET", "vietredis:key", "hello"]) + encode_resp(
        [SimpleString("OK"), 42, None, ["nested", "resp2"]]
    )
    decoder = RespStreamDecoder()
    decoded: list[Any] = []
    # Simulate adversarial 3-byte TCP packet fragmentation
    for offset in range(0, len(pipeline), 3):
        decoder.feed(pipeline[offset : offset + 3])
        decoded.extend(decoder.pop_all())
    print(f"Encoded bytes: {len(pipeline)} B -> Decoded {len(decoded)} frames:")
    for idx, frame in enumerate(decoded, start=1):
        print(f"  Frame {idx}: {frame!r}")

"""MessagePack encoder."""

import struct
import math
from ..value import DateTimeValue


def encode(value) -> bytes:
    """Encode a value to MessagePack bytes."""
    buf = bytearray()
    _encode_value(value, buf)
    return bytes(buf)


def _encode_value(value, buf: bytearray):
    if value is None:
        buf.append(0xC0)
    elif isinstance(value, bool):
        buf.append(0xC3 if value else 0xC2)
    elif isinstance(value, int) and not isinstance(value, bool):
        _encode_integer(value, buf)
    elif isinstance(value, float):
        _encode_float64(value, buf)
    elif isinstance(value, str):
        _encode_string(value, buf)
    elif isinstance(value, (bytes, bytearray)):
        _encode_bin(value, buf)
    elif isinstance(value, DateTimeValue):
        _encode_string(value.value, buf)
    elif isinstance(value, list):
        _encode_array(value, buf)
    elif isinstance(value, dict):
        _encode_map(value, buf)
    else:
        _encode_string(str(value), buf)


def _encode_integer(n: int, buf: bytearray):
    if n >= 0:
        if n <= 127:
            buf.append(n)
        elif n <= 0xFF:
            buf.extend([0xCC, n])
        elif n <= 0xFFFF:
            buf.append(0xCD)
            buf.extend(struct.pack('>H', n))
        elif n <= 0xFFFFFFFF:
            buf.append(0xCE)
            buf.extend(struct.pack('>I', n))
        else:
            buf.append(0xCF)
            buf.extend(struct.pack('>Q', n))
    else:
        if n >= -32:
            buf.append(n & 0xFF)
        elif n >= -128:
            buf.extend([0xD0, n & 0xFF])
        elif n >= -32768:
            buf.append(0xD1)
            buf.extend(struct.pack('>h', n))
        elif n >= -2147483648:
            buf.append(0xD2)
            buf.extend(struct.pack('>i', n))
        else:
            buf.append(0xD3)
            buf.extend(struct.pack('>q', n))


def _encode_float64(f: float, buf: bytearray):
    buf.append(0xCB)
    buf.extend(struct.pack('>d', f))


def _encode_string(s: str, buf: bytearray):
    encoded = s.encode('utf-8')
    length = len(encoded)
    if length <= 31:
        buf.append(0xA0 | length)
    elif length <= 0xFF:
        buf.extend([0xD9, length])
    elif length <= 0xFFFF:
        buf.append(0xDA)
        buf.extend(struct.pack('>H', length))
    else:
        buf.append(0xDB)
        buf.extend(struct.pack('>I', length))
    buf.extend(encoded)


def _encode_bin(data, buf: bytearray):
    length = len(data)
    if length <= 0xFF:
        buf.extend([0xC4, length])
    elif length <= 0xFFFF:
        buf.append(0xC5)
        buf.extend(struct.pack('>H', length))
    else:
        buf.append(0xC6)
        buf.extend(struct.pack('>I', length))
    buf.extend(data)


def _encode_array(arr: list, buf: bytearray):
    length = len(arr)
    if length <= 15:
        buf.append(0x90 | length)
    elif length <= 0xFFFF:
        buf.append(0xDC)
        buf.extend(struct.pack('>H', length))
    else:
        buf.append(0xDD)
        buf.extend(struct.pack('>I', length))
    for v in arr:
        _encode_value(v, buf)


def _encode_map(m: dict, buf: bytearray):
    entries = list(m.items())
    length = len(entries)
    if length <= 15:
        buf.append(0x80 | length)
    elif length <= 0xFFFF:
        buf.append(0xDE)
        buf.extend(struct.pack('>H', length))
    else:
        buf.append(0xDF)
        buf.extend(struct.pack('>I', length))
    for k, v in entries:
        _encode_string(str(k), buf)
        _encode_value(v, buf)

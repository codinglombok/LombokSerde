"""MessagePack decoder."""

import struct
from ..error import SerdeError, SerdeErrorCode


def decode(data: bytes):
    """Decode MessagePack bytes into a Value."""
    d = _MsgPackDecoder(data)
    return d.decode_value()


class _MsgPackDecoder:
    def __init__(self, data: bytes):
        self._data = data
        self._pos = 0

    def decode_value(self):
        byte = self._read_u8()

        # Positive fixint
        if byte <= 0x7F:
            return byte
        # Negative fixint
        if byte >= 0xE0:
            return byte - 256
        # Fixmap
        if 0x80 <= byte <= 0x8F:
            return self._decode_map(byte & 0x0F)
        # Fixarray
        if 0x90 <= byte <= 0x9F:
            return self._decode_array(byte & 0x0F)
        # Fixstr
        if 0xA0 <= byte <= 0xBF:
            return self._decode_string(byte & 0x1F)

        if byte == 0xC0:
            return None
        if byte == 0xC2:
            return False
        if byte == 0xC3:
            return True
        # bin 8/16/32
        if byte == 0xC4:
            return self._decode_bin(self._read_u8())
        if byte == 0xC5:
            return self._decode_bin(self._read_u16())
        if byte == 0xC6:
            return self._decode_bin(self._read_u32())
        # ext 8/16/32
        if byte == 0xC7:
            length = self._read_u8()
            self._pos += 1  # skip type
            return self._decode_bin(length)
        if byte == 0xC8:
            length = self._read_u16()
            self._pos += 1
            return self._decode_bin(length)
        if byte == 0xC9:
            length = self._read_u32()
            self._pos += 1
            return self._decode_bin(length)
        # float 32/64
        if byte == 0xCA:
            val = struct.unpack_from('>f', self._data, self._pos)[0]
            self._pos += 4
            return val
        if byte == 0xCB:
            val = struct.unpack_from('>d', self._data, self._pos)[0]
            self._pos += 8
            return val
        # uint 8/16/32/64
        if byte == 0xCC:
            return self._read_u8()
        if byte == 0xCD:
            return self._read_u16()
        if byte == 0xCE:
            return self._read_u32()
        if byte == 0xCF:
            return self._read_u64()
        # int 8/16/32/64
        if byte == 0xD0:
            v = self._read_u8()
            return v - 256 if v > 127 else v
        if byte == 0xD1:
            v = self._read_u16()
            return v - 65536 if v > 32767 else v
        if byte == 0xD2:
            v = self._read_u32()
            return v - 0x100000000 if v > 0x7FFFFFFF else v
        if byte == 0xD3:
            val = struct.unpack_from('>q', self._data, self._pos)[0]
            self._pos += 8
            return val
        # fixext 1/2/4/8/16
        if byte == 0xD4:
            self._pos += 1
            return self._decode_bin(1)
        if byte == 0xD5:
            self._pos += 1
            return self._decode_bin(2)
        if byte == 0xD6:
            self._pos += 1
            return self._decode_bin(4)
        if byte == 0xD7:
            self._pos += 1
            return self._decode_bin(8)
        if byte == 0xD8:
            self._pos += 1
            return self._decode_bin(16)
        # str 8/16/32
        if byte == 0xD9:
            return self._decode_string(self._read_u8())
        if byte == 0xDA:
            return self._decode_string(self._read_u16())
        if byte == 0xDB:
            return self._decode_string(self._read_u32())
        # array 16/32
        if byte == 0xDC:
            return self._decode_array(self._read_u16())
        if byte == 0xDD:
            return self._decode_array(self._read_u32())
        # map 16/32
        if byte == 0xDE:
            return self._decode_map(self._read_u16())
        if byte == 0xDF:
            return self._decode_map(self._read_u32())

        raise SerdeError(SerdeErrorCode.SYNTAX_ERROR, f"unknown msgpack byte 0x{byte:02x}")

    def _decode_string(self, length: int) -> str:
        end = self._pos + length
        if end > len(self._data):
            raise SerdeError(SerdeErrorCode.UNEXPECTED_EOF, "unexpected eof")
        s = self._data[self._pos:end].decode('utf-8')
        self._pos = end
        return s

    def _decode_bin(self, length: int) -> bytes:
        end = self._pos + length
        if end > len(self._data):
            raise SerdeError(SerdeErrorCode.UNEXPECTED_EOF, "unexpected eof")
        b = self._data[self._pos:end]
        self._pos = end
        return b

    def _decode_array(self, length: int) -> list:
        arr = []
        for _ in range(length):
            arr.append(self.decode_value())
        return arr

    def _decode_map(self, length: int) -> dict:
        m = {}
        for _ in range(length):
            key = self.decode_value()
            val = self.decode_value()
            m[str(key)] = val
        return m

    def _read_u8(self) -> int:
        if self._pos >= len(self._data):
            raise SerdeError(SerdeErrorCode.UNEXPECTED_EOF, "unexpected eof")
        val = self._data[self._pos]
        self._pos += 1
        return val

    def _read_u16(self) -> int:
        if self._pos + 2 > len(self._data):
            raise SerdeError(SerdeErrorCode.UNEXPECTED_EOF, "unexpected eof")
        val = struct.unpack_from('>H', self._data, self._pos)[0]
        self._pos += 2
        return val

    def _read_u32(self) -> int:
        if self._pos + 4 > len(self._data):
            raise SerdeError(SerdeErrorCode.UNEXPECTED_EOF, "unexpected eof")
        val = struct.unpack_from('>I', self._data, self._pos)[0]
        self._pos += 4
        return val

    def _read_u64(self) -> int:
        if self._pos + 8 > len(self._data):
            raise SerdeError(SerdeErrorCode.UNEXPECTED_EOF, "unexpected eof")
        val = struct.unpack_from('>Q', self._data, self._pos)[0]
        self._pos += 8
        return val

// Package msgpack provides MessagePack encoding and decoding.
package msgpack

import (
	"encoding/binary"
	"math"

	serde "github.com/codinglombok/LombokSerde/go"
)

// Encode encodes a Value to MessagePack bytes.
func Encode(v *serde.Value) []byte {
	var buf []byte
	buf = encodeValue(v, buf)
	return buf
}

func encodeValue(v *serde.Value, buf []byte) []byte {
	if v == nil {
		return append(buf, 0xC0)
	}
	switch v.Kind {
	case serde.KindNull:
		return append(buf, 0xC0)
	case serde.KindBool:
		if v.Bool {
			return append(buf, 0xC3)
		}
		return append(buf, 0xC2)
	case serde.KindInteger:
		return encodeInteger(v.Integer, buf)
	case serde.KindFloat:
		return encodeFloat64(v.Float, buf)
	case serde.KindString:
		return encodeString(v.Str, buf)
	case serde.KindBytes:
		return encodeBin(v.Bytes, buf)
	case serde.KindDateTime:
		if v.DateTime != nil {
			return encodeString(v.DateTime.Value, buf)
		}
		return append(buf, 0xC0)
	case serde.KindArray:
		return encodeArray(v.Array, buf)
	case serde.KindMap:
		return encodeMap(v.Map, buf)
	default:
		return append(buf, 0xC0)
	}
}

func encodeInteger(n int64, buf []byte) []byte {
	if n >= 0 {
		if n <= 127 {
			return append(buf, byte(n))
		} else if n <= 0xFF {
			return append(buf, 0xCC, byte(n))
		} else if n <= 0xFFFF {
			b := make([]byte, 2)
			binary.BigEndian.PutUint16(b, uint16(n))
			return append(append(buf, 0xCD), b...)
		} else if n <= 0xFFFFFFFF {
			b := make([]byte, 4)
			binary.BigEndian.PutUint32(b, uint32(n))
			return append(append(buf, 0xCE), b...)
		} else {
			b := make([]byte, 8)
			binary.BigEndian.PutUint64(b, uint64(n))
			return append(append(buf, 0xCF), b...)
		}
	} else {
		if n >= -32 {
			return append(buf, byte(n))
		} else if n >= -128 {
			return append(buf, 0xD0, byte(n))
		} else if n >= -32768 {
			b := make([]byte, 2)
			binary.BigEndian.PutUint16(b, uint16(int16(n)))
			return append(append(buf, 0xD1), b...)
		} else if n >= -2147483648 {
			b := make([]byte, 4)
			binary.BigEndian.PutUint32(b, uint32(int32(n)))
			return append(append(buf, 0xD2), b...)
		} else {
			b := make([]byte, 8)
			binary.BigEndian.PutUint64(b, uint64(n))
			return append(append(buf, 0xD3), b...)
		}
	}
}

func encodeFloat64(f float64, buf []byte) []byte {
	b := make([]byte, 8)
	binary.BigEndian.PutUint64(b, math.Float64bits(f))
	return append(append(buf, 0xCB), b...)
}

func encodeString(s string, buf []byte) []byte {
	data := []byte(s)
	length := len(data)
	if length <= 31 {
		buf = append(buf, byte(0xA0|length))
	} else if length <= 0xFF {
		buf = append(buf, 0xD9, byte(length))
	} else if length <= 0xFFFF {
		b := make([]byte, 2)
		binary.BigEndian.PutUint16(b, uint16(length))
		buf = append(append(buf, 0xDA), b...)
	} else {
		b := make([]byte, 4)
		binary.BigEndian.PutUint32(b, uint32(length))
		buf = append(append(buf, 0xDB), b...)
	}
	return append(buf, data...)
}

func encodeBin(data []byte, buf []byte) []byte {
	length := len(data)
	if length <= 0xFF {
		buf = append(buf, 0xC4, byte(length))
	} else if length <= 0xFFFF {
		b := make([]byte, 2)
		binary.BigEndian.PutUint16(b, uint16(length))
		buf = append(append(buf, 0xC5), b...)
	} else {
		b := make([]byte, 4)
		binary.BigEndian.PutUint32(b, uint32(length))
		buf = append(append(buf, 0xC6), b...)
	}
	return append(buf, data...)
}

func encodeArray(arr []*serde.Value, buf []byte) []byte {
	length := len(arr)
	if length <= 15 {
		buf = append(buf, byte(0x90|length))
	} else if length <= 0xFFFF {
		b := make([]byte, 2)
		binary.BigEndian.PutUint16(b, uint16(length))
		buf = append(append(buf, 0xDC), b...)
	} else {
		b := make([]byte, 4)
		binary.BigEndian.PutUint32(b, uint32(length))
		buf = append(append(buf, 0xDD), b...)
	}
	for _, v := range arr {
		buf = encodeValue(v, buf)
	}
	return buf
}

func encodeMap(m map[string]*serde.Value, buf []byte) []byte {
	length := len(m)
	if length <= 15 {
		buf = append(buf, byte(0x80|length))
	} else if length <= 0xFFFF {
		b := make([]byte, 2)
		binary.BigEndian.PutUint16(b, uint16(length))
		buf = append(append(buf, 0xDE), b...)
	} else {
		b := make([]byte, 4)
		binary.BigEndian.PutUint32(b, uint32(length))
		buf = append(append(buf, 0xDF), b...)
	}
	for k, v := range m {
		buf = encodeString(k, buf)
		buf = encodeValue(v, buf)
	}
	return buf
}

package msgpack

import (
	"encoding/binary"
	"fmt"
	"math"

	serde "github.com/codinglombok/LombokSerde/go"
)

// Decode decodes MessagePack bytes into a Value.
func Decode(data []byte) (*serde.Value, error) {
	d := &msgpackDecoder{data: data}
	return d.decodeValue()
}

type msgpackDecoder struct {
	data []byte
	pos  int
}

func (d *msgpackDecoder) decodeValue() (*serde.Value, error) {
	b, err := d.readU8()
	if err != nil {
		return nil, err
	}

	// Positive fixint
	if b <= 0x7F {
		return serde.Integer(int64(b)), nil
	}
	// Negative fixint
	if b >= 0xE0 {
		return serde.Integer(int64(b) - 256), nil
	}
	// Fixmap
	if b >= 0x80 && b <= 0x8F {
		return d.decodeMap(int(b & 0x0F))
	}
	// Fixarray
	if b >= 0x90 && b <= 0x9F {
		return d.decodeArray(int(b & 0x0F))
	}
	// Fixstr
	if b >= 0xA0 && b <= 0xBF {
		return d.decodeString(int(b & 0x1F))
	}

	switch b {
	case 0xC0:
		return serde.Null(), nil
	case 0xC2:
		return serde.Bool(false), nil
	case 0xC3:
		return serde.Bool(true), nil
	// bin 8/16/32
	case 0xC4:
		n, err := d.readU8()
		if err != nil {
			return nil, err
		}
		return d.decodeBin(int(n))
	case 0xC5:
		n, err := d.readU16()
		if err != nil {
			return nil, err
		}
		return d.decodeBin(int(n))
	case 0xC6:
		n, err := d.readU32()
		if err != nil {
			return nil, err
		}
		return d.decodeBin(int(n))
	// ext 8/16/32
	case 0xC7:
		n, err := d.readU8()
		if err != nil {
			return nil, err
		}
		d.pos++ // skip type
		return d.decodeBin(int(n))
	case 0xC8:
		n, err := d.readU16()
		if err != nil {
			return nil, err
		}
		d.pos++
		return d.decodeBin(int(n))
	case 0xC9:
		n, err := d.readU32()
		if err != nil {
			return nil, err
		}
		d.pos++
		return d.decodeBin(int(n))
	// float 32
	case 0xCA:
		if d.pos+4 > len(d.data) {
			return nil, eofError()
		}
		bits := binary.BigEndian.Uint32(d.data[d.pos:])
		d.pos += 4
		return serde.Float(float64(math.Float32frombits(bits))), nil
	// float 64
	case 0xCB:
		if d.pos+8 > len(d.data) {
			return nil, eofError()
		}
		bits := binary.BigEndian.Uint64(d.data[d.pos:])
		d.pos += 8
		return serde.Float(math.Float64frombits(bits)), nil
	// uint 8/16/32/64
	case 0xCC:
		n, err := d.readU8()
		if err != nil {
			return nil, err
		}
		return serde.Integer(int64(n)), nil
	case 0xCD:
		n, err := d.readU16()
		if err != nil {
			return nil, err
		}
		return serde.Integer(int64(n)), nil
	case 0xCE:
		n, err := d.readU32()
		if err != nil {
			return nil, err
		}
		return serde.Integer(int64(n)), nil
	case 0xCF:
		if d.pos+8 > len(d.data) {
			return nil, eofError()
		}
		v := binary.BigEndian.Uint64(d.data[d.pos:])
		d.pos += 8
		return serde.Integer(int64(v)), nil
	// int 8/16/32/64
	case 0xD0:
		n, err := d.readU8()
		if err != nil {
			return nil, err
		}
		if n > 127 {
			return serde.Integer(int64(n) - 256), nil
		}
		return serde.Integer(int64(n)), nil
	case 0xD1:
		n, err := d.readU16()
		if err != nil {
			return nil, err
		}
		if n > 32767 {
			return serde.Integer(int64(n) - 65536), nil
		}
		return serde.Integer(int64(n)), nil
	case 0xD2:
		n, err := d.readU32()
		if err != nil {
			return nil, err
		}
		if n > 0x7FFFFFFF {
			return serde.Integer(int64(n) - 0x100000000), nil
		}
		return serde.Integer(int64(n)), nil
	case 0xD3:
		if d.pos+8 > len(d.data) {
			return nil, eofError()
		}
		v := int64(binary.BigEndian.Uint64(d.data[d.pos:]))
		d.pos += 8
		return serde.Integer(v), nil
	// fixext 1/2/4/8/16
	case 0xD4:
		d.pos++
		return d.decodeBin(1)
	case 0xD5:
		d.pos++
		return d.decodeBin(2)
	case 0xD6:
		d.pos++
		return d.decodeBin(4)
	case 0xD7:
		d.pos++
		return d.decodeBin(8)
	case 0xD8:
		d.pos++
		return d.decodeBin(16)
	// str 8/16/32
	case 0xD9:
		n, err := d.readU8()
		if err != nil {
			return nil, err
		}
		return d.decodeString(int(n))
	case 0xDA:
		n, err := d.readU16()
		if err != nil {
			return nil, err
		}
		return d.decodeString(int(n))
	case 0xDB:
		n, err := d.readU32()
		if err != nil {
			return nil, err
		}
		return d.decodeString(int(n))
	// array 16/32
	case 0xDC:
		n, err := d.readU16()
		if err != nil {
			return nil, err
		}
		return d.decodeArray(int(n))
	case 0xDD:
		n, err := d.readU32()
		if err != nil {
			return nil, err
		}
		return d.decodeArray(int(n))
	// map 16/32
	case 0xDE:
		n, err := d.readU16()
		if err != nil {
			return nil, err
		}
		return d.decodeMap(int(n))
	case 0xDF:
		n, err := d.readU32()
		if err != nil {
			return nil, err
		}
		return d.decodeMap(int(n))
	default:
		return nil, &serde.SerdeError{Code: serde.ErrSyntaxError, Message: fmt.Sprintf("unknown msgpack byte 0x%02x", b)}
	}
}

func (d *msgpackDecoder) decodeString(length int) (*serde.Value, error) {
	end := d.pos + length
	if end > len(d.data) {
		return nil, eofError()
	}
	s := string(d.data[d.pos:end])
	d.pos = end
	return serde.String(s), nil
}

func (d *msgpackDecoder) decodeBin(length int) (*serde.Value, error) {
	end := d.pos + length
	if end > len(d.data) {
		return nil, eofError()
	}
	b := make([]byte, length)
	copy(b, d.data[d.pos:end])
	d.pos = end
	return serde.Bytes(b), nil
}

func (d *msgpackDecoder) decodeArray(length int) (*serde.Value, error) {
	arr := make([]*serde.Value, 0, length)
	for i := 0; i < length; i++ {
		v, err := d.decodeValue()
		if err != nil {
			return nil, err
		}
		arr = append(arr, v)
	}
	return serde.Array(arr...), nil
}

func (d *msgpackDecoder) decodeMap(length int) (*serde.Value, error) {
	m := make(map[string]*serde.Value, length)
	for i := 0; i < length; i++ {
		key, err := d.decodeValue()
		if err != nil {
			return nil, err
		}
		val, err := d.decodeValue()
		if err != nil {
			return nil, err
		}
		m[fmt.Sprintf("%v", valueToString(key))] = val
	}
	return serde.Map(m), nil
}

func valueToString(v *serde.Value) string {
	if v == nil {
		return "null"
	}
	switch v.Kind {
	case serde.KindString:
		return v.Str
	case serde.KindInteger:
		return fmt.Sprintf("%d", v.Integer)
	case serde.KindFloat:
		return fmt.Sprintf("%g", v.Float)
	case serde.KindBool:
		if v.Bool {
			return "true"
		}
		return "false"
	default:
		return "null"
	}
}

func (d *msgpackDecoder) readU8() (byte, error) {
	if d.pos >= len(d.data) {
		return 0, eofError()
	}
	v := d.data[d.pos]
	d.pos++
	return v, nil
}

func (d *msgpackDecoder) readU16() (uint16, error) {
	if d.pos+2 > len(d.data) {
		return 0, eofError()
	}
	v := binary.BigEndian.Uint16(d.data[d.pos:])
	d.pos += 2
	return v, nil
}

func (d *msgpackDecoder) readU32() (uint32, error) {
	if d.pos+4 > len(d.data) {
		return 0, eofError()
	}
	v := binary.BigEndian.Uint32(d.data[d.pos:])
	d.pos += 4
	return v, nil
}

func eofError() *serde.SerdeError {
	return &serde.SerdeError{Code: serde.ErrUnexpectedEof, Message: "unexpected eof"}
}

package lombokserde

import (
	"encoding/binary"
	"math"
	"strings"
	"unicode/utf8"
)

// MessagePack codec — canonical, byte-precise (see SPEC).
//
// Encoding pins: minimal-length integer/str/bin/array/map families; floats
// always float64; timestamps use timestamp32/64/96 per the spec's compact
// forms; ext types other than -1 are rejected (fail-closed).

// MsgPackOptions holds the MessagePack options.
type MsgPackOptions struct {
	DepthLimit int
}

// MsgpackDecode decodes exactly one MessagePack value; trailing bytes are
// an error.
func MsgpackDecode(data []byte, opts *MsgPackOptions) (Value, error) {
	limit := DefaultDepthLimit
	if opts != nil && opts.DepthLimit != 0 {
		limit = opts.DepthLimit
	}
	p := &mpParser{b: data, limit: limit}
	v, err := p.readValue(1)
	if err != nil {
		return Value{}, err
	}
	if p.i != len(data) {
		return Value{}, syntaxErr(ErrMPTrailing, p.i, "trailing bytes after the top-level value")
	}
	return v, nil
}

// MsgpackEncode encodes a value with the canonical (minimal) rules.
func MsgpackEncode(v Value, opts *MsgPackOptions) ([]byte, error) {
	limit := DefaultDepthLimit
	if opts != nil && opts.DepthLimit != 0 {
		limit = opts.DepthLimit
	}
	out := []byte{}
	if err := mpWrite(&out, v, 1, limit); err != nil {
		return nil, err
	}
	return out, nil
}

type mpParser struct {
	b     []byte
	i     int
	limit int
}

func (p *mpParser) need(n int) error {
	if p.i+n > len(p.b) {
		return syntaxErr(ErrMPTruncated, len(p.b), "unexpected end of input")
	}
	return nil
}

func (p *mpParser) take(n int) ([]byte, error) {
	if err := p.need(n); err != nil {
		return nil, err
	}
	s := p.b[p.i : p.i+n]
	p.i += n
	return s, nil
}

func (p *mpParser) readValue(depth int) (Value, error) {
	raw, err := p.take(1)
	if err != nil {
		return Value{}, err
	}
	m := raw[0]
	switch {
	case m <= 0x7F:
		return NewInt(int64(m)), nil
	case m >= 0xE0:
		return NewInt(int64(int8(m))), nil
	case m >= 0x80 && m <= 0x8F:
		return p.readMap(int(m&0x0F), depth)
	case m >= 0x90 && m <= 0x9F:
		return p.readArray(int(m&0x0F), depth)
	case m >= 0xA0 && m <= 0xBF:
		s, err := p.readStr(int(m & 0x1F))
		if err != nil {
			return Value{}, err
		}
		return NewStr(s), nil
	}
	switch m {
	case 0xC0:
		return NewNull(), nil
	case 0xC1:
		return Value{}, syntaxErr(ErrMPUnexpected, p.i-1, "reserved type code 0xc1")
	case 0xC2:
		return NewBool(false), nil
	case 0xC3:
		return NewBool(true), nil
	case 0xC4, 0xC5, 0xC6:
		n, err := p.readLen(int(m-0xC4), 1)
		if err != nil {
			return Value{}, err
		}
		bs, err := p.take(n)
		if err != nil {
			return Value{}, err
		}
		return NewBytes(append([]byte{}, bs...)), nil
	case 0xC7, 0xC8, 0xC9:
		n, err := p.readLen(int(m-0xC7), 1)
		if err != nil {
			return Value{}, err
		}
		return p.readExt(n)
	case 0xCA:
		bs, err := p.take(4)
		if err != nil {
			return Value{}, err
		}
		bits := binary.BigEndian.Uint32(bs)
		return NewFloat(float64(math.Float32frombits(bits))), nil
	case 0xCB:
		bs, err := p.take(8)
		if err != nil {
			return Value{}, err
		}
		return NewFloat(math.Float64frombits(binary.BigEndian.Uint64(bs))), nil
	case 0xCC, 0xCD, 0xCE, 0xCF:
		n := 1 << (m - 0xCC)
		bs, err := p.take(n)
		if err != nil {
			return Value{}, err
		}
		return intOrUint(binary.BigEndian.Uint64(padBE(bs, 8))), nil
	case 0xD0, 0xD1, 0xD2, 0xD3:
		n := 1 << (m - 0xD0)
		bs, err := p.take(n)
		if err != nil {
			return Value{}, err
		}
		v := int64(binary.BigEndian.Uint64(padBE(bs, 8)))
		if bs[0]&0x80 != 0 {
			// sign-extend from the actual width
			v -= 1 << (8 * n)
		}
		return NewInt(v), nil
	case 0xD4, 0xD5, 0xD6, 0xD7, 0xD8:
		n := 1 << (m - 0xD4)
		return p.readExt(n)
	case 0xD9, 0xDA, 0xDB:
		n, err := p.readLen(int(m-0xD9), 1)
		if err != nil {
			return Value{}, err
		}
		s, err := p.readStr(n)
		if err != nil {
			return Value{}, err
		}
		return NewStr(s), nil
	case 0xDC, 0xDD:
		n, err := p.readLen(int(m-0xDB), 2)
		if err != nil {
			return Value{}, err
		}
		return p.readArray(n, depth)
	case 0xDE, 0xDF:
		n, err := p.readLen(int(m-0xDD), 2)
		if err != nil {
			return Value{}, err
		}
		return p.readMap(n, depth)
	}
	return Value{}, syntaxErr(ErrMPUnexpected, p.i-1, "invalid type code")
}

// padBE left-pads a big-endian slice to n bytes so binary.BigEndian can
// read fixed-width integers.
func padBE(bs []byte, n int) []byte {
	if len(bs) >= n {
		return bs
	}
	out := make([]byte, n)
	copy(out[n-len(bs):], bs)
	return out
}

func (p *mpParser) readLen(sizeClass, minBytes int) (int, error) {
	var n int
	switch sizeClass {
	case 0:
		bs, err := p.take(1)
		if err != nil {
			return 0, err
		}
		n = int(bs[0])
	case 1:
		bs, err := p.take(2)
		if err != nil {
			return 0, err
		}
		n = int(binary.BigEndian.Uint16(bs))
	default:
		bs, err := p.take(4)
		if err != nil {
			return 0, err
		}
		n = int(binary.BigEndian.Uint32(bs))
	}
	if n < minBytes {
		return 0, syntaxErr(ErrMPUnexpected, p.i, "length field below the minimum for this type")
	}
	return n, nil
}

func intOrUint(v uint64) Value {
	if v <= uint64(1<<63-1) {
		return NewInt(int64(v))
	}
	return NewUint(v)
}

func (p *mpParser) readStr(n int) (string, error) {
	start := p.i
	bs, err := p.take(n)
	if err != nil {
		return "", err
	}
	if !utf8.Valid(bs) {
		return "", syntaxErr(ErrMPUTF8, start, "invalid UTF-8 in string")
	}
	return string(bs), nil
}

func (p *mpParser) readArray(n, depth int) (Value, error) {
	if depth > p.limit {
		return Value{}, syntaxErr(ErrMPDepth, p.i, "depth limit exceeded")
	}
	items := make([]Value, 0, min64(int64(n), 4096))
	for j := 0; j < n; j++ {
		v, err := p.readValue(depth + 1)
		if err != nil {
			return Value{}, err
		}
		items = append(items, v)
	}
	return NewArray(items), nil
}

func min64(a, b int64) int64 {
	if a < b {
		return a
	}
	return b
}

func (p *mpParser) readMap(n, depth int) (Value, error) {
	if depth > p.limit {
		return Value{}, syntaxErr(ErrMPDepth, p.i, "depth limit exceeded")
	}
	pairs := make([]TableEntry, 0, min64(int64(n), 4096))
	for j := 0; j < n; j++ {
		k, err := p.readValue(depth + 1)
		if err != nil {
			return Value{}, err
		}
		if k.Kind != KindStr {
			return Value{}, syntaxErr(ErrMPUnexpected, p.i, "map key is not a string")
		}
		v, err := p.readValue(depth + 1)
		if err != nil {
			return Value{}, err
		}
		pairs = append(pairs, TableEntry{Key: k.Str, Value: v})
	}
	tab, terr := NewTable(pairs)
	if terr != nil {
		return Value{}, syntaxErr(ErrMPDuplicate, p.i, "duplicate map key")
	}
	return tab, nil
}

func (p *mpParser) readExt(n int) (Value, error) {
	tb, err := p.take(1)
	if err != nil {
		return Value{}, err
	}
	etype := int(int8(tb[0]))
	if etype != -1 {
		return Value{}, syntaxErr(ErrMPExt, p.i-1, "unsupported extension type")
	}
	switch n {
	case 4:
		bs, err := p.take(4)
		if err != nil {
			return Value{}, err
		}
		sec := int64(binary.BigEndian.Uint32(bs))
		return datetimeFromTimestamp(sec, 0), nil
	case 8:
		bs, err := p.take(8)
		if err != nil {
			return Value{}, err
		}
		bits := binary.BigEndian.Uint64(bs)
		ns := bits >> 34
		sec := bits & ((1 << 34) - 1)
		if ns > 999_999_999 {
			return Value{}, syntaxErr(ErrMPUnexpected, p.i-8, "nanoseconds out of range")
		}
		return datetimeFromTimestamp(int64(sec), int64(ns)), nil
	case 12:
		bs, err := p.take(12)
		if err != nil {
			return Value{}, err
		}
		ns := binary.BigEndian.Uint32(bs[0:4])
		sec := int64(binary.BigEndian.Uint64(bs[4:12]))
		if ns > 999_999_999 {
			return Value{}, syntaxErr(ErrMPUnexpected, p.i-12, "nanoseconds out of range")
		}
		return datetimeFromTimestamp(sec, int64(ns)), nil
	}
	return Value{}, syntaxErr(ErrMPExt, p.i-1, "unsupported timestamp payload length")
}

func datetimeFromTimestamp(sec, ns int64) Value {
	return NewDatetime(DatetimeOffset, FormatTimestamp(sec, ns))
}

func mpWrite(out *[]byte, v Value, depth, limit int) error {
	switch v.Kind {
	case KindNull:
		*out = append(*out, 0xC0)
	case KindBool:
		if v.Bool {
			*out = append(*out, 0xC3)
		} else {
			*out = append(*out, 0xC2)
		}
	case KindInt:
		mpWriteInt(out, v.Int)
	case KindUint:
		n := v.Uint
		switch {
		case n <= 0x7F:
			*out = append(*out, byte(n))
		case n <= 0xFF:
			*out = append(*out, 0xCC, byte(n))
		case n <= 0xFFFF:
			*out = append(*out, 0xCD)
			*out = binary.BigEndian.AppendUint16(*out, uint16(n))
		case n <= 0xFFFFFFFF:
			*out = append(*out, 0xCE)
			*out = binary.BigEndian.AppendUint32(*out, uint32(n))
		default:
			*out = append(*out, 0xCF)
			*out = binary.BigEndian.AppendUint64(*out, n)
		}
	case KindFloat:
		*out = append(*out, 0xCB)
		bits := math.Float64bits(v.Float)
		if math.IsNaN(v.Float) {
			// SPEC: NaN always encodes as the canonical quiet NaN; Go's
			// runtime NaN carries an extra payload bit.
			bits = 0x7FF8000000000000
		}
		*out = binary.BigEndian.AppendUint64(*out, bits)
	case KindStr:
		sb := []byte(v.Str)
		n := len(sb)
		switch {
		case n <= 31:
			*out = append(*out, 0xA0|byte(n))
		case n <= 0xFF:
			*out = append(*out, 0xD9, byte(n))
		case n <= 0xFFFF:
			*out = append(*out, 0xDA)
			*out = binary.BigEndian.AppendUint16(*out, uint16(n))
		default:
			*out = append(*out, 0xDB)
			*out = binary.BigEndian.AppendUint32(*out, uint32(n))
		}
		*out = append(*out, sb...)
	case KindBytes:
		n := len(v.Bytes)
		switch {
		case n <= 0xFF:
			*out = append(*out, 0xC4, byte(n))
		case n <= 0xFFFF:
			*out = append(*out, 0xC5)
			*out = binary.BigEndian.AppendUint16(*out, uint16(n))
		default:
			*out = append(*out, 0xC6)
			*out = binary.BigEndian.AppendUint32(*out, uint32(n))
		}
		*out = append(*out, v.Bytes...)
	case KindArray:
		if depth > limit {
			return NewError(ErrMPDepth, "depth limit exceeded", nil)
		}
		n := len(v.Array)
		switch {
		case n <= 15:
			*out = append(*out, 0x90|byte(n))
		case n <= 0xFFFF:
			*out = append(*out, 0xDC)
			*out = binary.BigEndian.AppendUint16(*out, uint16(n))
		default:
			*out = append(*out, 0xDD)
			*out = binary.BigEndian.AppendUint32(*out, uint32(n))
		}
		for _, x := range v.Array {
			if err := mpWrite(out, x, depth+1, limit); err != nil {
				return err
			}
		}
	case KindTable:
		if depth > limit {
			return NewError(ErrMPDepth, "depth limit exceeded", nil)
		}
		n := len(v.Table)
		switch {
		case n <= 15:
			*out = append(*out, 0x80|byte(n))
		case n <= 0xFFFF:
			*out = append(*out, 0xDE)
			*out = binary.BigEndian.AppendUint16(*out, uint16(n))
		default:
			*out = append(*out, 0xDF)
			*out = binary.BigEndian.AppendUint32(*out, uint32(n))
		}
		for _, e := range v.Table {
			if err := mpWrite(out, NewStr(e.Key), depth, limit); err != nil {
				return err
			}
			if err := mpWrite(out, e.Value, depth+1, limit); err != nil {
				return err
			}
		}
	case KindDatetime:
		return mpWriteDatetime(out, v.Datetime)
	default:
		return NewError(ErrMPUnexpected, "unsupported value kind: "+string(v.Kind), nil)
	}
	return nil
}

func mpWriteInt(out *[]byte, n int64) {
	switch {
	case n >= 0 && n <= 0x7F:
		*out = append(*out, byte(n))
	case n > 0:
		switch {
		case n <= 0xFF:
			*out = append(*out, 0xCC, byte(n))
		case n <= 0xFFFF:
			*out = append(*out, 0xCD)
			*out = binary.BigEndian.AppendUint16(*out, uint16(n))
		case n <= 0xFFFFFFFF:
			*out = append(*out, 0xCE)
			*out = binary.BigEndian.AppendUint32(*out, uint32(n))
		default:
			*out = append(*out, 0xCF)
			*out = binary.BigEndian.AppendUint64(*out, uint64(n))
		}
	case n >= -32:
		*out = append(*out, byte(0xE0|(n+32)))
	case n >= -128:
		*out = append(*out, 0xD0, byte(n))
	case n >= -32768:
		*out = append(*out, 0xD1)
		*out = binary.BigEndian.AppendUint16(*out, uint16(int16(n)))
	case n >= math.MinInt32:
		*out = append(*out, 0xD2)
		*out = binary.BigEndian.AppendUint32(*out, uint32(int32(n)))
	default:
		*out = append(*out, 0xD3)
		*out = binary.BigEndian.AppendUint64(*out, uint64(n))
	}
}

func mpWriteDatetime(out *[]byte, dt Datetime) error {
	if dt.Kind != DatetimeOffset {
		return NewError(ErrMPDatetime, "only Offset datetimes map to MessagePack timestamps", nil)
	}
	parsed, ok := ParseOffsetDatetime(dt.Raw)
	if !ok {
		return NewError(ErrMPDatetime, "datetime raw text is not a valid RFC 3339 offset datetime", nil)
	}
	sec, ns := parsed.sec, parsed.ns
	if ns == 0 && sec >= 0 && sec <= 0xFFFFFFFF {
		*out = append(*out, 0xD6, 0xFF)
		*out = binary.BigEndian.AppendUint32(*out, uint32(sec))
	} else if sec >= 0 && sec <= (1<<34)-1 {
		bits := (uint64(ns) << 34) | uint64(sec)
		*out = append(*out, 0xD7, 0xFF)
		*out = binary.BigEndian.AppendUint64(*out, bits)
	} else {
		*out = append(*out, 0xC7, 12, 0xFF)
		*out = binary.BigEndian.AppendUint32(*out, uint32(ns))
		*out = binary.BigEndian.AppendUint64(*out, uint64(sec))
	}
	return nil
}

// --- calendar math (identical integer arithmetic in every port) -----------

type timestampParts struct {
	sec int64
	ns  int64
}

// DaysFromCivil returns days since 1970-01-01 (Howard Hinnant's algorithm).
func DaysFromCivil(y, m, d int64) int64 {
	yy := y
	if m <= 2 {
		yy = y - 1
	}
	era := yy / 400
	if yy < 0 && yy%400 != 0 {
		era = (yy - 399) / 400
	}
	yoe := yy - era*400
	mp := m - 3
	if m <= 2 {
		mp = m + 9
	}
	doy := (153*mp+2)/5 + d - 1
	doe := yoe*365 + yoe/4 - yoe/100 + doy
	return era*146097 + doe - 719468
}

// CivilFromDays returns the civil date for days since 1970-01-01.
func CivilFromDays(z int64) (int64, int64, int64) {
	zz := z + 719468
	era := zz / 146097
	if zz < 0 && zz%146097 != 0 {
		era = (zz - 146096) / 146097
	}
	doe := zz - era*146097
	yoe := (doe - doe/1460 + doe/36524 - doe/146096) / 365
	y := yoe + era*400
	doy := doe - (365*yoe + yoe/4 - yoe/100)
	mp := (5*doy + 2) / 153
	d := doy - (153*mp+2)/5 + 1
	m := mp + 3
	if mp >= 10 {
		m = mp - 9
	}
	if m <= 2 {
		y++
	}
	return y, m, d
}

type offsetDT struct {
	sec int64
	ns  int64
}

// ParseOffsetDatetime parses an RFC 3339 offset datetime.
func ParseOffsetDatetime(raw string) (offsetDT, bool) {
	b := []byte(raw)
	digits := func(from, to int) (int64, bool) {
		if from < 0 || to > len(b) {
			return 0, false
		}
		var v int64
		for j := from; j < to; j++ {
			if b[j] < '0' || b[j] > '9' {
				return 0, false
			}
			v = v*10 + int64(b[j]-'0')
		}
		return v, true
	}
	if len(b) < 20 {
		return offsetDT{}, false
	}
	if !(b[4] == '-' && b[7] == '-' && (b[10] == 'T' || b[10] == 't' || b[10] == 0x20) && b[13] == ':' && b[16] == ':') {
		return offsetDT{}, false
	}
	y, ok1 := digits(0, 4)
	mo, ok2 := digits(5, 7)
	d, ok3 := digits(8, 10)
	h, ok4 := digits(11, 13)
	mi, ok5 := digits(14, 16)
	sv, ok6 := digits(17, 19)
	if !ok1 || !ok2 || !ok3 || !ok4 || !ok5 || !ok6 {
		return offsetDT{}, false
	}
	i := 19
	var ns int64
	if i < len(b) && b[i] == '.' {
		i++
		start := i
		for i < len(b) && b[i] >= '0' && b[i] <= '9' {
			i++
		}
		if i == start {
			return offsetDT{}, false
		}
		scale := int64(100000000)
		for j := start; j < i && scale > 0; j++ {
			ns += int64(b[j]-'0') * scale
			scale /= 10
		}
	}
	if sv == 60 {
		return offsetDT{}, false // leap seconds are not representable
	}
	if !(mo >= 1 && mo <= 12 && d >= 1 && d <= 31 && h <= 23 && mi <= 59) {
		return offsetDT{}, false
	}
	var sec int64
	if i < len(b) && (b[i] == 'Z' || b[i] == 'z') {
		if i+1 != len(b) {
			return offsetDT{}, false
		}
		sec = DaysFromCivil(y, mo, d)*86400 + h*3600 + mi*60 + sv
	} else if i+5 < len(b) && (b[i] == '+' || b[i] == '-') && b[i+3] == ':' {
		if i+6 != len(b) {
			return offsetDT{}, false
		}
		oh, ok1 := digits(i+1, i+3)
		om, ok2 := digits(i+4, i+6)
		if !ok1 || !ok2 || oh > 23 || om > 59 {
			return offsetDT{}, false
		}
		off := oh*3600 + om*60
		base := DaysFromCivil(y, mo, d)*86400 + h*3600 + mi*60 + sv
		if b[i] == '+' {
			sec = base - off
		} else {
			sec = base + off
		}
	} else {
		return offsetDT{}, false
	}
	return offsetDT{sec: sec, ns: ns}, true
}

// FormatTimestamp renders epoch seconds + nanoseconds as canonical `...Z`.
func FormatTimestamp(sec, ns int64) string {
	days := floorDiv(sec, 86400)
	rem := sec - days*86400
	y, mo, d := CivilFromDays(days)
	h := rem / 3600
	mi := (rem % 3600) / 60
	s := rem % 60
	frac := ""
	if ns != 0 {
		frac = "." + pad9(ns)
		frac = strings.TrimRight(frac, "0")
	}
	return pad4(y) + "-" + pad2(mo) + "-" + pad2(d) + "T" + pad2(h) + ":" + pad2(mi) + ":" + pad2(s) + frac + "Z"
}

func floorDiv(a, b int64) int64 {
	q := a / b
	if a%b != 0 && (a < 0) != (b < 0) {
		q--
	}
	return q
}

func pad2(v int64) string {
	if v < 10 {
		return "0" + itoa(int(v))
	}
	return itoa(int(v))
}

func pad4(v int64) string {
	neg := v < 0
	av := v
	if neg {
		av = -v
	}
	s := itoa(int(av))
	for len(s) < 4 {
		s = "0" + s
	}
	if neg {
		return "-" + s
	}
	return s
}

func pad9(v int64) string {
	s := itoa(int(v))
	for len(s) < 9 {
		s = "0" + s
	}
	return s
}

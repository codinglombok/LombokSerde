package lombokserde

import (
	"errors"
	"strconv"
	"strings"
	"unicode/utf8"
)

// JSON codec (RFC 8259) — canonical, byte-precise (see SPEC).

// JsonOptions holds the JSON options; DepthLimit is the maximum container
// nesting (the outermost container is depth 1).
type JsonOptions struct {
	DepthLimit int
}

// DefaultDepthLimit is the default maximum container nesting for every
// format and port.
const DefaultDepthLimit = 128

// JsonDecode decodes exactly one JSON value; trailing non-whitespace is an
// error.
func JsonDecode(data []byte, opts *JsonOptions) (Value, error) {
	limit := DefaultDepthLimit
	if opts != nil && opts.DepthLimit != 0 {
		limit = opts.DepthLimit
	}
	if bad := utf8FirstBadOffset(data); bad != -1 {
		return Value{}, syntaxErr(ErrJSONUTF8, bad, "invalid UTF-8")
	}
	p := &jsonParser{b: data, limit: limit}
	v, err := p.parseValue(1)
	if err != nil {
		return Value{}, err
	}
	p.skipWs()
	if p.i != len(data) {
		return Value{}, syntaxErr(ErrJSONTrailing, p.i, "trailing characters after the top-level value")
	}
	return v, nil
}

// JsonEncode encodes a value as canonical compact JSON: no whitespace,
// table keys sorted bytewise, shortest-roundtrip floats.
func JsonEncode(v Value, opts *JsonOptions) ([]byte, error) {
	limit := DefaultDepthLimit
	if opts != nil && opts.DepthLimit != 0 {
		limit = opts.DepthLimit
	}
	var out strings.Builder
	if err := jsonWrite(&out, v, 1, limit); err != nil {
		return nil, err
	}
	return []byte(out.String()), nil
}

func utf8FirstBadOffset(b []byte) int {
	i := 0
	for i < len(b) {
		c := b[i]
		if c < 0x80 {
			i++
			continue
		}
		var ln, lo, hi int
		switch {
		case c >= 0xC2 && c <= 0xDF:
			ln, lo, hi = 2, 0x80, 0xBF
		case c == 0xE0:
			ln, lo, hi = 3, 0xA0, 0xBF
		case c >= 0xE1 && c <= 0xEC:
			ln, lo, hi = 3, 0x80, 0xBF
		case c == 0xED:
			ln, lo, hi = 3, 0x80, 0x9F
		case c >= 0xEE && c <= 0xEF:
			ln, lo, hi = 3, 0x80, 0xBF
		case c == 0xF0:
			ln, lo, hi = 4, 0x90, 0xBF
		case c >= 0xF1 && c <= 0xF3:
			ln, lo, hi = 4, 0x80, 0xBF
		case c == 0xF4:
			ln, lo, hi = 4, 0x80, 0x8F
		default:
			return i
		}
		if i+ln > len(b) {
			return i
		}
		for j := 1; j < ln; j++ {
			cc := b[i+j]
			l2, h2 := lo, hi
			if j != 1 {
				l2, h2 = 0x80, 0xBF
			}
			if cc < uint8(l2) || cc > uint8(h2) {
				return i
			}
		}
		i += ln
	}
	return -1
}

type jsonParser struct {
	b     []byte
	i     int
	limit int
}

func (p *jsonParser) skipWs() {
	for p.i < len(p.b) {
		c := p.b[p.i]
		if c == 0x20 || c == 0x09 || c == 0x0A || c == 0x0D {
			p.i++
			continue
		}
		break
	}
}

func (p *jsonParser) fail(detail string) error {
	return syntaxErr(ErrJSONSyntax, p.i, detail)
}

func (p *jsonParser) parseValue(depth int) (Value, error) {
	p.skipWs()
	if p.i >= len(p.b) {
		return Value{}, p.fail("unexpected end of input")
	}
	c := p.b[p.i]
	switch {
	case c == 0x7B:
		if depth > p.limit {
			return Value{}, syntaxErr(ErrJSONDepth, p.i, "depth limit exceeded")
		}
		return p.parseObject(depth)
	case c == 0x5B:
		if depth > p.limit {
			return Value{}, syntaxErr(ErrJSONDepth, p.i, "depth limit exceeded")
		}
		return p.parseArray(depth)
	case c == 0x22:
		s, err := p.parseString()
		if err != nil {
			return Value{}, err
		}
		return NewStr(s), nil
	case c == 0x74:
		if err := p.expect("true"); err != nil {
			return Value{}, err
		}
		return NewBool(true), nil
	case c == 0x66:
		if err := p.expect("false"); err != nil {
			return Value{}, err
		}
		return NewBool(false), nil
	case c == 0x6E:
		if err := p.expect("null"); err != nil {
			return Value{}, err
		}
		return NewNull(), nil
	case c == 0x2D || (c >= 0x30 && c <= 0x39):
		return p.parseNumber()
	}
	return Value{}, p.fail("unexpected character")
}

func (p *jsonParser) expect(word string) error {
	w := []byte(word)
	if len(p.b)-p.i < len(w) {
		return p.fail("invalid literal")
	}
	for j := 0; j < len(w); j++ {
		if p.b[p.i+j] != w[j] {
			return p.fail("invalid literal")
		}
	}
	p.i += len(w)
	return nil
}

func (p *jsonParser) parseObject(depth int) (Value, error) {
	p.i++ // {
	pairs := []TableEntry{}
	p.skipWs()
	if p.i < len(p.b) && p.b[p.i] == 0x7D {
		p.i++
		return TableUnchecked(pairs), nil
	}
	for {
		p.skipWs()
		if p.i >= len(p.b) || p.b[p.i] != 0x22 {
			return Value{}, p.fail("expected object key")
		}
		k, err := p.parseString()
		if err != nil {
			return Value{}, err
		}
		p.skipWs()
		if p.i >= len(p.b) || p.b[p.i] != 0x3A {
			return Value{}, p.fail("expected ':'")
		}
		p.i++
		v, err := p.parseValue(depth + 1)
		if err != nil {
			return Value{}, err
		}
		pairs = append(pairs, TableEntry{Key: k, Value: v})
		p.skipWs()
		if p.i >= len(p.b) {
			return Value{}, p.fail("unterminated object")
		}
		switch p.b[p.i] {
		case 0x2C:
			p.i++
			continue
		case 0x7D:
			p.i++
			tab, terr := NewTable(pairs)
			if terr != nil {
				return Value{}, syntaxErr(ErrJSONSyntax, p.i, "duplicate object key")
			}
			return tab, nil
		}
		return Value{}, p.fail("expected ',' or '}'")
	}
}

func (p *jsonParser) parseArray(depth int) (Value, error) {
	p.i++ // [
	items := []Value{}
	p.skipWs()
	if p.i < len(p.b) && p.b[p.i] == 0x5D {
		p.i++
		return NewArray(items), nil
	}
	for {
		v, err := p.parseValue(depth + 1)
		if err != nil {
			return Value{}, err
		}
		items = append(items, v)
		p.skipWs()
		if p.i >= len(p.b) {
			return Value{}, p.fail("unterminated array")
		}
		switch p.b[p.i] {
		case 0x2C:
			p.i++
			continue
		case 0x5D:
			p.i++
			return NewArray(items), nil
		}
		return Value{}, p.fail("expected ',' or ']'")
	}
}

func (p *jsonParser) parseString() (string, error) {
	p.i++ // opening quote
	var out []rune
	for {
		if p.i >= len(p.b) {
			return "", p.fail("unterminated string")
		}
		c := p.b[p.i]
		if c == 0x22 {
			p.i++
			return string(out), nil
		}
		if c == 0x5C {
			p.i++
			if p.i >= len(p.b) {
				return "", p.fail("unterminated escape")
			}
			e := p.b[p.i]
			switch e {
			case '"':
				out = append(out, '"')
				p.i++
			case '\\':
				out = append(out, '\\')
				p.i++
			case '/':
				out = append(out, '/')
				p.i++
			case 'b':
				out = append(out, '\b')
				p.i++
			case 'f':
				out = append(out, '\f')
				p.i++
			case 'n':
				out = append(out, '\n')
				p.i++
			case 'r':
				out = append(out, '\r')
				p.i++
			case 't':
				out = append(out, '\t')
				p.i++
			case 'u':
				cp, err := p.parseHex4()
				if err != nil {
					return "", err
				}
				if cp >= 0xD800 && cp <= 0xDBFF {
					// after parseHex4 the cursor sits on the next char: a
					// trailing pair escape starts here
					if p.i+1 < len(p.b) && p.b[p.i] == 0x5C && p.b[p.i+1] == 0x75 {
						p.i++ // land on the 'u' of the low escape
						lo, err := p.parseHex4()
						if err != nil {
							return "", err
						}
						if lo >= 0xDC00 && lo <= 0xDFFF {
							cc := 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00)
							out = append(out, rune(cc))
						} else {
							return "", p.fail("invalid low surrogate")
						}
					} else {
						return "", p.fail("lone high surrogate")
					}
				} else if cp >= 0xDC00 && cp <= 0xDFFF {
					return "", p.fail("lone low surrogate")
				} else {
					out = append(out, rune(cp))
				}
			default:
				return "", p.fail("invalid escape")
			}
			continue
		}
		if c < 0x20 {
			return "", p.fail("raw control character in string")
		}
		// consume one UTF-8 code point (input is pre-validated)
		r, size := utf8.DecodeRune(p.b[p.i:])
		out = append(out, r)
		p.i += size
	}
}

func (p *jsonParser) parseHex4() (int, error) {
	if p.i >= len(p.b) || p.b[p.i] != 0x75 {
		return 0, p.fail("expected \\u")
	}
	if p.i+4 >= len(p.b) {
		return 0, p.fail("truncated \\u escape")
	}
	h := string(p.b[p.i+1 : p.i+5])
	var cp int
	for _, ch := range h {
		var d int
		switch {
		case ch >= '0' && ch <= '9':
			d = int(ch - '0')
		case ch >= 'a' && ch <= 'f':
			d = int(ch-'a') + 10
		case ch >= 'A' && ch <= 'F':
			d = int(ch-'A') + 10
		default:
			return 0, p.fail("invalid \\u escape")
		}
		cp = cp*16 + d
	}
	p.i += 5
	return cp, nil
}

func (p *jsonParser) parseNumber() (Value, error) {
	start := p.i
	b := p.b
	if b[p.i] == 0x2D {
		p.i++
		if p.i >= len(b) {
			return Value{}, p.fail("unexpected end of input")
		}
	}
	if b[p.i] == 0x30 {
		p.i++
	} else if b[p.i] >= 0x31 && b[p.i] <= 0x39 {
		for p.i < len(b) && b[p.i] >= 0x30 && b[p.i] <= 0x39 {
			p.i++
		}
	} else {
		return Value{}, p.fail("invalid number")
	}
	isFloat := false
	if p.i < len(b) && b[p.i] == 0x2E {
		isFloat = true
		p.i++
		if p.i >= len(b) || b[p.i] < 0x30 || b[p.i] > 0x39 {
			return Value{}, p.fail("expected digit after '.'")
		}
		for p.i < len(b) && b[p.i] >= 0x30 && b[p.i] <= 0x39 {
			p.i++
		}
	}
	if p.i < len(b) && (b[p.i] == 0x65 || b[p.i] == 0x45) {
		isFloat = true
		p.i++
		if p.i < len(b) && (b[p.i] == 0x2B || b[p.i] == 0x2D) {
			p.i++
		}
		if p.i >= len(b) || b[p.i] < 0x30 || b[p.i] > 0x39 {
			return Value{}, p.fail("expected digit in exponent")
		}
		for p.i < len(b) && b[p.i] >= 0x30 && b[p.i] <= 0x39 {
			p.i++
		}
	}
	text := string(b[start:p.i])
	if !isFloat {
		if n, err := parseInt64(text); err == nil {
			return NewInt(n), nil
		}
		if u, err := parseUint64(text); err == nil {
			return NewUint(u), nil
		}
		return Value{}, syntaxErr(ErrJSONIntRange, start, "integer out of 64-bit range")
	}
	return NewFloat(parseFloat64(text)), nil
}

func parseInt64(text string) (int64, error) {
	neg := len(text) > 0 && text[0] == '-'
	digits := text
	if neg {
		digits = text[1:]
	}
	u, err := parseUint64(digits)
	if err != nil {
		return 0, err
	}
	if neg {
		// i64::MIN is -(2^63); everything above it must fail
		if u > 1<<63 {
			return 0, errRange
		}
		if u == 1<<63 {
			return math_MinInt64, nil
		}
		return -int64(u), nil
	}
	if u > 1<<63-1 {
		return 0, errRange
	}
	return int64(u), nil
}

func parseUint64(text string) (uint64, error) {
	if len(text) > 0 && text[0] == '-' {
		return 0, errRange
	}
	var n uint64
	for j := 0; j < len(text); j++ {
		d := uint64(text[j] - '0')
		if n > (1<<64-1-d)/10 {
			return 0, errRange
		}
		n = n*10 + d
	}
	return n, nil
}

var errRange = errors.New("range")

const math_MinInt64 int64 = -1 << 63

// parseFloat64 parses an RFC 8259 number literal; Go's ParseFloat is a
// correctly-rounded strtod, identical to every other port's platform
// formatter. The grammar above guarantees validity, so the error is moot.
func parseFloat64(text string) float64 {
	f, _ := strconv.ParseFloat(text, 64)
	return f
}

func itoa(n int) string {
	return strconv.Itoa(n)
}

func parseInt64Base(text string, base int) (int64, error) {
	var n int64
	for j := 0; j < len(text); j++ {
		var d int64
		c := text[j]
		switch {
		case c >= '0' && c <= '9':
			d = int64(c - '0')
		case c >= 'a' && c <= 'f':
			d = int64(c-'a') + 10
		case c >= 'A' && c <= 'F':
			d = int64(c-'A') + 10
		default:
			return 0, errRange
		}
		if d >= int64(base) {
			return 0, errRange
		}
		if n > (1<<62-1)/int64(base) {
			return 0, errRange
		}
		n = n*int64(base) + d
	}
	return n, nil
}

func strconvParseFloat(text string) (float64, bool) {
	f, err := strconv.ParseFloat(text, 64)
	if err != nil {
		return 0, true
	}
	return f, false
}

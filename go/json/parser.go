// Package json provides JSON encoding and decoding.
package json

import (
	"fmt"
	"strconv"
	"strings"
	"unicode/utf16"

	serde "github.com/codinglombok/LombokSerde/go"
)

const defaultMaxDepth = 128

// Parse parses a JSON string into a Value.
func Parse(input string) (*serde.Value, error) {
	return ParseWithDepth(input, defaultMaxDepth)
}

// ParseWithDepth parses a JSON string with a custom depth limit.
func ParseWithDepth(input string, maxDepth int) (*serde.Value, error) {
	p := &jsonParser{input: input, maxDepth: maxDepth}
	val, err := p.parseValue(0)
	if err != nil {
		return nil, err
	}
	p.skipWs()
	if p.pos < len(p.input) {
		return nil, syntaxErr("trailing data")
	}
	return val, nil
}

type jsonParser struct {
	input    string
	pos      int
	maxDepth int
}

func (p *jsonParser) parseValue(depth int) (*serde.Value, error) {
	if depth > p.maxDepth {
		return nil, &serde.SerdeError{Code: serde.ErrDepthExceeded, Message: "max depth exceeded"}
	}
	p.skipWs()
	if p.pos >= len(p.input) {
		return nil, eofErr()
	}
	ch := p.input[p.pos]
	switch {
	case ch == '"':
		s, err := p.parseString()
		if err != nil {
			return nil, err
		}
		return serde.String(s), nil
	case ch == '{':
		return p.parseObject(depth)
	case ch == '[':
		return p.parseArray(depth)
	case ch == 't':
		if err := p.expectLiteral("true"); err != nil {
			return nil, err
		}
		return serde.Bool(true), nil
	case ch == 'f':
		if err := p.expectLiteral("false"); err != nil {
			return nil, err
		}
		return serde.Bool(false), nil
	case ch == 'n':
		if err := p.expectLiteral("null"); err != nil {
			return nil, err
		}
		return serde.Null(), nil
	case ch == '-' || (ch >= '0' && ch <= '9'):
		return p.parseNumber()
	default:
		return nil, syntaxErr(fmt.Sprintf("unexpected character '%c'", ch))
	}
}

func (p *jsonParser) parseObject(depth int) (*serde.Value, error) {
	p.pos++ // skip '{'
	m := make(map[string]*serde.Value)
	p.skipWs()
	if p.pos < len(p.input) && p.input[p.pos] == '}' {
		p.pos++
		return serde.Map(m), nil
	}
	for {
		p.skipWs()
		if p.pos >= len(p.input) || p.input[p.pos] != '"' {
			return nil, syntaxErr("expected string key")
		}
		key, err := p.parseString()
		if err != nil {
			return nil, err
		}
		if _, exists := m[key]; exists {
			return nil, &serde.SerdeError{Code: serde.ErrDuplicateKey, Message: "duplicate key: " + key}
		}
		p.skipWs()
		if p.pos >= len(p.input) || p.input[p.pos] != ':' {
			return nil, syntaxErr("expected ':'")
		}
		p.pos++
		val, err := p.parseValue(depth + 1)
		if err != nil {
			return nil, err
		}
		m[key] = val
		p.skipWs()
		if p.pos >= len(p.input) {
			return nil, eofErr()
		}
		if p.input[p.pos] == '}' {
			p.pos++
			return serde.Map(m), nil
		}
		if p.input[p.pos] != ',' {
			return nil, syntaxErr("expected ',' or '}'")
		}
		p.pos++
	}
}

func (p *jsonParser) parseArray(depth int) (*serde.Value, error) {
	p.pos++ // skip '['
	var arr []*serde.Value
	p.skipWs()
	if p.pos < len(p.input) && p.input[p.pos] == ']' {
		p.pos++
		return serde.Array(arr...), nil
	}
	for {
		val, err := p.parseValue(depth + 1)
		if err != nil {
			return nil, err
		}
		arr = append(arr, val)
		p.skipWs()
		if p.pos >= len(p.input) {
			return nil, eofErr()
		}
		if p.input[p.pos] == ']' {
			p.pos++
			return serde.Array(arr...), nil
		}
		if p.input[p.pos] != ',' {
			return nil, syntaxErr("expected ',' or ']'")
		}
		p.pos++
	}
}

func (p *jsonParser) parseString() (string, error) {
	p.pos++ // skip '"'
	var sb strings.Builder
	for {
		if p.pos >= len(p.input) {
			return "", eofErr()
		}
		ch := p.input[p.pos]
		if ch == '"' {
			p.pos++
			return sb.String(), nil
		}
		if ch == '\\' {
			p.pos++
			esc, err := p.parseEscape()
			if err != nil {
				return "", err
			}
			sb.WriteString(esc)
		} else {
			sb.WriteByte(ch)
			p.pos++
		}
	}
}

func (p *jsonParser) parseEscape() (string, error) {
	if p.pos >= len(p.input) {
		return "", eofErr()
	}
	ch := p.input[p.pos]
	p.pos++
	switch ch {
	case '"':
		return "\"", nil
	case '\\':
		return "\\", nil
	case '/':
		return "/", nil
	case 'b':
		return "\b", nil
	case 'f':
		return "\f", nil
	case 'n':
		return "\n", nil
	case 'r':
		return "\r", nil
	case 't':
		return "\t", nil
	case 'u':
		cp, err := p.parseHex4()
		if err != nil {
			return "", err
		}
		// Surrogate pair
		if cp >= 0xD800 && cp <= 0xDBFF {
			if p.pos+1 < len(p.input) && p.input[p.pos] == '\\' && p.input[p.pos+1] == 'u' {
				p.pos += 2
				lo, err := p.parseHex4()
				if err != nil {
					return "", err
				}
				if lo >= 0xDC00 && lo <= 0xDFFF {
					r := utf16.DecodeRune(rune(cp), rune(lo))
					return string(r), nil
				}
				return "", &serde.SerdeError{Code: serde.ErrInvalidUnicode, Message: "invalid surrogate pair"}
			}
			return "", &serde.SerdeError{Code: serde.ErrInvalidUnicode, Message: "lone high surrogate"}
		}
		if cp >= 0xDC00 && cp <= 0xDFFF {
			return "", &serde.SerdeError{Code: serde.ErrInvalidUnicode, Message: "lone low surrogate"}
		}
		return string(rune(cp)), nil
	default:
		return "", syntaxErr(fmt.Sprintf("invalid escape '\\%c'", ch))
	}
}

func (p *jsonParser) parseHex4() (int, error) {
	if p.pos+4 > len(p.input) {
		return 0, eofErr()
	}
	hex := p.input[p.pos : p.pos+4]
	p.pos += 4
	val, err := strconv.ParseInt(hex, 16, 32)
	if err != nil {
		return 0, &serde.SerdeError{Code: serde.ErrInvalidUnicode, Message: "invalid hex: " + hex}
	}
	return int(val), nil
}

func (p *jsonParser) parseNumber() (*serde.Value, error) {
	start := p.pos
	if p.input[p.pos] == '-' {
		p.pos++
	}
	if p.pos >= len(p.input) {
		return nil, eofErr()
	}
	if p.input[p.pos] == '0' {
		p.pos++
	} else if p.input[p.pos] >= '1' && p.input[p.pos] <= '9' {
		for p.pos < len(p.input) && p.input[p.pos] >= '0' && p.input[p.pos] <= '9' {
			p.pos++
		}
	} else {
		return nil, syntaxErr("invalid number")
	}

	isFloat := false
	if p.pos < len(p.input) && p.input[p.pos] == '.' {
		isFloat = true
		p.pos++
		if p.pos >= len(p.input) || p.input[p.pos] < '0' || p.input[p.pos] > '9' {
			return nil, syntaxErr("expected digit after '.'")
		}
		for p.pos < len(p.input) && p.input[p.pos] >= '0' && p.input[p.pos] <= '9' {
			p.pos++
		}
	}
	if p.pos < len(p.input) && (p.input[p.pos] == 'e' || p.input[p.pos] == 'E') {
		isFloat = true
		p.pos++
		if p.pos < len(p.input) && (p.input[p.pos] == '+' || p.input[p.pos] == '-') {
			p.pos++
		}
		if p.pos >= len(p.input) || p.input[p.pos] < '0' || p.input[p.pos] > '9' {
			return nil, syntaxErr("expected digit in exponent")
		}
		for p.pos < len(p.input) && p.input[p.pos] >= '0' && p.input[p.pos] <= '9' {
			p.pos++
		}
	}

	raw := p.input[start:p.pos]
	if isFloat {
		f, err := strconv.ParseFloat(raw, 64)
		if err != nil {
			return nil, syntaxErr("invalid float: " + raw)
		}
		return serde.Float(f), nil
	}
	n, err := strconv.ParseInt(raw, 10, 64)
	if err != nil {
		// Fallback to float
		f, err2 := strconv.ParseFloat(raw, 64)
		if err2 != nil {
			return nil, syntaxErr("invalid number: " + raw)
		}
		return serde.Float(f), nil
	}
	return serde.Integer(n), nil
}

func (p *jsonParser) expectLiteral(s string) error {
	if p.pos+len(s) > len(p.input) || p.input[p.pos:p.pos+len(s)] != s {
		return syntaxErr("expected '" + s + "'")
	}
	p.pos += len(s)
	return nil
}

func (p *jsonParser) skipWs() {
	for p.pos < len(p.input) {
		ch := p.input[p.pos]
		if ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n' {
			p.pos++
		} else {
			break
		}
	}
}

func syntaxErr(msg string) *serde.SerdeError {
	return &serde.SerdeError{Code: serde.ErrSyntaxError, Message: msg}
}

func eofErr() *serde.SerdeError {
	return &serde.SerdeError{Code: serde.ErrUnexpectedEof, Message: "unexpected end of input"}
}

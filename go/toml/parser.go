// Package toml provides TOML v1.0 parsing and serialization.
package toml

import (
	"fmt"
	"math"
	"regexp"
	"strconv"
	"strings"

	serde "github.com/codinglombok/LombokSerde/go"
)

// Parse parses a TOML string into a Value (map).
func Parse(input string) (*serde.Value, error) {
	p := &tomlParser{input: input}
	return p.parse()
}

type tomlParser struct {
	input string
	pos   int
}

func (p *tomlParser) parse() (*serde.Value, error) {
	root := make(map[string]*serde.Value)
	var currentPath []string

	for {
		p.skipWsNewlines()
		if p.pos >= len(p.input) {
			break
		}
		ch := p.input[p.pos]
		if ch == '#' {
			p.skipComment()
			continue
		}
		if ch == '[' {
			p.pos++
			isArray := p.pos < len(p.input) && p.input[p.pos] == '['
			if isArray {
				p.pos++
			}
			p.skipWs()
			keys, err := p.parseKey()
			if err != nil {
				return nil, err
			}
			p.skipWs()
			if isArray {
				if err := p.expect(']'); err != nil {
					return nil, err
				}
				if err := p.expect(']'); err != nil {
					return nil, err
				}
			} else {
				if err := p.expect(']'); err != nil {
					return nil, err
				}
			}
			p.skipWs()
			if p.pos < len(p.input) && p.input[p.pos] == '#' {
				p.skipComment()
			}
			if isArray {
				if err := ensureArrayOfTables(root, keys); err != nil {
					return nil, err
				}
			} else {
				if err := ensureTable(root, keys); err != nil {
					return nil, err
				}
			}
			currentPath = keys
			continue
		}
		// Key-value pair
		keys, err := p.parseKey()
		if err != nil {
			return nil, err
		}
		p.skipWs()
		if err := p.expect('='); err != nil {
			return nil, err
		}
		p.skipWs()
		val, err := p.parseValue()
		if err != nil {
			return nil, err
		}
		p.skipWs()
		if p.pos < len(p.input) && p.input[p.pos] == '#' {
			p.skipComment()
		}
		if err := insertValue(root, currentPath, keys, val); err != nil {
			return nil, err
		}
	}
	return mapToValue(root), nil
}

func (p *tomlParser) parseKey() ([]string, error) {
	key, err := p.parseSimpleKey()
	if err != nil {
		return nil, err
	}
	keys := []string{key}
	for {
		p.skipWs()
		if p.pos < len(p.input) && p.input[p.pos] == '.' {
			p.pos++
			p.skipWs()
			k, err := p.parseSimpleKey()
			if err != nil {
				return nil, err
			}
			keys = append(keys, k)
		} else {
			break
		}
	}
	return keys, nil
}

func (p *tomlParser) parseSimpleKey() (string, error) {
	if p.pos >= len(p.input) {
		return "", p.eofErr()
	}
	ch := p.input[p.pos]
	if ch == '"' {
		return p.parseBasicString()
	}
	if ch == '\'' {
		return p.parseLiteralString()
	}
	return p.parseBareKey()
}

func (p *tomlParser) parseBareKey() (string, error) {
	start := p.pos
	for p.pos < len(p.input) && isBareKeyChar(p.input[p.pos]) {
		p.pos++
	}
	if p.pos == start {
		return "", p.syntaxErr("empty bare key")
	}
	return p.input[start:p.pos], nil
}

func isBareKeyChar(ch byte) bool {
	return (ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '_' || ch == '-'
}

func (p *tomlParser) parseBasicString() (string, error) {
	if err := p.expect('"'); err != nil {
		return "", err
	}
	if p.pos+1 < len(p.input) && p.input[p.pos] == '"' && p.input[p.pos+1] == '"' {
		p.pos += 2
		return p.parseMultilineBasicString()
	}
	var sb strings.Builder
	for {
		if p.pos >= len(p.input) {
			return "", p.eofErr()
		}
		ch := p.input[p.pos]
		p.pos++
		if ch == '"' {
			return sb.String(), nil
		}
		if ch == '\\' {
			esc, err := p.parseEscape()
			if err != nil {
				return "", err
			}
			sb.WriteString(esc)
		} else {
			sb.WriteByte(ch)
		}
	}
}

func (p *tomlParser) parseMultilineBasicString() (string, error) {
	if p.pos < len(p.input) && p.input[p.pos] == '\n' {
		p.pos++
	} else if p.pos < len(p.input) && p.input[p.pos] == '\r' {
		p.pos++
		if p.pos < len(p.input) && p.input[p.pos] == '\n' {
			p.pos++
		}
	}
	var sb strings.Builder
	for {
		if p.pos >= len(p.input) {
			return "", p.eofErr()
		}
		ch := p.input[p.pos]
		p.pos++
		if ch == '"' && p.pos+1 < len(p.input) && p.input[p.pos] == '"' && p.input[p.pos+1] == '"' {
			p.pos += 2
			return sb.String(), nil
		}
		if ch == '\\' {
			if p.pos < len(p.input) && (p.input[p.pos] == '\n' || p.input[p.pos] == '\r') {
				p.skipWsNewlines()
				continue
			}
			esc, err := p.parseEscape()
			if err != nil {
				return "", err
			}
			sb.WriteString(esc)
			continue
		}
		sb.WriteByte(ch)
	}
}

func (p *tomlParser) parseLiteralString() (string, error) {
	if err := p.expect('\''); err != nil {
		return "", err
	}
	if p.pos+1 < len(p.input) && p.input[p.pos] == '\'' && p.input[p.pos+1] == '\'' {
		p.pos += 2
		return p.parseMultilineLiteralString()
	}
	start := p.pos
	for p.pos < len(p.input) && p.input[p.pos] != '\'' {
		p.pos++
	}
	s := p.input[start:p.pos]
	if err := p.expect('\''); err != nil {
		return "", err
	}
	return s, nil
}

func (p *tomlParser) parseMultilineLiteralString() (string, error) {
	if p.pos < len(p.input) && p.input[p.pos] == '\n' {
		p.pos++
	} else if p.pos < len(p.input) && p.input[p.pos] == '\r' {
		p.pos++
		if p.pos < len(p.input) && p.input[p.pos] == '\n' {
			p.pos++
		}
	}
	var sb strings.Builder
	for {
		if p.pos >= len(p.input) {
			return "", p.eofErr()
		}
		ch := p.input[p.pos]
		p.pos++
		if ch == '\'' && p.pos+1 < len(p.input) && p.input[p.pos] == '\'' && p.input[p.pos+1] == '\'' {
			p.pos += 2
			return sb.String(), nil
		}
		sb.WriteByte(ch)
	}
}

func (p *tomlParser) parseEscape() (string, error) {
	if p.pos >= len(p.input) {
		return "", p.eofErr()
	}
	ch := p.input[p.pos]
	p.pos++
	switch ch {
	case 'b':
		return "\b", nil
	case 't':
		return "\t", nil
	case 'n':
		return "\n", nil
	case 'f':
		return "\f", nil
	case 'r':
		return "\r", nil
	case '"':
		return "\"", nil
	case '\\':
		return "\\", nil
	case 'u':
		return p.parseUnicodeEscape(4)
	case 'U':
		return p.parseUnicodeEscape(8)
	default:
		return "", p.syntaxErr("invalid escape")
	}
}

func (p *tomlParser) parseUnicodeEscape(digits int) (string, error) {
	if p.pos+digits > len(p.input) {
		return "", p.eofErr()
	}
	hex := p.input[p.pos : p.pos+digits]
	p.pos += digits
	cp, err := strconv.ParseInt(hex, 16, 32)
	if err != nil {
		return "", p.syntaxErr("invalid unicode escape")
	}
	return string(rune(cp)), nil
}

func (p *tomlParser) parseValue() (*serde.Value, error) {
	if p.pos >= len(p.input) {
		return nil, p.eofErr()
	}
	ch := p.input[p.pos]
	switch {
	case ch == '"':
		s, err := p.parseBasicString()
		if err != nil {
			return nil, err
		}
		return serde.String(s), nil
	case ch == '\'':
		s, err := p.parseLiteralString()
		if err != nil {
			return nil, err
		}
		return serde.String(s), nil
	case ch == 't':
		if p.pos+4 <= len(p.input) && p.input[p.pos:p.pos+4] == "true" {
			p.pos += 4
			return serde.Bool(true), nil
		}
		return nil, p.syntaxErr("expected 'true'")
	case ch == 'f':
		if p.pos+5 <= len(p.input) && p.input[p.pos:p.pos+5] == "false" {
			p.pos += 5
			return serde.Bool(false), nil
		}
		return nil, p.syntaxErr("expected 'false'")
	case ch == '[':
		return p.parseArray()
	case ch == '{':
		return p.parseInlineTable()
	case ch == 'i':
		if p.pos+3 <= len(p.input) && p.input[p.pos:p.pos+3] == "inf" {
			p.pos += 3
			return serde.Float(posInf()), nil
		}
		return nil, p.syntaxErr("expected value")
	case ch == 'n' && p.pos+3 <= len(p.input) && p.input[p.pos:p.pos+3] == "nan":
		p.pos += 3
		return serde.Float(nan()), nil
	case ch == '-' || ch == '+' || (ch >= '0' && ch <= '9'):
		return p.parseNumberOrDate()
	default:
		return nil, p.syntaxErr("expected value")
	}
}

func (p *tomlParser) parseArray() (*serde.Value, error) {
	if err := p.expect('['); err != nil {
		return nil, err
	}
	var arr []*serde.Value
	for {
		p.skipWsNewlinesComments()
		if p.pos < len(p.input) && p.input[p.pos] == ']' {
			p.pos++
			return serde.Array(arr...), nil
		}
		val, err := p.parseValue()
		if err != nil {
			return nil, err
		}
		arr = append(arr, val)
		p.skipWsNewlinesComments()
		if p.pos < len(p.input) && p.input[p.pos] == ',' {
			p.pos++
		}
	}
}

func (p *tomlParser) parseInlineTable() (*serde.Value, error) {
	if err := p.expect('{'); err != nil {
		return nil, err
	}
	m := make(map[string]*serde.Value)
	p.skipWs()
	if p.pos < len(p.input) && p.input[p.pos] == '}' {
		p.pos++
		return serde.Map(m), nil
	}
	for {
		p.skipWs()
		keys, err := p.parseKey()
		if err != nil {
			return nil, err
		}
		p.skipWs()
		if err := p.expect('='); err != nil {
			return nil, err
		}
		p.skipWs()
		val, err := p.parseValue()
		if err != nil {
			return nil, err
		}
		if err := insertIntoMap(m, keys, val); err != nil {
			return nil, err
		}
		p.skipWs()
		if p.pos < len(p.input) && p.input[p.pos] == ',' {
			p.pos++
		} else {
			break
		}
	}
	p.skipWs()
	if err := p.expect('}'); err != nil {
		return nil, err
	}
	return serde.Map(m), nil
}

var numDateRe = regexp.MustCompile(`^[0-9a-fA-F_.:\+\-TtZxXoObB]+`)

func (p *tomlParser) parseNumberOrDate() (*serde.Value, error) {
	start := p.pos
	sign := p.input[p.pos]
	if sign == '+' || sign == '-' {
		p.pos++
	}

	// Special floats
	if p.pos+3 <= len(p.input) && p.input[p.pos:p.pos+3] == "inf" {
		p.pos += 3
		if sign == '-' {
			return serde.Float(negInf()), nil
		}
		return serde.Float(posInf()), nil
	}
	if p.pos+3 <= len(p.input) && p.input[p.pos:p.pos+3] == "nan" {
		p.pos += 3
		return serde.Float(nan()), nil
	}

	for p.pos < len(p.input) {
		c := p.input[p.pos]
		if (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F') ||
			c == '_' || c == '.' || c == ':' || c == '+' || c == '-' ||
			c == 'T' || c == 't' || c == 'Z' || c == 'x' || c == 'X' ||
			c == 'o' || c == 'O' || c == 'b' || c == 'B' {
			p.pos++
		} else {
			break
		}
	}

	raw := p.input[start:p.pos]
	clean := strings.ReplaceAll(raw, "_", "")

	if looksLikeDatetime(clean) {
		return parseDatetime(clean), nil
	}

	noSign := clean
	mult := int64(1)
	if sign == '+' || sign == '-' {
		noSign = clean[1:]
		if sign == '-' {
			mult = -1
		}
	}

	if strings.HasPrefix(noSign, "0x") || strings.HasPrefix(noSign, "0X") {
		n, err := strconv.ParseInt(noSign, 0, 64)
		if err != nil {
			return nil, p.syntaxErr("invalid hex number")
		}
		return serde.Integer(n * mult), nil
	}
	if strings.HasPrefix(noSign, "0o") || strings.HasPrefix(noSign, "0O") {
		n, err := strconv.ParseInt(noSign[2:], 8, 64)
		if err != nil {
			return nil, p.syntaxErr("invalid octal number")
		}
		return serde.Integer(n * mult), nil
	}
	if strings.HasPrefix(noSign, "0b") || strings.HasPrefix(noSign, "0B") {
		n, err := strconv.ParseInt(noSign[2:], 2, 64)
		if err != nil {
			return nil, p.syntaxErr("invalid binary number")
		}
		return serde.Integer(n * mult), nil
	}

	if strings.ContainsAny(clean, ".eE") {
		f, err := strconv.ParseFloat(clean, 64)
		if err != nil {
			return nil, p.syntaxErr("invalid float")
		}
		return serde.Float(f), nil
	}
	n, err := strconv.ParseInt(clean, 10, 64)
	if err != nil {
		return nil, p.syntaxErr("invalid integer")
	}
	return serde.Integer(n), nil
}

// --- Table navigation ---

func ensureTable(root map[string]*serde.Value, keys []string) error {
	current := root
	for _, key := range keys {
		if _, exists := current[key]; !exists {
			current[key] = serde.Map(make(map[string]*serde.Value))
		}
		val := current[key]
		if val.Kind == serde.KindArray && len(val.Array) > 0 {
			last := val.Array[len(val.Array)-1]
			if last.Kind == serde.KindMap {
				current = last.Map
			} else {
				return &serde.SerdeError{Code: serde.ErrDuplicateKey, Message: "duplicate key"}
			}
		} else if val.Kind == serde.KindMap {
			current = val.Map
		} else {
			return &serde.SerdeError{Code: serde.ErrDuplicateKey, Message: "duplicate key"}
		}
	}
	return nil
}

func ensureArrayOfTables(root map[string]*serde.Value, keys []string) error {
	current := root
	for i := 0; i < len(keys)-1; i++ {
		key := keys[i]
		if _, exists := current[key]; !exists {
			current[key] = serde.Map(make(map[string]*serde.Value))
		}
		val := current[key]
		if val.Kind == serde.KindArray && len(val.Array) > 0 {
			last := val.Array[len(val.Array)-1]
			if last.Kind == serde.KindMap {
				current = last.Map
			} else {
				return &serde.SerdeError{Code: serde.ErrDuplicateKey, Message: "duplicate key"}
			}
		} else if val.Kind == serde.KindMap {
			current = val.Map
		} else {
			return &serde.SerdeError{Code: serde.ErrDuplicateKey, Message: "duplicate key"}
		}
	}
	lastKey := keys[len(keys)-1]
	if _, exists := current[lastKey]; !exists {
		current[lastKey] = serde.Array(serde.Map(make(map[string]*serde.Value)))
	} else {
		val := current[lastKey]
		if val.Kind == serde.KindArray {
			val.Array = append(val.Array, serde.Map(make(map[string]*serde.Value)))
		} else {
			return &serde.SerdeError{Code: serde.ErrDuplicateKey, Message: "duplicate key"}
		}
	}
	return nil
}

func insertValue(root map[string]*serde.Value, tablePath []string, keys []string, value *serde.Value) error {
	current := root
	for _, key := range tablePath {
		val := current[key]
		if val.Kind == serde.KindArray && len(val.Array) > 0 {
			current = val.Array[len(val.Array)-1].Map
		} else {
			current = val.Map
		}
	}
	return insertIntoMap(current, keys, value)
}

func insertIntoMap(m map[string]*serde.Value, keys []string, value *serde.Value) error {
	if len(keys) == 1 {
		if _, exists := m[keys[0]]; exists {
			return &serde.SerdeError{Code: serde.ErrDuplicateKey, Message: "duplicate key"}
		}
		m[keys[0]] = value
		return nil
	}
	if _, exists := m[keys[0]]; !exists {
		m[keys[0]] = serde.Map(make(map[string]*serde.Value))
	}
	sub := m[keys[0]]
	if sub.Kind == serde.KindMap {
		return insertIntoMap(sub.Map, keys[1:], value)
	}
	return &serde.SerdeError{Code: serde.ErrDuplicateKey, Message: "duplicate key"}
}

func mapToValue(m map[string]*serde.Value) *serde.Value {
	return serde.Map(m)
}

// --- Helpers ---

func (p *tomlParser) expect(ch byte) error {
	if p.pos >= len(p.input) || p.input[p.pos] != ch {
		return p.syntaxErr(fmt.Sprintf("expected '%c'", ch))
	}
	p.pos++
	return nil
}

func (p *tomlParser) skipWs() {
	for p.pos < len(p.input) && (p.input[p.pos] == ' ' || p.input[p.pos] == '\t') {
		p.pos++
	}
}

func (p *tomlParser) skipWsNewlines() {
	for p.pos < len(p.input) {
		ch := p.input[p.pos]
		if ch == ' ' || ch == '\t' || ch == '\r' || ch == '\n' {
			p.pos++
		} else {
			break
		}
	}
}

func (p *tomlParser) skipWsNewlinesComments() {
	for {
		p.skipWsNewlines()
		if p.pos < len(p.input) && p.input[p.pos] == '#' {
			p.skipComment()
		} else {
			break
		}
	}
}

func (p *tomlParser) skipComment() {
	for p.pos < len(p.input) && p.input[p.pos] != '\n' {
		p.pos++
	}
	if p.pos < len(p.input) {
		p.pos++
	}
}

func (p *tomlParser) syntaxErr(msg string) *serde.SerdeError {
	return &serde.SerdeError{Code: serde.ErrSyntaxError, Message: msg}
}

func (p *tomlParser) eofErr() *serde.SerdeError {
	return &serde.SerdeError{Code: serde.ErrUnexpectedEof, Message: "unexpected end of input"}
}

func looksLikeDatetime(s string) bool {
	if len(s) >= 10 && s[4] == '-' && s[7] == '-' && s[0] >= '0' && s[0] <= '9' {
		return true
	}
	if len(s) >= 5 && s[2] == ':' && s[0] >= '0' && s[0] <= '9' {
		return true
	}
	return false
}

func parseDatetime(s string) *serde.Value {
	if (strings.Contains(s, "T") || strings.Contains(s, "t")) && len(s) > 10 {
		rest := s[10:]
		if strings.Contains(rest, "Z") || strings.Contains(rest, "+") || strings.LastIndex(rest, "-") > 0 {
			return serde.DateTimeVal(serde.DTOffset, s)
		}
		return serde.DateTimeVal(serde.DTLocalDateTime, s)
	}
	if len(s) == 10 && s[4] == '-' {
		return serde.DateTimeVal(serde.DTLocalDate, s)
	}
	if strings.Contains(s, ":") && !strings.Contains(s, "-") {
		return serde.DateTimeVal(serde.DTLocalTime, s)
	}
	return serde.DateTimeVal(serde.DTLocalDateTime, s)
}

func posInf() float64 { return math.Inf(1) }
func negInf() float64 { return math.Inf(-1) }
func nan() float64    { return math.NaN() }

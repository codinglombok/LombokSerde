package lombokserde

import (
	"math"
	"strings"
	"unicode/utf8"
)

// canonNaN is the canonical quiet NaN bit pattern (SPEC).
var canonNaN = math.Float64frombits(0x7FF8000000000000)

// TOML v1.0 codec — canonical, byte-precise (see SPEC).

// TomlOptions holds the TOML options.
type TomlOptions struct {
	DepthLimit int
}

// TomlDecode decodes a TOML document into a table value.
func TomlDecode(data []byte, opts *TomlOptions) (Value, error) {
	limit := DefaultDepthLimit
	if opts != nil && opts.DepthLimit != 0 {
		limit = opts.DepthLimit
	}
	if bad := utf8FirstBadOffset(data); bad != -1 {
		return Value{}, syntaxErr(ErrTOMLUTF8, bad, "invalid UTF-8")
	}
	p := &tomlParser{b: data, limit: limit,
		root: map[string]*tomlNode{encodePath(nil): {state: "explicit", pairs: map[string]Value{}}},
	}
	return p.parse()
}

// TomlEncode encodes a table value as canonical TOML. The root must be a
// table: scalars first (sorted), then [sub-tables] (sorted), then
// [[array-of-tables]] (sorted); all arrays are single-line inline arrays.
func TomlEncode(v Value, opts *TomlOptions) ([]byte, error) {
	limit := DefaultDepthLimit
	if opts != nil && opts.DepthLimit != 0 {
		limit = opts.DepthLimit
	}
	if v.Kind != KindTable {
		return nil, NewError(ErrTOMLRoot, "TOML documents encode from a table root", nil)
	}
	var out strings.Builder
	if err := tomlEmitTable(v, nil, &out, 1, limit); err != nil {
		return nil, err
	}
	return []byte(out.String()), nil
}

type tomlNode struct {
	state string // implicit | explicit | dotted | aot
	pairs map[string]Value
	elems []*tomlNode
}

func encodePath(p []string) string {
	// JSON encoding is injective: [] (root) and [""] (empty key) differ.
	return pathJSON(p)
}

type tomlParser struct {
	b     []byte
	i     int
	limit int
	root  map[string]*tomlNode
	cur   []string
}

func isPseudo(seg string) bool {
	return len(seg) > 0 && seg[0] == '#'
}

func (p *tomlParser) fail(detail string) error {
	return syntaxErr(ErrTOMLSyntax, p.i, detail)
}

func (p *tomlParser) dup() error {
	return syntaxErr(ErrTOMLDuplicate, p.i, "duplicate key or table definition")
}

func (p *tomlParser) peek() (byte, bool) {
	if p.i < len(p.b) {
		return p.b[p.i], true
	}
	return 0, false
}

func (p *tomlParser) skipInlineWs() {
	for {
		c, ok := p.peek()
		if !ok || (c != 0x20 && c != 0x09) {
			break
		}
		p.i++
	}
}

func (p *tomlParser) skipComment() {
	if c, ok := p.peek(); ok && c == 0x23 {
		for {
			c, ok := p.peek()
			if !ok || c == 0x0A || c == 0x0D {
				break
			}
			p.i++
		}
	}
}

func (p *tomlParser) expectLineEnd() error {
	p.skipInlineWs()
	p.skipComment()
	c, ok := p.peek()
	if !ok {
		return nil
	}
	if c == 0x0A {
		p.i++
		return nil
	}
	if c == 0x0D {
		p.i++
		if c2, ok := p.peek(); ok && c2 == 0x0A {
			p.i++
		}
		return nil
	}
	return p.fail("expected end of line")
}

func (p *tomlParser) parse() (Value, error) {
	for {
		p.skipInlineWs()
		c, ok := p.peek()
		if !ok {
			break
		}
		switch {
		case c == 0x0A:
			p.i++
			continue
		case c == 0x0D:
			p.i++
			if c2, ok := p.peek(); ok && c2 == 0x0A {
				p.i++
			}
			continue
		case c == 0x23:
			p.skipComment()
			continue
		case c == 0x5B:
			if p.i+1 < len(p.b) && p.b[p.i+1] == 0x5B {
				if err := p.parseAotHeader(); err != nil {
					return Value{}, err
				}
			} else {
				if err := p.parseTableHeader(); err != nil {
					return Value{}, err
				}
			}
		default:
			if err := p.parseKeyval(); err != nil {
				return Value{}, err
			}
		}
		if err := p.expectLineEnd(); err != nil {
			return Value{}, err
		}
	}
	return p.toValue(nil, 1)
}

func (p *tomlParser) parseTableHeader() error {
	start := p.i
	p.i++ // [
	path, err := p.parseKeyPath()
	if err != nil {
		return err
	}
	p.skipInlineWs()
	if c, ok := p.peek(); !ok || c != 0x5D {
		return p.fail("expected ']'")
	}
	p.i++
	if len(path)+1 > p.limit {
		return syntaxErr(ErrTOMLDepth, start, "depth limit exceeded")
	}
	if err := p.defineTable(path); err != nil {
		return err
	}
	p.cur = path
	return nil
}

func (p *tomlParser) parseAotHeader() error {
	start := p.i
	p.i += 2 // [[
	path, err := p.parseKeyPath()
	if err != nil {
		return err
	}
	p.skipInlineWs()
	c, ok := p.peek()
	if !ok || c != 0x5D || p.i+1 >= len(p.b) || p.b[p.i+1] != 0x5D {
		return p.fail("expected ']]'")
	}
	p.i += 2
	if len(path)+1 > p.limit {
		return syntaxErr(ErrTOMLDepth, start, "depth limit exceeded")
	}
	if err := p.defineAot(path); err != nil {
		return err
	}
	p.cur = path
	return nil
}

func (p *tomlParser) resolve(path []string) []string {
	out := []string{}
	for _, seg := range path {
		if node, ok := p.root[encodePath(out)]; ok && node.state == "aot" {
			out = append(out, "#"+itoa(len(node.elems)-1))
		}
		out = append(out, seg)
	}
	return out
}

func (p *tomlParser) defineTable(path []string) error {
	concrete := p.resolve(path)
	for j := 1; j <= len(concrete); j++ {
		if isPseudo(concrete[j-1]) {
			continue
		}
		sp := encodePath(concrete[:j])
		node, ok := p.root[sp]
		if !ok {
			p.root[sp] = &tomlNode{state: "implicit", pairs: map[string]Value{}}
		} else if node.state == "dotted" {
			return syntaxErr(ErrTOMLDuplicate, p.i, "dotted-key table redefined by header")
		}
	}
	ck := encodePath(concrete)
	node, ok := p.root[ck]
	if !ok {
		p.root[ck] = &tomlNode{state: "explicit", pairs: map[string]Value{}}
		return nil
	}
	if node.state == "implicit" {
		node.state = "explicit"
		return nil
	}
	return p.dup()
}

func (p *tomlParser) defineAot(path []string) error {
	concrete := p.resolve(path)
	for j := 1; j <= len(concrete); j++ {
		if isPseudo(concrete[j-1]) {
			continue
		}
		sp := encodePath(concrete[:j])
		node, ok := p.root[sp]
		if !ok {
			p.root[sp] = &tomlNode{state: "implicit", pairs: map[string]Value{}}
		} else if node.state == "dotted" {
			return syntaxErr(ErrTOMLDuplicate, p.i, "dotted-key table redefined by header")
		}
	}
	ck := encodePath(concrete)
	node, ok := p.root[ck]
	if !ok {
		return p.dup()
	}
	switch node.state {
	case "aot":
		node.elems = append(node.elems, &tomlNode{state: "explicit", pairs: map[string]Value{}})
	case "implicit":
		node.state = "aot"
		node.elems = []*tomlNode{{state: "explicit", pairs: map[string]Value{}}}
	default:
		return p.dup()
	}
	return nil
}

func (p *tomlParser) parseKeyPath() ([]string, error) {
	keys := []string{}
	p.skipInlineWs()
	for {
		k, err := p.parseSingleKey()
		if err != nil {
			return nil, err
		}
		keys = append(keys, k)
		p.skipInlineWs()
		if c, ok := p.peek(); ok && c == 0x2E {
			p.i++
			p.skipInlineWs()
			continue
		}
		break
	}
	return keys, nil
}

func (p *tomlParser) parseSingleKey() (string, error) {
	c, ok := p.peek()
	if !ok {
		return "", p.fail("expected key")
	}
	if c == 0x22 {
		k, err := p.parseBasicString()
		if err != nil {
			return "", err
		}
		if err := checkReservedKey(k, p.i); err != nil {
			return "", err
		}
		return k, nil
	}
	if c == 0x27 {
		k, err := p.parseLiteralString()
		if err != nil {
			return "", err
		}
		if err := checkReservedKey(k, p.i); err != nil {
			return "", err
		}
		return k, nil
	}
	s := p.i
	for {
		c, ok := p.peek()
		if !ok || !isBareKeyByte(c) {
			break
		}
		p.i++
	}
	if p.i == s {
		return "", p.fail("invalid key")
	}
	return string(p.b[s:p.i]), nil
}

func checkReservedKey(key string, at int) error {
	if len(key) > 0 && key[0] == '#' {
		return syntaxErr(ErrTOMLSyntax, at, "keys starting with '#' are reserved")
	}
	return nil
}

func (p *tomlParser) parseKeyval() error {
	keys, err := p.parseKeyPath()
	if err != nil {
		return err
	}
	p.skipInlineWs()
	if c, ok := p.peek(); !ok || c != 0x3D {
		return p.fail("expected '='")
	}
	p.i++
	p.skipInlineWs()
	v, err := p.parseValue(len(p.cur) + len(keys) + 1)
	if err != nil {
		return err
	}
	base := p.resolve(p.cur)
	inter := keys[:len(keys)-1]
	if len(inter) > 0 {
		if bn, ok := p.root[encodePath(base)]; ok && bn.state == "aot" {
			return syntaxErr(ErrTOMLSyntax, p.i, "dotted keys cannot extend array-of-tables elements")
		}
	}
	for j := 1; j <= len(inter); j++ {
		sp := encodePath(append(append([]string{}, base[:0:0]...), base...))
		_ = sp
		break
	}
	// walk intermediates
	cur := append([]string{}, base...)
	for j := 0; j < len(inter); j++ {
		cur = append(cur, inter[j])
		sp := encodePath(cur)
		node, ok := p.root[sp]
		if !ok {
			p.root[sp] = &tomlNode{state: "dotted", pairs: map[string]Value{}}
		} else if node.state == "explicit" {
			return syntaxErr(ErrTOMLDuplicate, p.i, "dotted key extends a header-defined table")
		} else if node.state == "aot" {
			return syntaxErr(ErrTOMLSyntax, p.i, "dotted keys cannot extend array-of-tables elements")
		}
	}
	parentPath := append(append([]string{}, base...), inter...)
	last := keys[len(keys)-1]
	leaf := encodePath(append(append([]string{}, parentPath...), last))
	if _, ok := p.root[leaf]; ok {
		return p.dup()
	}
	pk := encodePath(parentPath)
	node, ok := p.root[pk]
	if !ok {
		node = &tomlNode{state: "dotted", pairs: map[string]Value{}}
		p.root[pk] = node
	}
	if node.state == "aot" {
		// keyvals directly under [[a]] write into the most recent element
		elem := node.elems[len(node.elems)-1]
		if _, exists := elem.pairs[last]; exists {
			return p.dup()
		}
		elem.pairs[last] = v
		return nil
	}
	if _, exists := node.pairs[last]; exists {
		return p.dup()
	}
	node.pairs[last] = v
	return nil
}

func (p *tomlParser) parseValue(depth int) (Value, error) {
	if depth > p.limit {
		return Value{}, syntaxErr(ErrTOMLDepth, p.i, "depth limit exceeded")
	}
	c, ok := p.peek()
	if !ok {
		return Value{}, p.fail("expected value")
	}
	switch {
	case c == 0x22:
		if p.startsWithStr(`"""`) {
			s, err := p.parseMlBasic()
			if err != nil {
				return Value{}, err
			}
			return NewStr(s), nil
		}
		s, err := p.parseBasicString()
		if err != nil {
			return Value{}, err
		}
		return NewStr(s), nil
	case c == 0x27:
		if p.startsWithStr("'''") {
			s, err := p.parseMlLiteral()
			if err != nil {
				return Value{}, err
			}
			return NewStr(s), nil
		}
		s, err := p.parseLiteralString()
		if err != nil {
			return Value{}, err
		}
		return NewStr(s), nil
	case c == 0x5B:
		return p.parseArray(depth)
	case c == 0x7B:
		return p.parseInlineTable(depth)
	case p.startsWithStr("true"):
		p.i += 4
		return NewBool(true), nil
	case p.startsWithStr("false"):
		p.i += 5
		return NewBool(false), nil
	}
	return p.parseNumberOrDatetime()
}

func (p *tomlParser) startsWithStr(prefix string) bool {
	if p.i+len(prefix) > len(p.b) {
		return false
	}
	return string(p.b[p.i:p.i+len(prefix)]) == prefix
}

func (p *tomlParser) parseArray(depth int) (Value, error) {
	p.i++ // [
	items := []Value{}
	for {
		p.skipArrayWs()
		c, ok := p.peek()
		if !ok {
			return Value{}, p.fail("unterminated array")
		}
		if c == 0x5D {
			p.i++
			return NewArray(items), nil
		}
		v, err := p.parseValue(depth + 1)
		if err != nil {
			return Value{}, err
		}
		items = append(items, v)
		p.skipArrayWs()
		c, ok = p.peek()
		if ok && c == 0x2C {
			p.i++
			continue
		}
		if ok && c == 0x5D {
			p.i++
			return NewArray(items), nil
		}
		return Value{}, p.fail("expected ',' or ']'")
	}
}

func (p *tomlParser) skipArrayWs() {
	for {
		c, ok := p.peek()
		if !ok {
			break
		}
		if c == 0x20 || c == 0x09 || c == 0x0A || c == 0x0D {
			p.i++
			continue
		}
		if c == 0x23 {
			for {
				c2, ok := p.peek()
				if !ok || c2 == 0x0A || c2 == 0x0D {
					break
				}
				p.i++
			}
			continue
		}
		break
	}
}

func (p *tomlParser) parseInlineTable(depth int) (Value, error) {
	p.i++ // {
	pairs := []TableEntry{}
	p.skipInlineWs()
	if c, ok := p.peek(); ok && c == 0x7D {
		p.i++
		return TableUnchecked(pairs), nil
	}
	for {
		p.skipInlineWs()
		keys, err := p.parseKeyPath()
		if err != nil {
			return Value{}, err
		}
		p.skipInlineWs()
		if c, ok := p.peek(); !ok || c != 0x3D {
			return Value{}, p.fail("expected '='")
		}
		p.i++
		p.skipInlineWs()
		v, err := p.parseValue(depth + 1)
		if err != nil {
			return Value{}, err
		}
		if len(keys) > 1 {
			v = nestDotted(keys[1:], v)
		}
		pairs = append(pairs, TableEntry{Key: keys[0], Value: v})
		p.skipInlineWs()
		c, ok := p.peek()
		if ok && c == 0x2C {
			p.i++
			continue
		}
		if ok && c == 0x7D {
			p.i++
			tab, terr := NewTable(pairs)
			if terr != nil {
				return Value{}, syntaxErr(ErrTOMLSyntax, p.i-1, "duplicate key in inline table")
			}
			return tab, nil
		}
		return Value{}, p.fail("expected ',' or '}' in inline table")
	}
}

func nestDotted(keys []string, v Value) Value {
	inner := v
	for j := len(keys) - 1; j >= 0; j-- {
		inner = TableUnchecked([]TableEntry{{Key: keys[j], Value: inner}})
	}
	return inner
}

func (p *tomlParser) parseBasicString() (string, error) {
	p.i++ // "
	var out []rune
	for {
		c, ok := p.peek()
		if !ok {
			return "", p.fail("unterminated string")
		}
		if c == 0x22 {
			p.i++
			return string(out), nil
		}
		if c == 0x0A || c == 0x0D {
			return "", p.fail("newline in basic string")
		}
		if c == 0x5C {
			p.i++
			if err := p.parseEscapeInto(&out); err != nil {
				return "", err
			}
			continue
		}
		if c < 0x20 && c != 0x09 {
			return "", p.fail("raw control character in string")
		}
		r, size := utf8.DecodeRune(p.b[p.i:])
		out = append(out, r)
		p.i += size
	}
}

func (p *tomlParser) parseEscapeInto(out *[]rune) error {
	e, ok := p.peek()
	if !ok {
		return p.fail("unterminated escape")
	}
	switch e {
	case 'b':
		*out = append(*out, '\b')
		p.i++
	case 't':
		*out = append(*out, '\t')
		p.i++
	case 'n':
		*out = append(*out, '\n')
		p.i++
	case 'f':
		*out = append(*out, '\f')
		p.i++
	case 'r':
		*out = append(*out, '\r')
		p.i++
	case '"':
		*out = append(*out, '"')
		p.i++
	case '\\':
		*out = append(*out, '\\')
		p.i++
	case 'u', 'U':
		width := 4
		if e == 'U' {
			width = 8
		}
		p.i++
		if p.i+width > len(p.b) {
			return p.fail("truncated unicode escape")
		}
		h := string(p.b[p.i : p.i+width])
		cp := 0
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
				return p.fail("invalid unicode escape")
			}
			cp = cp*16 + d
		}
		if cp > 0x10FFFF {
			return p.fail("invalid scalar value")
		}
		*out = append(*out, rune(cp))
		p.i += width
	case 0x0A, 0x0D, 0x20, 0x09:
		// possible line-ending backslash (multiline strings only)
		j := p.i
		sawNl := false
		for j < len(p.b) {
			c := p.b[j]
			if c == 0x20 || c == 0x09 || c == 0x0D || c == 0x0A {
				if c == 0x0A || c == 0x0D {
					sawNl = true
				}
				j++
				continue
			}
			break
		}
		if sawNl {
			p.i = j
			return nil
		}
		return p.fail("invalid escape")
	default:
		return p.fail("invalid escape")
	}
	return nil
}

func (p *tomlParser) parseLiteralString() (string, error) {
	p.i++ // '
	s := p.i
	for {
		c, ok := p.peek()
		if !ok {
			return "", p.fail("unterminated string")
		}
		if c == 0x27 {
			r := string(p.b[s:p.i])
			p.i++
			return r, nil
		}
		if (c < 0x20 && c != 0x09) || c == 0x7F {
			return "", p.fail("raw control character in literal string")
		}
		p.i++
	}
}

func (p *tomlParser) parseMlBasic() (string, error) {
	p.i += 3
	if c, ok := p.peek(); ok && c == 0x0A {
		p.i++
	} else if p.startsWithStr("\r\n") {
		p.i += 2
	}
	var out []rune
	for {
		if p.i >= len(p.b) {
			return "", p.fail("unterminated multiline string")
		}
		if p.startsWithStr(`"""`) {
			p.i += 3
			extra := 0
			for {
				c, ok := p.peek()
				if !ok || c != 0x22 || extra >= 2 {
					break
				}
				out = append(out, '"')
				p.i++
				extra++
			}
			return string(out), nil
		}
		c := p.b[p.i]
		if c == 0x5C {
			p.i++
			if err := p.parseEscapeInto(&out); err != nil {
				return "", err
			}
			continue
		}
		if c < 0x20 && c != 0x09 && c != 0x0A && c != 0x0D {
			return "", p.fail("raw control character in multiline string")
		}
		r, size := utf8.DecodeRune(p.b[p.i:])
		out = append(out, r)
		p.i += size
	}
}

func (p *tomlParser) parseMlLiteral() (string, error) {
	p.i += 3
	if c, ok := p.peek(); ok && c == 0x0A {
		p.i++
	} else if p.startsWithStr("\r\n") {
		p.i += 2
	}
	s := p.i
	for {
		if p.i >= len(p.b) {
			return "", p.fail("unterminated multiline string")
		}
		if p.startsWithStr("'''") {
			r := string(p.b[s:p.i])
			p.i += 3
			return r, nil
		}
		c := p.b[p.i]
		if c < 0x20 && c != 0x09 && c != 0x0A && c != 0x0D {
			return "", p.fail("raw control character in multiline string")
		}
		p.i++
	}
}

func (p *tomlParser) parseNumberOrDatetime() (Value, error) {
	start := p.i
	kind, end, serr := p.scanDatetime()
	if serr != nil {
		return Value{}, serr
	}
	if kind != "" {
		raw := string(p.b[start:end])
		p.i = end
		return NewDatetime(DatetimeKind(kind), raw), nil
	}
	b := p.b
	sign := int64(1)
	signSeen := false
	if c := b[p.i]; c == 0x2B || c == 0x2D {
		if c == 0x2D {
			sign = -1
		}
		signSeen = true
		p.i++
	}
	if p.startsWithStr("inf") {
		p.i += 3
		if sign < 0 {
			return NewFloat(math.Inf(-1)), nil
		}
		return NewFloat(math.Inf(1)), nil
	}
	if p.startsWithStr("nan") {
		p.i += 3
		// SPEC: the canonical quiet NaN, not Go's runtime NaN payload
		return NewFloat(canonNaN), nil
	}
	digitsStart := p.i
	if err := p.readDigits(10); err != nil {
		return Value{}, err
	}
	base := 10
	if p.i-digitsStart == 1 && b[digitsStart] == '0' {
		if c, ok := p.peek(); ok {
			switch c {
			case 'x':
				base = 16
			case 'o':
				base = 8
			case 'b':
				base = 2
			}
		}
	}
	if base != 10 {
		if signSeen {
			return Value{}, p.fail("signs are not allowed on hex/oct/bin integers")
		}
		p.i++
		if err := p.readDigits(base); err != nil {
			return Value{}, err
		}
		text := stripUnderscores(string(b[digitsStart+2 : p.i]))
		n, err := parseInt64Base(text, base)
		if err != nil {
			return Value{}, syntaxErr(ErrTOMLSyntax, start, "integer out of 64-bit range")
		}
		return NewInt(sign * n), nil
	}
	isFloat := false
	if c, ok := p.peek(); ok && c == 0x2E {
		isFloat = true
		p.i++
		if err := p.readDigits(10); err != nil {
			return Value{}, err
		}
	}
	if c, ok := p.peek(); ok && (c == 0x65 || c == 0x45) {
		isFloat = true
		p.i++
		if c2, ok := p.peek(); ok && (c2 == 0x2B || c2 == 0x2D) {
			p.i++
		}
		if c2, ok := p.peek(); !ok || c2 < 0x30 || c2 > 0x39 {
			return Value{}, p.fail("expected digit in exponent")
		}
		if err := p.readDigits(10); err != nil {
			return Value{}, err
		}
	}
	text := stripUnderscores(string(b[digitsStart:p.i]))
	if !isFloat {
		if len(text) > 1 && text[0] == '0' {
			return Value{}, p.fail("leading zero in integer")
		}
		mag, err := parseUint64(text)
		if err != nil {
			return Value{}, syntaxErr(ErrTOMLSyntax, start, "integer out of 64-bit range")
		}
		if (sign > 0 && mag > 1<<63-1) || (sign < 0 && mag > 1<<63) {
			return Value{}, syntaxErr(ErrTOMLSyntax, start, "integer out of 64-bit range")
		}
		if sign < 0 {
			if mag == 1<<63 {
				return NewInt(math_MinInt64), nil
			}
			return NewInt(-int64(mag)), nil
		}
		return NewInt(int64(mag)), nil
	}
	// Rust semantics (the reference port): overflow rounds to ±Inf and
	// underflow rounds to ±0 — ParseFloat already returns those values, so
	// the range error is deliberately ignored to stay bit-identical.
	f, _ := strconvParseFloat(text)
	return NewFloat(f), nil
}

func stripUnderscores(s string) string {
	return strings.Replace(s, "_", "", -1)
}

func (p *tomlParser) readDigits(base int) error {
	count := 0
	for p.i < len(p.b) {
		c := p.b[p.i]
		if isDigitBase(c, base) {
			count++
			p.i++
			continue
		}
		if c == 0x5F {
			if count == 0 {
				return p.fail("leading underscore")
			}
			if p.i+1 >= len(p.b) || !isDigitBase(p.b[p.i+1], base) {
				return p.fail("trailing underscore")
			}
			p.i++
			continue
		}
		break
	}
	if count == 0 {
		return p.fail("expected digit")
	}
	return nil
}

func isDigitBase(c byte, base int) bool {
	switch base {
	case 10:
		return c >= '0' && c <= '9'
	case 16:
		return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F')
	case 8:
		return c >= '0' && c <= '7'
	default:
		return c == '0' || c == '1'
	}
}

type scanResult struct {
	kind  string
	end   int
	error error
}

func (p *tomlParser) scanDatetime() (string, int, error) {
	i := p.i
	n := len(p.b)
	j := i
	for j < n && ((p.b[j] >= '0' && p.b[j] <= '9') || p.b[j] == '-' || p.b[j] == ':') {
		j++
	}
	seg := string(p.b[i:j])
	hasDash := strings.ContainsRune(seg, '-')
	hasColon := strings.ContainsRune(seg, ':')
	if !hasDash && !hasColon {
		return "", i, nil
	}
	if hasDash && !hasColon {
		if j-i != 10 {
			return "", i, nil
		}
		if j < n && (p.b[j] == 'T' || p.b[j] == 't' || p.b[j] == 0x20) {
			m := j + 1
			k := m
			for k < n && ((p.b[k] >= '0' && p.b[k] <= '9') || p.b[k] == ':') {
				k++
			}
			tseg := string(p.b[m:k])
			if !strings.ContainsRune(tseg, ':') {
				return p.validateDatetime(i, j, "date")
			}
			end, hadZone := p.scanFracZone(k)
			if end == nil {
				return "", i, nil
			}
			kind := "localdt"
			if hadZone {
				kind = "offset"
			}
			return p.validateDatetime(i, *end, kind)
		}
		return p.validateDatetime(i, j, "date")
	}
	if hasColon && !hasDash {
		k := j
		if k < n && p.b[k] == 0x2E {
			k++
			if k < n && p.b[k] >= '0' && p.b[k] <= '9' {
				for k < n && p.b[k] >= '0' && p.b[k] <= '9' {
					k++
				}
			} else {
				return "", i, nil
			}
		}
		return p.validateDatetime(i, k, "time")
	}
	return "", i, nil
}

func (p *tomlParser) scanFracZone(k int) (*int, bool) {
	n := len(p.b)
	end := k
	if end < n && p.b[end] == 0x2E {
		end++
		if end < n && p.b[end] >= '0' && p.b[end] <= '9' {
			for end < n && p.b[end] >= '0' && p.b[end] <= '9' {
				end++
			}
		} else {
			return nil, false
		}
	}
	if end < n && (p.b[end] == 'Z' || p.b[end] == 'z') {
		e := end + 1
		return &e, true
	}
	if end+6 <= n && (p.b[end] == '+' || p.b[end] == '-') && p.b[end+3] == ':' {
		e := end + 6
		return &e, true
	}
	return &end, false
}

func (p *tomlParser) validateDatetime(s, end int, kind string) (string, int, error) {
	text := string(p.b[s:end])
	if datetimeOK(text, kind) {
		return kind, end, nil
	}
	// the token has datetime shape but is invalid: fail at its start
	return "", s, syntaxErr(ErrTOMLSyntax, s, "invalid datetime")
}

func datetimeOK(text, kind string) bool {
	b := []byte(text)
	seg := func(from, to int) (int, bool) {
		if from < 0 || to > len(b) {
			return 0, false
		}
		v := 0
		for j := from; j < to; j++ {
			if b[j] < '0' || b[j] > '9' {
				return 0, false
			}
			v = v*10 + int(b[j]-'0')
		}
		return v, true
	}
	switch kind {
	case "date":
		if len(b) != 10 || b[4] != '-' || b[7] != '-' {
			return false
		}
		mo, ok1 := seg(5, 7)
		d, ok2 := seg(8, 10)
		_, ok0 := seg(0, 4)
		return ok0 && ok1 && ok2 && mo >= 1 && mo <= 12 && d >= 1 && d <= 31
	case "time":
		if len(b) < 8 || b[2] != ':' || b[5] != ':' {
			return false
		}
		h, ok1 := seg(0, 2)
		mi, ok2 := seg(3, 5)
		se, ok3 := seg(6, 8)
		if !ok1 || !ok2 || !ok3 || h > 23 || mi > 59 || se > 60 {
			return false
		}
		if len(b) == 8 {
			return true
		}
		if len(b) <= 9 || b[8] != '.' {
			return false
		}
		for j := 9; j < len(b); j++ {
			if b[j] < '0' || b[j] > '9' {
				return false
			}
		}
		return true
	case "localdt", "offset":
		minLen := 19
		if kind == "offset" {
			minLen = 20
		}
		if len(b) < minLen {
			return false
		}
		if !(b[4] == '-' && b[7] == '-' && (b[10] == 'T' || b[10] == 't' || b[10] == 0x20) && b[13] == ':' && b[16] == ':') {
			return false
		}
		mo, ok1 := seg(5, 7)
		d, ok2 := seg(8, 10)
		h, ok3 := seg(11, 13)
		mi, ok4 := seg(14, 16)
		se, ok5 := seg(17, 19)
		if !ok1 || !ok2 || !ok3 || !ok4 || !ok5 {
			return false
		}
		if !(mo >= 1 && mo <= 12 && d >= 1 && d <= 31 && h <= 23 && mi <= 59 && se <= 60) {
			return false
		}
		i := 19
		if i < len(b) && b[i] == '.' {
			i++
			start := i
			for i < len(b) && b[i] >= '0' && b[i] <= '9' {
				i++
			}
			if i == start {
				return false
			}
		}
		if kind == "localdt" {
			return i == len(b)
		}
		if i == len(b) {
			return false
		}
		if b[i] == 'Z' || b[i] == 'z' {
			return i+1 == len(b)
		}
		if i+6 != len(b) || (b[i] != '+' && b[i] != '-') || b[i+3] != ':' {
			return false
		}
		_, okzh := seg(i+1, i+3)
		_, okzm := seg(i+4, i+6)
		if !okzh || !okzm {
			return false
		}
		zh, _ := seg(i+1, i+3)
		zm, _ := seg(i+4, i+6)
		return zh <= 23 && zm <= 59
	}
	return false
}

// --- tree -> Value -----------------------------------------------------------

func (p *tomlParser) toValue(path []string, depth int) (Value, error) {
	node, ok := p.root[encodePath(path)]
	if !ok {
		return Value{}, p.fail("missing table")
	}
	if node.state == "aot" {
		elems := []Value{}
		for idx, el := range node.elems {
			base := append(append([]string{}, path...), "#"+itoa(idx))
			v, err := p.collectFrom(el.pairs, base, depth)
			if err != nil {
				return Value{}, err
			}
			elems = append(elems, v)
		}
		return NewArray(elems), nil
	}
	return p.collect(path, depth)
}

func (p *tomlParser) collect(path []string, depth int) (Value, error) {
	node, ok := p.root[encodePath(path)]
	if !ok {
		return Value{}, p.fail("missing table")
	}
	return p.collectFrom(node.pairs, path, depth)
}

func (p *tomlParser) collectFrom(pairs map[string]Value, basePath []string, depth int) (Value, error) {
	out := []TableEntry{}
	for k, v := range pairs {
		out = append(out, TableEntry{Key: k, Value: v})
	}
	for key := range p.root {
		segs := decodePath(key)
		if len(segs) != len(basePath)+1 || !pathHasPrefix(segs, basePath) {
			continue
		}
		k := segs[len(segs)-1]
		if isPseudo(k) {
			continue
		}
		for _, existing := range out {
			if existing.Key == k {
				return Value{}, syntaxErr(ErrTOMLDuplicate, p.i, "table and value share a key")
			}
		}
		v, err := p.toValue(segs, depth+1)
		if err != nil {
			return Value{}, err
		}
		out = append(out, TableEntry{Key: k, Value: v})
	}
	return TableUnchecked(out), nil
}

func pathHasPrefix(segs, base []string) bool {
	for j := 0; j < len(base); j++ {
		if segs[j] != base[j] {
			return false
		}
	}
	return true
}

// --- serializer -----------------------------------------------------------

func tomlIsAot(v Value) bool {
	if v.Kind != KindArray || len(v.Array) == 0 {
		return false
	}
	for _, x := range v.Array {
		if x.Kind != KindTable {
			return false
		}
	}
	return true
}

func tomlEmitTable(tbl Value, path []string, out *strings.Builder, depth, limit int) error {
	if depth > limit {
		return NewError(ErrTOMLDepth, "depth limit exceeded", nil)
	}
	var scalars, subtables, aots []TableEntry
	for _, e := range tbl.Table {
		if e.Value.Kind == KindTable {
			subtables = append(subtables, e)
		} else if tomlIsAot(e.Value) {
			aots = append(aots, e)
		} else {
			scalars = append(scalars, e)
		}
	}
	prefix := ""
	for j, seg := range path {
		if j > 0 {
			prefix += "."
		}
		prefix += tomlKey(seg)
	}
	for _, e := range scalars {
		out.WriteString(tomlKey(e.Key))
		out.WriteString(" = ")
		s, err := tomlInline(e.Value, depth, limit)
		if err != nil {
			return err
		}
		out.WriteString(s)
		out.WriteByte('\n')
	}
	for _, e := range subtables {
		if prefix != "" {
			out.WriteString("[" + prefix + "." + tomlKey(e.Key) + "]\n")
		} else {
			out.WriteString("[" + tomlKey(e.Key) + "]\n")
		}
		sub := append(append([]string{}, path...), e.Key)
		if err := tomlEmitTable(e.Value, sub, out, depth+1, limit); err != nil {
			return err
		}
	}
	for _, e := range aots {
		for _, el := range e.Value.Array {
			if prefix != "" {
				out.WriteString("[[" + prefix + "." + tomlKey(e.Key) + "]]\n")
			} else {
				out.WriteString("[[" + tomlKey(e.Key) + "]]\n")
			}
			sub := append(append([]string{}, path...), e.Key)
			if err := tomlEmitTable(el, sub, out, depth+1, limit); err != nil {
				return err
			}
		}
	}
	return nil
}

func tomlKey(k string) string {
	bare := len(k) > 0
	for _, ch := range k {
		if !isBareKeyByte(byte(ch)) {
			bare = false
			break
		}
	}
	if bare {
		return k
	}
	return tomlQuote(k)
}

func tomlQuote(s string) string {
	var out strings.Builder
	out.WriteByte('"')
	for _, ch := range s {
		switch ch {
		case '"':
			out.WriteString("\\\"")
		case '\\':
			out.WriteString("\\\\")
		case '\b':
			out.WriteString("\\b")
		case '\t':
			out.WriteString("\\t")
		case '\n':
			out.WriteString("\\n")
		case '\f':
			out.WriteString("\\f")
		case '\r':
			out.WriteString("\\r")
		default:
			if ch < 0x20 || ch == 0x7F {
				out.WriteString(formatU4(uint32(ch)))
			} else {
				out.WriteRune(ch)
			}
		}
	}
	out.WriteByte('"')
	return out.String()
}

func tomlInline(v Value, depth, limit int) (string, error) {
	switch v.Kind {
	case KindNull:
		return "", NewError(ErrTOMLSyntax, "null is not a TOML value", nil)
	case KindBool:
		if v.Bool {
			return "true", nil
		}
		return "false", nil
	case KindInt:
		return formatInt(v.Int), nil
	case KindUint:
		if v.Uint > uint64(1<<63-1) {
			return "", NewError(ErrTOMLSyntax, "unsigned value out of TOML 64-bit signed range", nil)
		}
		return formatUint(v.Uint), nil
	case KindFloat:
		if math.IsNaN(v.Float) {
			return "nan", nil
		}
		if math.IsInf(v.Float, 1) {
			return "inf", nil
		}
		if math.IsInf(v.Float, -1) {
			return "-inf", nil
		}
		return RenderFloat(v.Float), nil
	case KindStr:
		return tomlQuote(v.Str), nil
	case KindDatetime:
		if !datetimeOK(v.Datetime.Raw, string(v.Datetime.Kind)) {
			return "", NewError(ErrTOMLDatetime, "invalid datetime raw text", nil)
		}
		return v.Datetime.Raw, nil
	case KindBytes:
		return "", NewError(ErrTOMLBytes, "Bytes values cannot be encoded as TOML", nil)
	case KindArray:
		if depth > limit {
			return "", NewError(ErrTOMLDepth, "depth limit exceeded", nil)
		}
		parts := make([]string, 0, len(v.Array))
		for _, x := range v.Array {
			s, err := tomlInline(x, depth+1, limit)
			if err != nil {
				return "", err
			}
			parts = append(parts, s)
		}
		return "[" + strings.Join(parts, ", ") + "]", nil
	case KindTable:
		if depth > limit {
			return "", NewError(ErrTOMLDepth, "depth limit exceeded", nil)
		}
		if len(v.Table) == 0 {
			return "{}", nil
		}
		parts := make([]string, 0, len(v.Table))
		for _, e := range v.Table {
			s, err := tomlInline(e.Value, depth+1, limit)
			if err != nil {
				return "", err
			}
			parts = append(parts, tomlKey(e.Key)+" = "+s)
		}
		return "{ " + strings.Join(parts, ", ") + " }", nil
	}
	return "", NewError(ErrTOMLSyntax, "unsupported value", nil)
}

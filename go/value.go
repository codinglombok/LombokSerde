// Package lombokserde is the Go port of the LombokSerde contract:
// zero-dependency JSON (RFC 8259), TOML (v1.0) and MessagePack codecs with
// byte-identical behavior across all ecosystem ports.
//
// See docs/SPEC_LombokSerde_v0.1.0.md for the normative specification and
// vectors/lombokserde-vectors-v1.json for the shared test vectors.
package lombokserde

import (
	"fmt"
	"strings"
)

// Kind discriminates the tagged Value union.
type Kind string

const (
	KindNull     Kind = "null"
	KindBool     Kind = "bool"
	KindInt      Kind = "int"
	KindUint     Kind = "uint"
	KindFloat    Kind = "float"
	KindStr      Kind = "str"
	KindBytes    Kind = "bytes"
	KindArray    Kind = "array"
	KindTable    Kind = "table"
	KindDatetime Kind = "datetime"
)

// DatetimeKind mirrors the TOML datetime kinds (SPEC section 2).
type DatetimeKind string

const (
	DatetimeOffset  DatetimeKind = "offset"
	DatetimeLocalDT DatetimeKind = "localdt"
	DatetimeDate    DatetimeKind = "date"
	DatetimeTime    DatetimeKind = "time"
)

// Datetime preserves the exact source text for TOML decode; MessagePack
// timestamps decode to the canonical `...Z` form.
type Datetime struct {
	Kind DatetimeKind
	Raw  string
}

// TableEntry is one sorted key/value pair of a Table value.
type TableEntry struct {
	Key   string
	Value Value
}

// Value is the canonical tagged union shared by all formats.
// Invariant: Table entries are sorted bytewise by key, without duplicates.
type Value struct {
	Kind     Kind
	Bool     bool
	Int      int64
	Uint     uint64
	Float    float64
	Str      string
	Bytes    []byte
	Array    []Value
	Table    []TableEntry
	Datetime Datetime
}

// Constructors ---------------------------------------------------------------

func NewNull() Value       { return Value{Kind: KindNull} }
func NewBool(b bool) Value { return Value{Kind: KindBool, Bool: b} }
func NewInt(n int64) Value { return Value{Kind: KindInt, Int: n} }
func NewUint(n uint64) Value {
	return Value{Kind: KindUint, Uint: n}
}
func NewFloat(f float64) Value { return Value{Kind: KindFloat, Float: f} }
func NewStr(s string) Value    { return Value{Kind: KindStr, Str: s} }
func NewBytes(b []byte) Value  { return Value{Kind: KindBytes, Bytes: b} }
func NewArray(items []Value) Value {
	return Value{Kind: KindArray, Array: items}
}

func NewDatetime(kind DatetimeKind, raw string) Value {
	return Value{Kind: KindDatetime, Datetime: Datetime{Kind: kind, Raw: raw}}
}

// NewTable sorts the pairs bytewise and fails closed on duplicates.
func NewTable(pairs []TableEntry) (Value, error) {
	sortEntries(pairs)
	for j := 1; j < len(pairs); j++ {
		if pairs[j-1].Key == pairs[j].Key {
			return Value{}, NewError(ErrTableDuplicate, fmt.Sprintf("duplicate key %q", pairs[j].Key), nil)
		}
	}
	return Value{Kind: KindTable, Table: pairs}, nil
}

// TableUnchecked builds a table from pairs known to be duplicate-free.
func TableUnchecked(pairs []TableEntry) Value {
	sortEntries(pairs)
	return Value{Kind: KindTable, Table: pairs}
}

// TableGet looks a key up by binary search (bytewise order).
func (v Value) TableGet(key string) (Value, bool) {
	if v.Kind != KindTable {
		return Value{}, false
	}
	kb := []byte(key)
	lo, hi := 0, len(v.Table)
	for lo < hi {
		mid := (lo + hi) / 2
		switch bytesCmp([]byte(v.Table[mid].Key), kb) {
		case 0:
			return v.Table[mid].Value, true
		case -1:
			lo = mid + 1
		default:
			hi = mid
		}
	}
	return Value{}, false
}

func sortEntries(pairs []TableEntry) {
	// insertion sort keeps the dependency surface zero and is fine for the
	// sizes serde documents reach in tests; stable and deterministic
	for j := 1; j < len(pairs); j++ {
		for k := j; k > 0 && bytesCmp([]byte(pairs[k].Key), []byte(pairs[k-1].Key)) < 0; k-- {
			pairs[k], pairs[k-1] = pairs[k-1], pairs[k]
		}
	}
}

func bytesCmp(a, b []byte) int {
	n := len(a)
	if len(b) < n {
		n = len(b)
	}
	for j := 0; j < n; j++ {
		if a[j] != b[j] {
			if a[j] < b[j] {
				return -1
			}
			return 1
		}
	}
	switch {
	case len(a) < len(b):
		return -1
	case len(a) > len(b):
		return 1
	}
	return 0
}

// pathJSON encodes a key path injectively (distinguishes [] from [""]).
func pathJSON(p []string) string {
	var sb strings.Builder
	sb.WriteByte('[')
	for j, seg := range p {
		if j > 0 {
			sb.WriteByte(',')
		}
		sb.WriteByte('"')
		for _, ch := range seg {
			switch ch {
			case '"':
				sb.WriteString("\\\"")
			case '\\':
				sb.WriteString("\\\\")
			default:
				sb.WriteRune(ch)
			}
		}
		sb.WriteByte('"')
	}
	sb.WriteByte(']')
	return sb.String()
}

func decodePath(k string) []string {
	body := k[1 : len(k)-1]
	if len(body) == 0 {
		return []string{}
	}
	segs := []string{}
	cur := strings.Builder{}
	j := 0
	for j < len(body) {
		if body[j] == ',' {
			segs = append(segs, cur.String())
			cur.Reset()
			j++
			continue
		}
		if body[j] == '"' && j+1 < len(body) {
			// a quoted segment starts; unescape until the closing quote
			j++
			for j < len(body) && body[j] != '"' {
				if body[j] == '\\' && j+1 < len(body) {
					j++
				}
				cur.WriteByte(body[j])
				j++
			}
			j++ // closing quote
			continue
		}
		cur.WriteByte(body[j])
		j++
	}
	segs = append(segs, cur.String())
	return segs
}

func isBareKeyByte(c byte) bool {
	return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == '_' || c == '-'
}

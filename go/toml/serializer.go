package toml

import (
	"fmt"
	"math"
	"strings"

	serde "github.com/codinglombok/LombokSerde/go"
)

// Stringify serializes a Value (map) to a TOML string.
func Stringify(v *serde.Value) string {
	if v == nil || v.Kind != serde.KindMap {
		return ""
	}
	var sb strings.Builder
	writeTable(v.Map, nil, &sb)
	return sb.String()
}

func writeTable(m map[string]*serde.Value, path []string, sb *strings.Builder) {
	// Simple key-value pairs first
	for k, v := range m {
		if !isTableOrArrayOfTables(v) {
			sb.WriteString(writeKey(k))
			sb.WriteString(" = ")
			sb.WriteString(writeValueInline(v))
			sb.WriteByte('\n')
		}
	}

	// Sub-tables
	for k, v := range m {
		if v.Kind == serde.KindMap && !isInlineTable(v) {
			newPath := append(append([]string{}, path...), k)
			sb.WriteByte('\n')
			sb.WriteByte('[')
			sb.WriteString(joinKeys(newPath))
			sb.WriteString("]\n")
			writeTable(v.Map, newPath, sb)
		} else if v.Kind == serde.KindArray && isArrayOfTables(v) {
			newPath := append(append([]string{}, path...), k)
			for _, item := range v.Array {
				if item.Kind == serde.KindMap {
					sb.WriteByte('\n')
					sb.WriteString("[[")
					sb.WriteString(joinKeys(newPath))
					sb.WriteString("]]\n")
					writeTable(item.Map, newPath, sb)
				}
			}
		}
	}
}

func isTableOrArrayOfTables(v *serde.Value) bool {
	if v.Kind == serde.KindMap && !isInlineTable(v) {
		return true
	}
	if v.Kind == serde.KindArray && isArrayOfTables(v) {
		return true
	}
	return false
}

func isInlineTable(v *serde.Value) bool {
	if v.Kind != serde.KindMap || len(v.Map) > 4 {
		return false
	}
	for _, val := range v.Map {
		switch val.Kind {
		case serde.KindNull, serde.KindBool, serde.KindInteger, serde.KindFloat,
			serde.KindString, serde.KindBytes, serde.KindDateTime:
			continue
		default:
			return false
		}
	}
	return true
}

func isArrayOfTables(v *serde.Value) bool {
	if v.Kind != serde.KindArray || len(v.Array) == 0 {
		return false
	}
	for _, item := range v.Array {
		if item.Kind != serde.KindMap {
			return false
		}
	}
	return true
}

func joinKeys(keys []string) string {
	parts := make([]string, len(keys))
	for i, k := range keys {
		parts[i] = writeKey(k)
	}
	return strings.Join(parts, ".")
}

func writeKey(key string) string {
	if isBareKey(key) {
		return key
	}
	return writeBasicString(key)
}

func isBareKey(key string) bool {
	if len(key) == 0 {
		return false
	}
	for _, ch := range key {
		if !((ch >= 'A' && ch <= 'Z') || (ch >= 'a' && ch <= 'z') || (ch >= '0' && ch <= '9') || ch == '_' || ch == '-') {
			return false
		}
	}
	return true
}

func writeValueInline(v *serde.Value) string {
	if v == nil {
		return "\"null\""
	}
	switch v.Kind {
	case serde.KindNull:
		return "\"null\""
	case serde.KindBool:
		if v.Bool {
			return "true"
		}
		return "false"
	case serde.KindInteger:
		return fmt.Sprintf("%d", v.Integer)
	case serde.KindFloat:
		if math.IsNaN(v.Float) {
			return "nan"
		}
		if math.IsInf(v.Float, 1) {
			return "inf"
		}
		if math.IsInf(v.Float, -1) {
			return "-inf"
		}
		s := fmt.Sprintf("%g", v.Float)
		if !strings.Contains(s, ".") && !strings.Contains(s, "e") && !strings.Contains(s, "E") {
			s += ".0"
		}
		return s
	case serde.KindString:
		return writeBasicString(v.Str)
	case serde.KindBytes:
		parts := make([]string, len(v.Bytes))
		for i, b := range v.Bytes {
			parts[i] = fmt.Sprintf("%d", b)
		}
		return "[" + strings.Join(parts, ", ") + "]"
	case serde.KindDateTime:
		if v.DateTime != nil {
			return v.DateTime.Value
		}
		return "\"null\""
	case serde.KindArray:
		items := make([]string, len(v.Array))
		for i, item := range v.Array {
			items[i] = writeValueInline(item)
		}
		return "[" + strings.Join(items, ", ") + "]"
	case serde.KindMap:
		var parts []string
		for k, val := range v.Map {
			parts = append(parts, writeKey(k)+" = "+writeValueInline(val))
		}
		return "{" + strings.Join(parts, ", ") + "}"
	default:
		return "\"null\""
	}
}

func writeBasicString(s string) string {
	var sb strings.Builder
	sb.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			sb.WriteString("\\\"")
		case '\\':
			sb.WriteString("\\\\")
		case '\b':
			sb.WriteString("\\b")
		case '\t':
			sb.WriteString("\\t")
		case '\n':
			sb.WriteString("\\n")
		case '\f':
			sb.WriteString("\\f")
		case '\r':
			sb.WriteString("\\r")
		default:
			if r < 0x20 {
				fmt.Fprintf(&sb, "\\u%04X", r)
			} else {
				sb.WriteRune(r)
			}
		}
	}
	sb.WriteByte('"')
	return sb.String()
}

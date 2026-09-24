package json

import (
	"fmt"
	"math"
	"strings"

	serde "github.com/codinglombok/LombokSerde/go"
)

// ToString serializes a Value to compact JSON.
func ToString(v *serde.Value) string {
	var sb strings.Builder
	writeValue(v, &sb)
	return sb.String()
}

// ToStringPretty serializes a Value to pretty-printed JSON with 2-space indent.
func ToStringPretty(v *serde.Value) string {
	return ToStringPrettyIndent(v, "  ")
}

// ToStringPrettyIndent serializes with custom indent.
func ToStringPrettyIndent(v *serde.Value, indent string) string {
	var sb strings.Builder
	writePretty(v, &sb, indent, 0)
	return sb.String()
}

func writeValue(v *serde.Value, sb *strings.Builder) {
	if v == nil {
		sb.WriteString("null")
		return
	}
	switch v.Kind {
	case serde.KindNull:
		sb.WriteString("null")
	case serde.KindBool:
		if v.Bool {
			sb.WriteString("true")
		} else {
			sb.WriteString("false")
		}
	case serde.KindInteger:
		fmt.Fprintf(sb, "%d", v.Integer)
	case serde.KindFloat:
		if math.IsNaN(v.Float) || math.IsInf(v.Float, 0) {
			sb.WriteString("null")
		} else {
			fmt.Fprintf(sb, "%g", v.Float)
		}
	case serde.KindString:
		writeString(v.Str, sb)
	case serde.KindBytes:
		sb.WriteByte('[')
		for i, b := range v.Bytes {
			if i > 0 {
				sb.WriteByte(',')
			}
			fmt.Fprintf(sb, "%d", b)
		}
		sb.WriteByte(']')
	case serde.KindDateTime:
		if v.DateTime != nil {
			writeString(v.DateTime.Value, sb)
		} else {
			sb.WriteString("null")
		}
	case serde.KindArray:
		sb.WriteByte('[')
		for i, item := range v.Array {
			if i > 0 {
				sb.WriteByte(',')
			}
			writeValue(item, sb)
		}
		sb.WriteByte(']')
	case serde.KindMap:
		sb.WriteByte('{')
		first := true
		for k, val := range v.Map {
			if !first {
				sb.WriteByte(',')
			}
			first = false
			writeString(k, sb)
			sb.WriteByte(':')
			writeValue(val, sb)
		}
		sb.WriteByte('}')
	}
}

func writePretty(v *serde.Value, sb *strings.Builder, indent string, depth int) {
	if v == nil {
		sb.WriteString("null")
		return
	}
	switch v.Kind {
	case serde.KindArray:
		if len(v.Array) == 0 {
			sb.WriteString("[]")
			return
		}
		sb.WriteString("[\n")
		inner := strings.Repeat(indent, depth+1)
		outer := strings.Repeat(indent, depth)
		for i, item := range v.Array {
			if i > 0 {
				sb.WriteString(",\n")
			}
			sb.WriteString(inner)
			writePretty(item, sb, indent, depth+1)
		}
		sb.WriteByte('\n')
		sb.WriteString(outer)
		sb.WriteByte(']')
	case serde.KindMap:
		if len(v.Map) == 0 {
			sb.WriteString("{}")
			return
		}
		sb.WriteString("{\n")
		inner := strings.Repeat(indent, depth+1)
		outer := strings.Repeat(indent, depth)
		first := true
		for k, val := range v.Map {
			if !first {
				sb.WriteString(",\n")
			}
			first = false
			sb.WriteString(inner)
			writeString(k, sb)
			sb.WriteString(": ")
			writePretty(val, sb, indent, depth+1)
		}
		sb.WriteByte('\n')
		sb.WriteString(outer)
		sb.WriteByte('}')
	default:
		writeValue(v, sb)
	}
}

func writeString(s string, sb *strings.Builder) {
	sb.WriteByte('"')
	for _, r := range s {
		switch r {
		case '"':
			sb.WriteString("\\\"")
		case '\\':
			sb.WriteString("\\\\")
		case '\b':
			sb.WriteString("\\b")
		case '\f':
			sb.WriteString("\\f")
		case '\n':
			sb.WriteString("\\n")
		case '\r':
			sb.WriteString("\\r")
		case '\t':
			sb.WriteString("\\t")
		default:
			if r < 0x20 {
				fmt.Fprintf(sb, "\\u%04X", r)
			} else {
				sb.WriteRune(r)
			}
		}
	}
	sb.WriteByte('"')
}

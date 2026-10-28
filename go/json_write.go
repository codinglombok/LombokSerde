package lombokserde

import (
	"math"
	"strconv"
	"strings"
)

func jsonWrite(out *strings.Builder, v Value, depth, limit int) error {
	switch v.Kind {
	case KindNull:
		out.WriteString("null")
	case KindBool:
		if v.Bool {
			out.WriteString("true")
		} else {
			out.WriteString("false")
		}
	case KindInt:
		out.WriteString(formatInt(v.Int))
	case KindUint:
		out.WriteString(formatUint(v.Uint))
	case KindFloat:
		if math.IsNaN(v.Float) || math.IsInf(v.Float, 0) {
			return NewError(ErrJSONFloatNaN, "non-finite float is not valid JSON", nil)
		}
		out.WriteString(RenderFloat(v.Float))
	case KindStr:
		jsonQuote(out, v.Str)
	case KindBytes:
		return NewError(ErrJSONBytes, "Bytes values cannot be encoded as JSON", nil)
	case KindDatetime:
		return NewError(ErrJSONDatetime, "Datetime values cannot be encoded as JSON", nil)
	case KindArray:
		if depth > limit {
			return NewError(ErrJSONDepth, "depth limit exceeded", nil)
		}
		out.WriteByte('[')
		for j, x := range v.Array {
			if j > 0 {
				out.WriteByte(',')
			}
			if err := jsonWrite(out, x, depth+1, limit); err != nil {
				return err
			}
		}
		out.WriteByte(']')
	case KindTable:
		if depth > limit {
			return NewError(ErrJSONDepth, "depth limit exceeded", nil)
		}
		out.WriteByte('{')
		for j, e := range v.Table {
			if j > 0 {
				out.WriteByte(',')
			}
			jsonQuote(out, e.Key)
			out.WriteByte(':')
			if err := jsonWrite(out, e.Value, depth+1, limit); err != nil {
				return err
			}
		}
		out.WriteByte('}')
	default:
		return NewError(ErrJSONSyntax, "unsupported value kind: "+string(v.Kind), nil)
	}
	return nil
}

func formatInt(n int64) string {
	// strconv is std and produces canonical minimal decimal digits
	return strconv.FormatInt(n, 10)
}

func formatUint(n uint64) string {
	return strconv.FormatUint(n, 10)
}

func jsonQuote(out *strings.Builder, s string) {
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
			if ch < 0x20 {
				out.WriteString(formatU4(uint32(ch)))
			} else {
				out.WriteRune(ch)
			}
		}
	}
	out.WriteByte('"')
}

func formatU4(o uint32) string {
	const hexd = "0123456789abcdef"
	return "\\u" + string([]byte{
		hexd[(o>>12)&0xf], hexd[(o>>8)&0xf], hexd[(o>>4)&0xf], hexd[o&0xf],
	})
}

package lombokserde

import (
	"fmt"
	"math"
	"os"
	"path/filepath"
	"testing"
)

// --- shared vector runner (mirrors the other ports) -------------------------

func loadVectors(t *testing.T) []map[string]any {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("..", "vectors", "lombokserde-vectors-v1.json"))
	if err != nil {
		t.Fatalf("vector file readable: %v", err)
	}
	doc, err := JsonDecode(raw, nil)
	if err != nil {
		t.Fatalf("vector file is valid JSON: %v", err)
	}
	casesV, ok := doc.TableGet("cases")
	if !ok || casesV.Kind != KindArray {
		t.Fatalf("vector file has no cases array")
	}
	out := make([]map[string]any, 0, len(casesV.Array))
	for _, cv := range casesV.Array {
		out = append(out, valueToPlainMap(t, cv))
	}
	return out
}

func valueToPlainMap(t *testing.T, v Value) map[string]any {
	t.Helper()
	if v.Kind != KindTable {
		panic("case is not a table")
	}
	m := map[string]any{}
	for _, e := range v.Table {
		m[e.Key] = plainValue(e.Value)
	}
	return m
}

func plainValue(v Value) any {
	switch v.Kind {
	case KindNull:
		return nil
	case KindBool:
		return v.Bool
	case KindInt:
		return v.Int
	case KindUint:
		return v.Uint
	case KindFloat:
		return v.Float
	case KindStr:
		return v.Str
	case KindBytes:
		return hexEncodeLower(v.Bytes)
	case KindDatetime:
		return map[string]any{"$d": []any{string(v.Datetime.Kind), v.Datetime.Raw}}
	case KindArray:
		out := make([]any, 0, len(v.Array))
		for _, x := range v.Array {
			out = append(out, plainValue(x))
		}
		return out
	case KindTable:
		m := map[string]any{}
		for _, e := range v.Table {
			m[e.Key] = plainValue(e.Value)
		}
		return m
	}
	panic("unexpected kind " + string(v.Kind))
}

func hexEncodeLower(b []byte) string {
	const hexd = "0123456789abcdef"
	out := make([]byte, 0, len(b)*2)
	for _, x := range b {
		out = append(out, hexd[x>>4], hexd[x&0xf])
	}
	return string(out)
}

func hexDecodeLower(s string) []byte {
	out := make([]byte, 0, len(s)/2)
	for j := 0; j+1 < len(s); j += 2 {
		var v byte
		for k := 0; k < 2; k++ {
			c := s[j+k]
			var d byte
			switch {
			case c >= '0' && c <= '9':
				d = c - '0'
			case c >= 'a' && c <= 'f':
				d = c - 'a' + 10
			default:
				d = c - 'A' + 10
			}
			v = v*16 + d
		}
		out = append(out, v)
	}
	return out
}

// VVE -----------------------------------------------------------------------

func vveParse(v any) Value {
	switch x := v.(type) {
	case nil:
		return NewNull()
	case bool:
		return NewBool(x)
	case string:
		return NewStr(x)
	case float64:
		return NewFloat(x)
	case []any:
		items := make([]Value, 0, len(x))
		for _, e := range x {
			items = append(items, vveParse(e))
		}
		return NewArray(items)
	case map[string]any:
		if len(x) != 1 {
			panic("VVE object must have exactly one key")
		}
		for tag, payload := range x {
			switch tag {
			case "$i":
				n, err := parseInt64(payload.(string))
				if err != nil {
					panic("bad $i payload: " + payload.(string))
				}
				return NewInt(n)
			case "$u":
				u, err := parseUint64(payload.(string))
				if err != nil {
					panic("bad $u payload: " + payload.(string))
				}
				return NewUint(u)
			case "$f":
				s := payload.(string)
				switch s {
				case "inf":
					return NewFloat(inf(1))
				case "-inf":
					return NewFloat(inf(-1))
				case "nan":
					return NewFloat(nan())
				}
				return NewFloat(parseFloat64(s))
			case "$b":
				return NewBytes(hexDecodeLower(payload.(string)))
			case "$d":
				arr := payload.([]any)
				return NewDatetime(DatetimeKind(arr[0].(string)), arr[1].(string))
			case "$t":
				pairs := []TableEntry{}
				for _, kv := range payload.([]any) {
					pair := kv.([]any)
					pairs = append(pairs, TableEntry{Key: pair[0].(string), Value: vveParse(pair[1])})
				}
				return TableUnchecked(pairs)
			}
			panic("unknown VVE tag " + tag)
		}
	}
	panic(fmt.Sprintf("unexpected VVE node %v", v))
}

func valueEq(a, b Value) bool {
	if a.Kind != b.Kind {
		return false
	}
	switch a.Kind {
	case KindNull:
		return true
	case KindBool:
		return a.Bool == b.Bool
	case KindInt:
		return a.Int == b.Int
	case KindUint:
		return a.Uint == b.Uint
	case KindFloat:
		return math.Float64bits(a.Float) == math.Float64bits(b.Float)
	case KindStr:
		return a.Str == b.Str
	case KindBytes:
		return string(a.Bytes) == string(b.Bytes)
	case KindDatetime:
		return a.Datetime == b.Datetime
	case KindArray:
		if len(a.Array) != len(b.Array) {
			return false
		}
		for j := range a.Array {
			if !valueEq(a.Array[j], b.Array[j]) {
				return false
			}
		}
		return true
	case KindTable:
		if len(a.Table) != len(b.Table) {
			return false
		}
		for j := range a.Table {
			if a.Table[j].Key != b.Table[j].Key || !valueEq(a.Table[j].Value, b.Table[j].Value) {
				return false
			}
		}
		return true
	}
	return false
}

func mustAnyVal(m map[string]any, k string) any {
	v, ok := getAny(m, k)
	if !ok {
		panic("missing key " + k)
	}
	return v
}

func mustAny(t *testing.T, m map[string]any, k string) any {
	t.Helper()
	v, ok := getAny(m, k)
	if !ok {
		t.Fatalf("missing key %s", k)
	}
	return v
}

func d_any(om map[string]any) (int, bool) {
	switch d := om["depth"].(type) {
	case float64:
		return int(d), true
	case int64:
		return int(d), true
	}
	return 0, false
}

func getAny(m map[string]any, k string) (any, bool) {
	v, ok := m[k]
	return v, ok
}

func TestSharedVectorsBitIdentical(t *testing.T) {
	cases := loadVectors(t)
	if len(cases) < 100 {
		t.Fatalf("expected >= 100 vector cases, got %d", len(cases))
	}
	for _, c := range cases {
		id := mustAny(t, c, "id").(string)
		t.Run(id, func(t *testing.T) {
			format := mustAny(t, c, "format").(string)
			op := mustAny(t, c, "op").(string)
			depth := DefaultDepthLimit
			if opts, ok := getAny(c, "options"); ok && opts != nil {
				om := opts.(map[string]any)
				if d, ok := d_any(om); ok {
					depth = d
				}
			}
			expect := mustAny(t, c, "expect").(map[string]any)

			got, gotEnc, runErr := runCaseOp(format, op, c, depth)
			if runErr != nil {
				expErrAny, hasE := getAny(expect, "error")
				expErr, isMap := expErrAny.(map[string]any)
				if !hasE || !isMap {
					t.Fatalf("operation failed but no error expected: %v", runErr)
				}
				se, ok := runErr.(*Error)
				if !ok {
					t.Fatalf("unexpected error type %T", runErr)
				}
				if se.Code != expErr["code"].(string) {
					t.Fatalf("error code mismatch: got %s want %s", se.Code, expErr["code"])
				}
				wantOff := expErr["offset"]
				switch wo := wantOff.(type) {
				case float64:
					if se.Offset == nil || int(*se.Offset) != int(wo) {
						t.Fatalf("error offset mismatch: got %v want %v", se.Offset, int(wo))
					}
				case int64:
					if se.Offset == nil || int(*se.Offset) != int(wo) {
						t.Fatalf("error offset mismatch: got %v want %v", se.Offset, int(wo))
					}
				default:
					if se.Offset != nil {
						t.Fatalf("error offset mismatch: got %v want null", *se.Offset)
					}
				}
				return
			}
			if _, hasErr := expect["error"]; hasErr {
				t.Fatalf("expected an error but the operation succeeded")
			}
			if expVal, hasV := getAny(expect, "value"); hasV {
				want := vveParse(expVal)
				if !valueEq(got, want) {
					t.Fatalf("value mismatch\n  got:  %#v\n  want: %#v", got, want)
				}
			}
			if expEncAny, hasE := getAny(expect, "encoding"); hasE {
				expEnc := expEncAny.(string)
				if gotEnc != expEnc {
					t.Fatalf("encoding mismatch\n  got:  %q\n  want: %q", gotEnc, expEnc)
				}
			}
		})
	}
}

func runCaseOp(format, op string, c map[string]any, depth int) (Value, string, error) {
	if op == "decode" {
		var input []byte
		if in, ok := getAny(c, "input"); ok && in != nil {
			input = []byte(in.(string))
		} else if hx, ok := getAny(c, "input_hex"); ok && hx != nil {
			input = hexDecodeLower(hx.(string))
		}
		switch format {
		case "json":
			v, err := JsonDecode(input, &JsonOptions{DepthLimit: depth})
			if err != nil {
				return Value{}, "", err
			}
			enc, err := JsonEncode(v, &JsonOptions{DepthLimit: depth})
			if err != nil {
				return Value{}, "", err
			}
			return v, string(enc), nil
		case "toml":
			v, err := TomlDecode(input, &TomlOptions{DepthLimit: depth})
			if err != nil {
				return Value{}, "", err
			}
			enc, err := TomlEncode(v, &TomlOptions{DepthLimit: depth})
			if err != nil {
				return Value{}, "", err
			}
			return v, string(enc), nil
		case "msgpack":
			v, err := MsgpackDecode(input, &MsgPackOptions{DepthLimit: depth})
			if err != nil {
				return Value{}, "", err
			}
			enc, err := MsgpackEncode(v, &MsgPackOptions{DepthLimit: depth})
			if err != nil {
				return Value{}, "", err
			}
			return v, hexEncodeLower(enc), nil
		}
		return Value{}, "", fmt.Errorf("unknown format %s", format)
	}
	valAny := mustAnyVal(c, "value")
	v := vveParse(valAny)
	switch format {
	case "json":
		enc, err := JsonEncode(v, &JsonOptions{DepthLimit: depth})
		if err != nil {
			return Value{}, "", err
		}
		back, err := JsonDecode(enc, &JsonOptions{DepthLimit: depth})
		if err != nil {
			return Value{}, "", err
		}
		return back, string(enc), nil
	case "toml":
		enc, err := TomlEncode(v, &TomlOptions{DepthLimit: depth})
		if err != nil {
			return Value{}, "", err
		}
		back, err := TomlDecode(enc, &TomlOptions{DepthLimit: depth})
		if err != nil {
			return Value{}, "", err
		}
		return back, string(enc), nil
	case "msgpack":
		enc, err := MsgpackEncode(v, &MsgPackOptions{DepthLimit: depth})
		if err != nil {
			return Value{}, "", err
		}
		back, err := MsgpackDecode(enc, &MsgPackOptions{DepthLimit: depth})
		if err != nil {
			return Value{}, "", err
		}
		return back, hexEncodeLower(enc), nil
	}
	return Value{}, "", fmt.Errorf("unknown format %s", format)
}

// small helpers used by vveParse
func inf(sign int) float64 {
	if sign < 0 {
		return negInf
	}
	return posInf
}

func nan() float64 { return nanVal }

var (
	posInf = math.Inf(1)
	negInf = math.Inf(-1)
	// SPEC: the canonical quiet NaN bit pattern, not Go's runtime NaN
	nanVal = math.Float64frombits(0x7FF8000000000000)
)

package lombokserde

import (
	"math"
	"strings"
	"testing"
)

// TestOffsetDatetimeRejections exercises the remaining ParseOffsetDatetime
// guard branches (leap seconds, calendar ranges, offset ranges, suffixes).
func TestOffsetDatetimeRejections(t *testing.T) {
	for _, bad := range []string{
		"2024-01-01T00:00:60Z",       // leap second not representable
		"2024-13-01T00:00:00Z",       // month 13
		"2024-00-01T00:00:00Z",       // month 0
		"2024-01-32T00:00:00Z",       // day 32
		"2024-01-00T00:00:00Z",       // day 0
		"2024-01-01T24:00:00Z",       // hour 24
		"2024-01-01T00:60:00Z",       // minute 60
		"2024-01-01T00:00:00+24:00",  // offset hour 24
		"2024-01-01T00:00:00+00:60",  // offset minute 60
		"2024-01-01T00:00:00Zx",      // trailing garbage after Z
		"2024-01-01T00:00:00+00:00x", // trailing garbage after offset
		"2024-01-01T00:00:00+0:00",   // short offset
		"2024-01-01T00:00:00+00x00",  // missing colon in offset
		"2024-01-01T00:00:00.5",      // no zone at all
	} {
		if _, ok := ParseOffsetDatetime(bad); ok {
			t.Fatalf("must reject %q", bad)
		}
	}
	// valid offsets must parse and differ by the signed offset
	a, oka := ParseOffsetDatetime("2024-01-01T12:00:00+01:00")
	b, okb := ParseOffsetDatetime("2024-01-01T11:00:00Z")
	if !oka || !okb || a.sec != b.sec {
		t.Fatalf("offset arithmetic: %+v vs %+v", a, b)
	}
	// fractional seconds land in ns
	c, okc := ParseOffsetDatetime("2024-01-01T00:00:00.123456789+00:00")
	if !okc || c.ns != 123456789 {
		t.Fatalf("ns: %+v", c)
	}
	// lowercase t / space separator accepted
	if _, ok := ParseOffsetDatetime("2024-01-01t00:00:00z"); !ok {
		t.Fatal("lowercase t/z")
	}
	if _, ok := ParseOffsetDatetime("2024-01-01 00:00:00Z"); !ok {
		t.Fatal("space separator")
	}
}

// TestMsgpackDatetimeErrors covers mpWriteDatetime failure branches.
func TestMsgpackDatetimeErrors(t *testing.T) {
	// non-offset datetime cannot map to a MessagePack timestamp
	_, err := MsgpackEncode(NewDatetime(DatetimeDate, "2024-01-01"), nil)
	if err == nil || !strings.Contains(err.Error(), "SERDE_MP_DATETIME") {
		t.Fatalf("local date: %v", err)
	}
	// offset datetime with garbage raw text
	_, err = MsgpackEncode(NewDatetime(DatetimeOffset, "not-a-date"), nil)
	if err == nil || !strings.Contains(err.Error(), "SERDE_MP_DATETIME") {
		t.Fatalf("bad raw: %v", err)
	}
	// big seconds fall to the ext64 carrier and decode back
	v := NewDatetime(DatetimeOffset, "2286-11-20T17:46:40Z")
	enc, err := MsgpackEncode(v, nil)
	if err != nil {
		t.Fatalf("ext64 encode: %v", err)
	}
	got, err := MsgpackDecode(enc, nil)
	if err != nil {
		t.Fatalf("ext64 decode: %v", err)
	}
	if !valueEq(got, v) {
		t.Fatalf("roundtrip: got %v want %v", got, v)
	}
}

// TestTomlInlineEdges covers the tomlInline error branches reachable via
// TomlEncode: null, unsigned overflow, bad datetime raw, depth limits.
func TestTomlInlineEdges(t *testing.T) {
	_, err := TomlEncode(TableUnchecked([]TableEntry{{Key: "n", Value: NewNull()}}), nil)
	if err == nil || !strings.Contains(err.Error(), "SERDE_TOML_SYNTAX") {
		t.Fatalf("null: %v", err)
	}
	_, err = TomlEncode(TableUnchecked([]TableEntry{{Key: "u", Value: NewUint(1 << 63)}}), nil)
	if err == nil || !strings.Contains(err.Error(), "SERDE_TOML_SYNTAX") {
		t.Fatalf("uint overflow: %v", err)
	}
	_, err = TomlEncode(TableUnchecked([]TableEntry{{Key: "d", Value: NewDatetime(DatetimeOffset, "junk")}}), nil)
	if err == nil || !strings.Contains(err.Error(), "SERDE_TOML_DATETIME") {
		t.Fatalf("bad datetime: %v", err)
	}
	deep := NewNull()
	for i := 0; i < 5; i++ {
		deep = NewArray([]Value{deep})
	}
	_, err = TomlEncode(TableUnchecked([]TableEntry{{Key: "a", Value: deep}}), &TomlOptions{DepthLimit: 2})
	if err == nil || !strings.Contains(err.Error(), "SERDE_TOML_DEPTH") {
		t.Fatalf("depth: %v", err)
	}
	// nan / inf present as TOML values
	out, err := TomlEncode(TableUnchecked([]TableEntry{
		{Key: "x", Value: NewFloat(math.NaN())},
		{Key: "y", Value: NewFloat(math.Inf(1))},
		{Key: "z", Value: NewFloat(math.Inf(-1))},
	}), nil)
	if err != nil {
		t.Fatalf("nan/inf: %v", err)
	}
	if !strings.Contains(string(out), "nan") || !strings.Contains(string(out), "inf") {
		t.Fatalf("nan/inf text: %s", out)
	}
}

// TestTomlShareKeyDup decodes a document where a table header collides with
// a value created by a dotted key — collectFrom must report SERDE_TOML_DUPLICATE.
func TestTomlShareKeyDup(t *testing.T) {
	_, err := TomlDecode([]byte("[a]\nb.c = 1\n[a.b]\nd = 2\n"), nil)
	if err == nil || !strings.Contains(err.Error(), "SERDE_TOML_DUPLICATE") {
		t.Fatalf("share key: %v", err)
	}
	// super-table declared after its sub-table is fine
	v, err := TomlDecode([]byte("[a.b]\nx = 1\n[a]\ny = 2\n"), nil)
	if err != nil {
		t.Fatalf("late super table: %v", err)
	}
	a, _ := v.TableGet("a")
	if _, ok := a.TableGet("b"); !ok {
		t.Fatal("missing b")
	}
	// explicit redefinition is a duplicate
	_, err = TomlDecode([]byte("[a]\n[a]\n"), nil)
	if err == nil || !strings.Contains(err.Error(), "SERDE_TOML_DUPLICATE") {
		t.Fatalf("redefine: %v", err)
	}
	// AoT then header on the same name is a duplicate
	_, err = TomlDecode([]byte("[[a]]\n[a]\n"), nil)
	if err == nil || !strings.Contains(err.Error(), "SERDE_TOML_DUPLICATE") {
		t.Fatalf("aot then header: %v", err)
	}
}

// TestTomlQuotedKeys covers pathJSON/decodePath with quotes and commas in
// table headers, plus inline-table edges.
func TestTomlQuotedKeys(t *testing.T) {
	v, err := TomlDecode([]byte("[\"a\\\"b\"]\n\"c,d\" = 1\n"), nil)
	if err != nil {
		t.Fatalf("quoted: %v", err)
	}
	outer, _ := v.TableGet("a\"b")
	if got, ok := outer.TableGet("c,d"); !ok || got.Int != 1 {
		t.Fatalf("quoted roundtrip: %v", outer)
	}
	// inline table: duplicate key is a syntax error (matches the Rust
	// reference: "duplicate key in inline table")
	_, err = TomlDecode([]byte("a = {x = 1, x = 2}\n"), nil)
	if err == nil || !strings.Contains(err.Error(), "SERDE_TOML_SYNTAX") {
		t.Fatalf("inline dup: %v", err)
	}
	// inline table: trailing comma rejected
	_, err = TomlDecode([]byte("a = {x = 1,}\n"), nil)
	if err == nil || !strings.Contains(err.Error(), "SERDE_TOML_SYNTAX") {
		t.Fatalf("inline trailing: %v", err)
	}
	// dotted keys inside an inline table
	v, err = TomlDecode([]byte("a = {b.c = 1}\n"), nil)
	if err != nil {
		t.Fatalf("inline dotted: %v", err)
	}
	av, _ := v.TableGet("a")
	bv, _ := av.TableGet("b")
	if got, ok := bv.TableGet("c"); !ok || got.Int != 1 {
		t.Fatalf("inline dotted value: %v", bv)
	}
	// AoT header with dotted sub-elements
	v, err = TomlDecode([]byte("[[a]]\nb = 1\n[[a]]\nb = 2\n"), nil)
	if err != nil {
		t.Fatalf("aot: %v", err)
	}
	av, _ = v.TableGet("a")
	if len(av.Array) != 2 {
		t.Fatalf("aot len: %v", av)
	}
}

// TestTomlMlLiteral covers multiline literal string edges.
func TestTomlMlLiteral(t *testing.T) {
	cases := []struct{ in, want string }{
		{"a = ''''''\n", ""},         // empty
		{"a = '''\n'''\n", ""},       // first newline trimmed
		{"a = '''x''y'''\n", "x''y"}, // internal double quotes
	}
	for _, c := range cases {
		v, err := TomlDecode([]byte(c.in), nil)
		if err != nil {
			t.Fatalf("%q: %v", c.in, err)
		}
		av, _ := v.TableGet("a")
		if av.Str != c.want {
			t.Fatalf("%q: got %q want %q", c.in, av.Str, c.want)
		}
	}
	// unterminated
	if _, err := TomlDecode([]byte("a = '''x\n"), nil); err == nil {
		t.Fatal("unterminated ml literal")
	}
	// four quotes adjacent to the opening delimiter are not allowed
	// (verified against the Rust reference: error at byte 12)
	if _, err := TomlDecode([]byte("a = ''''q''''\n"), nil); err == nil {
		t.Fatal("four-quote edge must be rejected")
	}
}

// TestTomlDatetimeShapes adds datetimeOK branches via decode roundtrips.
func TestTomlDatetimeShapes(t *testing.T) {
	for _, good := range []string{
		"d = 1979-05-27\n",
		"t = 07:32:00\n",
		"t = 07:32:00.999\n",
		"dt = 1979-05-27 07:32:00Z\n",
		"dt = 1979-05-27T07:32:00.5+07:00\n",
	} {
		if _, err := TomlDecode([]byte(good), nil); err != nil {
			t.Fatalf("%q: %v", good, err)
		}
	}
	for _, bad := range []string{
		"d = 1979-05-99\n",
		"t = 07:32\n",
		"dt = 1979-05-27T07:32:00+\n",
	} {
		if _, err := TomlDecode([]byte(bad), nil); err == nil {
			t.Fatalf("must reject %q", bad)
		}
	}
}

// TestJSONUnicodeEdges covers parseHex4 and surrogate pair error branches.
func TestJSONUnicodeEdges(t *testing.T) {
	for _, bad := range []string{
		"\"\\u00\"",          // truncated hex
		"\"\\uzzzz\"",        // non-hex
		"\"\\uD800\"",        // lone high surrogate
		"\"\\uD800\\u0041\"", // high surrogate without low surrogate
		"\"\\uDC00\\uD800\"", // low surrogate first
	} {
		if _, err := JsonDecode([]byte(bad), nil); err == nil {
			t.Fatalf("must reject %q", bad)
		}
	}
	// valid pair decodes to the astral code point
	v, err := JsonDecode([]byte("\"\\uD83D\\uDE00\""), nil)
	if err != nil || v.Str != "😀" {
		t.Fatalf("pair: %v %q", err, v.Str)
	}
}

// TestMsgpackIntWidths hits the remaining mpWriteInt width branches.
func TestMsgpackIntWidths(t *testing.T) {
	cases := []struct {
		v    Value
		want byte
	}{
		{NewInt(-33), 0xD0},
		{NewInt(-129), 0xD1},
		{NewInt(-32769), 0xD2},
		{NewInt(-2147483649), 0xD3},
		{NewInt(128), 0xCC},
		{NewInt(256), 0xCD},
		{NewInt(65536), 0xCE},
	}
	for _, c := range cases {
		enc, err := MsgpackEncode(c.v, nil)
		if err != nil {
			t.Fatalf("%v: %v", c.v, err)
		}
		if enc[0] != c.want {
			t.Fatalf("%v: got prefix %#x want %#x", c.v, enc[0], c.want)
		}
		back, err := MsgpackDecode(enc, nil)
		if err != nil {
			t.Fatalf("decode %v: %v", c.v, err)
		}
		if back.Int != c.v.Int || back.Kind != c.v.Kind {
			t.Fatalf("roundtrip %v -> %v", c.v, back)
		}
	}
}

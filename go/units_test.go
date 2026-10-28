package lombokserde

import (
	"fmt"
	"math"
	"strings"
	"testing"
)

func encStr(s string) []byte { return []byte(s) }

func mkTable(t *testing.T, pairs ...TableEntry) Value {
	t.Helper()
	v, err := NewTable(pairs)
	if err != nil {
		t.Fatalf("mkTable: %v", err)
	}
	return v
}

func TestFloatPresentationAllRegimes(t *testing.T) {
	cases := []struct {
		in   float64
		want string
	}{
		{0.0, "0.0"},
		{math.Copysign(0, -1), "-0.0"},
		{1.0, "1.0"},
		{-1.5, "-1.5"},
		{0.001, "0.001"},
		{1e-6, "0.000001"},
		{1e-7, "1e-7"},
		{2.5e-10, "2.5e-10"},
		{1e20, "100000000000000000000.0"},
		{1e21, "1e+21"},
		{-1.5e300, "-1.5e+300"},
		{5e-324, "5e-324"},
		{123.456, "123.456"},
		{12.5, "12.5"},
	}
	for _, c := range cases {
		got, err := JsonEncode(NewFloat(c.in), nil)
		if err != nil {
			t.Fatalf("encode %v: %v", c.in, err)
		}
		if string(got) != c.want {
			t.Fatalf("render %v: got %q want %q", c.in, got, c.want)
		}
	}
}

func TestJsonExtras(t *testing.T) {
	v, err := JsonDecode([]byte(`"a\/b"`), nil)
	if err != nil || v.Str != "a/b" {
		t.Fatalf("slash escape: %v %v", v, err)
	}
	if _, err := JsonDecode([]byte(`"\ud83d\u0041"`), nil); err == nil {
		t.Fatalf("invalid low surrogate must fail")
	} else if e := err.(*Error); e.Code != ErrJSONSyntax || *e.Offset != 13 {
		t.Fatalf("bad low surrogate error: %v", e)
	}
	for _, bad := range []string{"1e+", "1ex", "\"a\tb\"", "nul"} {
		if _, err := JsonDecode(encStr(bad), nil); err == nil {
			t.Fatalf("%q must fail", bad)
		}
	}
	deep := mkTable(t, TableEntry{Key: "a", Value: mkTable(t, TableEntry{Key: "b", Value: mkTable(t, TableEntry{Key: "c", Value: NewInt(1)})})})
	if _, err := JsonEncode(deep, &JsonOptions{DepthLimit: 2}); err == nil {
		t.Fatalf("encode depth must fail")
	} else if e := err.(*Error); e.Code != ErrJSONDepth || e.Offset != nil {
		t.Fatalf("encode depth error: %v", e)
	}
	if _, err := JsonEncode(NewFloat(posInf), nil); err == nil {
		t.Fatalf("inf json must fail")
	}
	if _, err := JsonEncode(NewBytes([]byte{1}), nil); err == nil {
		t.Fatalf("bytes json must fail")
	}
}

func TestMsgpackSizeFamilies(t *testing.T) {
	rt := func(v Value) Value {
		enc, err := MsgpackEncode(v, nil)
		if err != nil {
			t.Fatalf("encode: %v", err)
		}
		back, err := MsgpackDecode(enc, nil)
		if err != nil {
			t.Fatalf("decode: %v", err)
		}
		return back
	}
	if got := rt(NewUint(255)); got.Kind != KindInt || got.Int != 255 {
		t.Fatalf("u8 roundtrip: %#v", got)
	}
	if got := rt(NewUint(65535)); got.Int != 65535 {
		t.Fatalf("u16 roundtrip: %#v", got)
	}
	if got := rt(NewUint(4294967295)); got.Int != 4294967295 {
		t.Fatalf("u32 roundtrip: %#v", got)
	}
	if got := rt(NewUint(9223372036854775808)); got.Kind != KindUint || got.Uint != 9223372036854775808 {
		t.Fatalf("u53+ roundtrip: %#v", got)
	}
	if got := rt(NewUint(18446744073709551615)); got.Uint != 18446744073709551615 {
		t.Fatalf("u64max roundtrip: %#v", got)
	}
	if got := rt(NewInt(-9223372036854775808)); got.Int != -9223372036854775808 {
		t.Fatalf("i64min roundtrip: %#v", got)
	}
	for _, n := range []int{100, 300, 65537} {
		s := NewStr(strings.Repeat("x", n))
		if got := rt(s); got.Str != strings.Repeat("x", n) {
			t.Fatalf("str%d roundtrip", n)
		}
		b := NewBytes(make([]byte, n))
		if got := rt(b); len(got.Bytes) != n {
			t.Fatalf("bin%d roundtrip", n)
		}
	}
	arr := NewArray(func() []Value {
		a := make([]Value, 65537)
		for j := range a {
			a[j] = NewNull()
		}
		return a
	}())
	if got := rt(arr); len(got.Array) != 65537 {
		t.Fatalf("array32 roundtrip")
	}
	pairs := make([]TableEntry, 0, 65537)
	for j := 0; j < 65537; j++ {
		pairs = append(pairs, TableEntry{Key: fmt.Sprintf("k%05d", j), Value: NewInt(int64(j))})
	}
	m := TableUnchecked(pairs)
	if got := rt(m); len(got.Table) != 65537 {
		t.Fatalf("map32 roundtrip")
	}
	// exact float32 promotion
	f32v, err := MsgpackDecode([]byte{0xCA, 0x3F, 0xC0, 0x00, 0x00}, nil)
	if err != nil || f32v.Float != 1.5 {
		t.Fatalf("float32: %v %v", f32v, err)
	}
}

func TestMsgpackDepthAndTimestamps(t *testing.T) {
	withPayload := make([]byte, 130)
	for j := range withPayload {
		withPayload[j] = 0x91
	}
	withPayload[129] = 0x01
	if _, err := MsgpackDecode(withPayload, &MsgPackOptions{DepthLimit: 128}); err == nil {
		t.Fatalf("depth 128 must fail")
	} else if e := err.(*Error); e.Code != ErrMPDepth {
		t.Fatalf("depth error code: %v", e)
	}
	if _, err := MsgpackDecode(withPayload, &MsgPackOptions{DepthLimit: 129}); err != nil {
		t.Fatalf("depth 129 must pass: %v", err)
	}
	bad64 := append([]byte{0xD7, 0xFF}, make([]byte, 8)...)
	bits := uint64(1000000000) << 34
	for j := 0; j < 8; j++ {
		bad64[2+j] = byte(bits >> (8 * (7 - j)))
	}
	if _, err := MsgpackDecode(bad64, nil); err == nil {
		t.Fatalf("ts64 ns out of range must fail")
	}
	bad96 := append([]byte{0xC7, 12, 0xFF}, 0x3B, 0x9A, 0xCA)
	bad96 = append(bad96, make([]byte, 12)...)
	if _, err := MsgpackDecode(bad96, nil); err == nil {
		t.Fatalf("ts96 ns out of range must fail")
	}
	ts, err := MsgpackDecode([]byte{0xC7, 4, 0xFF, 1, 2, 3, 4}, nil)
	if err != nil {
		t.Fatalf("ext8 ts32: %v", err)
	}
	direct, err := MsgpackDecode([]byte{0xD6, 0xFF, 1, 2, 3, 4}, nil)
	if err != nil || !valueEq(ts, direct) {
		t.Fatalf("ts32 carriers differ: %v %v", ts, err)
	}
	if DaysFromCivil(1979, 5, 27) != 3433 {
		t.Fatalf("days_from_civil 1979-05-27")
	}
	if y, m, d := CivilFromDays(3433); y != 1979 || m != 5 || d != 27 {
		t.Fatalf("civil_from_days 3433")
	}
	if FormatTimestamp(0, 0) != "1970-01-01T00:00:00Z" {
		t.Fatalf("format ts 0")
	}
	if FormatTimestamp(1, 500000000) != "1970-01-01T00:00:01.5Z" {
		t.Fatalf("format ts frac")
	}
	if FormatTimestamp(-1, 0) != "1969-12-31T23:59:59Z" {
		t.Fatalf("format ts neg")
	}
}

func TestTomlDatetimeMatrix(t *testing.T) {
	ok := []struct {
		text string
		kind string
	}{
		{"1979-05-27", "date"},
		{"07:32:60", "time"},
		{"1979-05-27T07:32:00", "localdt"},
		{"1979-05-27t07:32:00.5", "localdt"},
		{"1979-05-27 07:32:00", "localdt"},
		{"1979-05-27T07:32:00Z", "offset"},
		{"1979-05-27t07:32:00.25-03:30", "offset"},
	}
	for _, c := range ok {
		if !datetimeOK(c.text, c.kind) {
			t.Fatalf("must accept %q (%s)", c.text, c.kind)
		}
	}
	bad := []struct {
		text string
		kind string
	}{
		{"1979-13-27", "date"},
		{"24:00:00", "time"},
		{"07:32:00.", "time"},
		{"1979-05-27T07:32:00Z", "localdt"},
		{"1979-05-27T07:32:00+24:00", "offset"},
		{"1979-05-27T07:32:00+07", "offset"},
		{"1979-05-27T07:32", "offset"},
	}
	for _, c := range bad {
		if datetimeOK(c.text, c.kind) {
			t.Fatalf("must reject %q (%s)", c.text, c.kind)
		}
	}
}

func TestTomlRedefinitionMatrix(t *testing.T) {
	d, err := TomlDecode([]byte("[a.b]\nx = 1\n[a]\ny = 2\n"), nil)
	if err != nil {
		t.Fatalf("implicit promotion: %v", err)
	}
	if _, ok := d.TableGet("a"); !ok {
		t.Fatalf("a missing")
	}
	for _, doc := range []string{"[a]\n[[a]]\n", "a.b = 1\n[[a]]\n"} {
		if _, err := TomlDecode([]byte(doc), nil); err == nil {
			t.Fatalf("%q must fail", doc)
		}
	}
	if _, err := TomlDecode([]byte("[[a]]\nx.y = 1\n"), nil); err == nil {
		t.Fatalf("dotted under aot must fail")
	}
	d2, err := TomlDecode([]byte("[[a]]\nx = 1\ny = 2\n"), nil)
	if err != nil {
		t.Fatalf("aot keyvals: %v", err)
	}
	if arr, ok := d2.TableGet("a"); !ok || arr.Kind != KindArray || len(arr.Array) != 1 {
		t.Fatalf("aot keyvals shape: %#v", d2)
	}
	d3, err := TomlDecode([]byte("[[a]]\nx = 1\n[a.b]\ny = 2\n"), nil)
	if err != nil {
		t.Fatalf("aot subtable: %v", err)
	}
	if arr, ok := d3.TableGet("a"); !ok || len(arr.Array) != 1 || len(arr.Array[0].Table) != 2 {
		t.Fatalf("aot subtable shape: %#v", d3)
	}
	if _, err := TomlDecode([]byte("[\"#x\"]\ny = 1\n"), nil); err == nil {
		t.Fatalf("reserved hash key must fail")
	}
	if _, err := TomlDecode([]byte("a = 1\n[a]\nb = 2\n"), nil); err == nil {
		t.Fatalf("value/table collision must fail")
	}
	if _, err := TomlDecode([]byte("[\"tag\"]\ny = 1\n"), nil); err != nil {
		t.Fatalf("normal quoted key: %v", err)
	}
}

func TestTomlEscapeAndNumberBattery(t *testing.T) {
	d, err := TomlDecode([]byte("a = \"\\b\\t\\n\\f\\r\\\"\\\\é\"\n"), nil)
	if err != nil {
		t.Fatalf("escape decode: %v", err)
	}
	if got, _ := d.TableGet("a"); got.Str != "\b\t\n\f\r\"\\é" {
		t.Fatalf("escape value: %q", got.Str)
	}
	for _, doc := range []string{
		"a = \"\\uZZZZ\"", "a = \"\\U0011FFFF\"", "a = 'x", "a = \"\"\"x",
		"a = 1e_", "a = 1e", "a = 0x", "a = +0x10", "a = -0b11",
		"a = 007", "a = 1_", "a = \"\x00\"", "a = '\x01'", "a = \"\"\"\x01\"\"\"",
		"t = { a = 1, a = 2 }",
	} {
		if _, err := TomlDecode([]byte(doc), nil); err == nil {
			t.Fatalf("%q must fail", doc)
		}
	}
	q, err := TomlDecode([]byte("a = \"\"\"\"\"\"\"\"\n"), nil)
	if err != nil {
		t.Fatalf("ml quotes: %v", err)
	}
	if got, _ := q.TableGet("a"); got.Str != `""` {
		t.Fatalf("ml quotes value: %q", got.Str)
	}
	ml, err := TomlDecode([]byte("a = \"\"\"x\\\n    y\"\"\"\n"), nil)
	if err != nil {
		t.Fatalf("line continuation: %v", err)
	}
	if got, _ := ml.TableGet("a"); got.Str != "xy" {
		t.Fatalf("line continuation value: %q", got.Str)
	}
	inf, err := TomlDecode([]byte("a = +inf\nb = -nan\n"), nil)
	if err != nil {
		t.Fatalf("inf/nan: %v", err)
	}
	if got, _ := inf.TableGet("a"); got.Float != posInf {
		t.Fatalf("+inf")
	}
	if got, _ := inf.TableGet("b"); !isCanonicalNaN(got.Float) {
		t.Fatalf("-nan canonical bits")
	}
}

func isCanonicalNaN(f float64) bool {
	return math.Float64bits(f) == 0x7FF8000000000000
}

func TestTomlEncoderFailures(t *testing.T) {
	if _, err := TomlEncode(NewInt(1), nil); err == nil {
		t.Fatalf("root must fail")
	} else if e := err.(*Error); e.Code != ErrTOMLRoot {
		t.Fatalf("root code: %v", e)
	}
	if _, err := TomlEncode(mkTable(t, TableEntry{Key: "b", Value: NewBytes([]byte{1})}), nil); err == nil {
		t.Fatalf("bytes must fail")
	}
	if _, err := TomlEncode(mkTable(t, TableEntry{Key: "n", Value: NewNull()}), nil); err == nil {
		t.Fatalf("null must fail")
	}
	if _, err := TomlEncode(mkTable(t, TableEntry{Key: "u", Value: NewUint(18446744073709551615)}), nil); err == nil {
		t.Fatalf("uint overflow must fail")
	}
	if _, err := TomlEncode(mkTable(t, TableEntry{Key: "d", Value: NewDatetime(DatetimeOffset, "not-a-date")}), nil); err == nil {
		t.Fatalf("bad datetime must fail")
	}
	deep := mkTable(t, TableEntry{Key: "a", Value: mkTable(t, TableEntry{Key: "b", Value: mkTable(t, TableEntry{Key: "c", Value: NewInt(1)})})})
	if _, err := TomlEncode(deep, &TomlOptions{DepthLimit: 2}); err == nil {
		t.Fatalf("encode depth must fail")
	}
	out, err := TomlEncode(mkTable(t,
		TableEntry{Key: "e", Value: NewArray(nil)},
		TableEntry{Key: "m", Value: NewArray([]Value{TableUnchecked(nil), NewInt(1)})},
		TableEntry{Key: "fin", Value: NewFloat(posInf)},
		TableEntry{Key: "ninf", Value: NewFloat(negInf)},
		TableEntry{Key: "nn", Value: NewFloat(nanVal)},
		TableEntry{Key: "k\"", Value: NewInt(1)},
		TableEntry{Key: "a.b", Value: NewInt(2)},
		TableEntry{Key: "", Value: NewInt(3)},
	), nil)
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	s := string(out)
	for _, want := range []string{
		"e = []", "m = [{}, 1]", "fin = inf", "ninf = -inf", "nn = nan",
		"\"k\\\"\" = 1", "\"a.b\" = 2", "\"\" = 3",
	} {
		if !strings.Contains(s, want) {
			t.Fatalf("output missing %q in %q", want, s)
		}
	}
}

// --- deterministic mutation property ----------------------------------------

type xorShift struct{ s uint32 }

func (x *xorShift) next() uint32 {
	s := x.s
	s ^= s << 13
	s ^= s >> 17
	s ^= s << 5
	x.s = s
	return s
}

func assertSerdeErr(t *testing.T, err error, where string) {
	t.Helper()
	if err == nil {
		return
	}
	e, ok := err.(*Error)
	if !ok || !strings.HasPrefix(e.Code, "SERDE_") {
		t.Fatalf("%s: unexpected error %v", where, err)
	}
}

func TestDecoderMutationProperty(t *testing.T) {
	samples := []struct {
		format string
		data   []byte
	}{
		{"json", jsonSample(t)},
		{"toml", []byte("a = [1, 2.5, \"x\", true]\n[b]\nc = 1979-05-27T07:32:00Z\nd = 0x2A\n")},
		{"msgpack", mpSample(t)},
	}
	for _, sm := range samples {
		decode := func(b []byte) error {
			switch sm.format {
			case "json":
				_, err := JsonDecode(b, nil)
				return err
			case "toml":
				_, err := TomlDecode(b, nil)
				return err
			default:
				_, err := MsgpackDecode(b, nil)
				return err
			}
		}
		for cut := 0; cut < len(sm.data); cut++ {
			assertSerdeErr(t, decode(sm.data[:cut]), fmt.Sprintf("%s truncation at %d", sm.format, cut))
		}
		rng := xorShift{0x5eed ^ uint32(len(sm.data))}
		for iter := 0; iter < 1200; iter++ {
			m := append([]byte{}, sm.data...)
			pos := int(rng.next()) % len(m)
			m[pos] ^= byte(1 + rng.next()%255)
			assertSerdeErr(t, decode(m), fmt.Sprintf("%s flip at %d iter %d", sm.format, pos, iter))
		}
		rng = xorShift{0xbeef ^ uint32(len(sm.data))}
		for iter := 0; iter < 1500; iter++ {
			g := make([]byte, 1+int(rng.next())%24)
			for j := range g {
				g[j] = byte(rng.next() & 0xff)
			}
			assertSerdeErr(t, decode(g), fmt.Sprintf("%s garbage iter %d", sm.format, iter))
		}
	}
}

func jsonSample(t *testing.T) []byte {
	t.Helper()
	out, err := JsonEncode(mkTable(t,
		TableEntry{Key: "a", Value: NewArray([]Value{NewInt(1), NewFloat(2.5), NewStr("x"), NewBool(true), NewNull()})},
		TableEntry{Key: "é", Value: NewFloat(-0.5)},
	), nil)
	mustEnc(t, out, err)
	return out
}

func mpSample(t *testing.T) []byte {
	t.Helper()
	out, err := MsgpackEncode(mkTable(t,
		TableEntry{Key: "a", Value: NewArray([]Value{NewInt(1), NewFloat(2.5), NewStr("x")})},
		TableEntry{Key: "b", Value: NewDatetime(DatetimeOffset, "2024-01-01T00:00:00Z")},
	), nil)
	mustEnc(t, out, err)
	return out
}

func mustEnc(t *testing.T, out []byte, err error) []byte {
	t.Helper()
	if err != nil {
		t.Fatalf("encode: %v", err)
	}
	return out
}

func encOr(t *testing.T, out []byte, err error) []byte {
	return mustEnc(t, out, err)
}

func TestCoverageBattery(t *testing.T) {
	// Error() formatting both branches
	if _, ok := any(&Error{Code: "X", Message: "m"}).(error); !ok {
		t.Fatal("error interface")
	}
	e := NewError("SERDE_X", "m", nil)
	if got := e.Error(); got != "[SERDE_X] m" {
		t.Fatalf("Error() no offset: %q", got)
	}
	off := 3
	if got := NewError("SERDE_X", "m", &off).Error(); got != "[SERDE_X] m (at byte 3)" {
		t.Fatalf("Error() offset: %q", got)
	}
	// TableGet on empty/missing shapes
	empty := TableUnchecked(nil)
	if _, ok := empty.TableGet("x"); ok {
		t.Fatal("empty table get")
	}
	// shortestDigits defensive paths
	if d, exp := shortestDigits(0); d != "0" || exp != 0 {
		t.Fatalf("shortestDigits zero: %q %d", d, exp)
	}
	// parseHex4 invalid/truncated
	if _, err := JsonDecode([]byte(`"\uZZZZ"`), nil); err == nil {
		t.Fatal("bad hex must fail")
	}
	if _, err := JsonDecode([]byte(`"\u12"`), nil); err == nil {
		t.Fatal("truncated hex must fail")
	}
	// parseInt64Base invalid digit / overflow
	if _, err := parseInt64Base("fg", 16); err == nil {
		t.Fatal("bad hex digits must fail")
	}
	if _, err := parseInt64Base("ffffffffffffffffff", 16); err == nil {
		t.Fatal("hex overflow must fail")
	}
	if _, bad := strconvParseFloat("x"); !bad {
		t.Fatal("bad float must report failure")
	}
	// mpWriteInt negative families
	rt := func(v Value) Value {
		out, err := MsgpackEncode(v, nil)
		if err != nil {
			t.Fatalf("enc: %v", err)
		}
		back, err := MsgpackDecode(out, nil)
		if err != nil {
			t.Fatalf("dec: %v", err)
		}
		return back
	}
	if got := rt(NewInt(-32768)); got.Int != -32768 {
		t.Fatalf("i16 min: %#v", got)
	}
	if got := rt(NewInt(-2147483648)); got.Int != -2147483648 {
		t.Fatalf("i32 min: %#v", got)
	}
	// ParseOffsetDatetime null battery
	for _, bad := range []string{
		"1970-01-01T00:00:00Z ", "x970-01-01T00:00:00Z", "1970-01-01T00:00:00",
		"1970-01-01T00:00:00.Z", "1970-01-01T00:00:00+00", "1970-01-01T00:00:00+00:0x",
	} {
		if _, ok := ParseOffsetDatetime(bad); ok {
			t.Fatalf("must reject %q", bad)
		}
	}
	if p, ok := ParseOffsetDatetime("0000-01-01T00:00:00Z"); !ok {
		t.Fatal("year 0000 must parse")
	} else if p.sec == 0 && false {
		t.Fatal("unreachable")
	}
	// pad4/pad9 negative and big years
	if FormatTimestamp(-62135596800, 0) == "" {
		t.Fatal("year-1 formatting")
	}
	// [[a]] header on dotted-created table (dotted redefinition by header)
	if _, err := TomlDecode([]byte("a.b = 1\n[a.c]\nd = 2\n"), nil); err == nil {
		t.Fatal("dotted then header must fail")
	}
	// inline table with dotted keys (nestDotted)
	d, err := TomlDecode([]byte("t = { a.b = 1, c = 2 }\n"), nil)
	if err != nil {
		t.Fatalf("inline dotted: %v", err)
	}
	tv, _ := d.TableGet("t")
	av, _ := tv.TableGet("a")
	if av.Kind != KindTable {
		t.Fatalf("nested inline: %#v", av)
	}
	// multiline literal with CRLF opening and internal blank lines
	m, err := TomlDecode([]byte("s = '''\r\nraw\r\ntext\r\n'''\r\n"), nil)
	if err != nil {
		t.Fatalf("crlf ml: %v", err)
	}
	if got, _ := m.TableGet("s"); got.Str != "raw\r\ntext\r\n" {
		t.Fatalf("crlf ml value: %q", got.Str)
	}
	// datetimeOK degenerate args
	if datetimeOK("1979-05-27", "unknown") {
		t.Fatal("unknown kind must fail")
	}
	// collect/collectFrom through deep headers
	d2, err := TomlDecode([]byte("[a.b.c]\nd.e = 1\n[a.f]\ng = 2\n"), nil)
	if err != nil {
		t.Fatalf("deep headers: %v", err)
	}
	a, _ := d2.TableGet("a")
	b, _ := a.TableGet("b")
	if _, ok := b.TableGet("c"); !ok {
		t.Fatalf("deep shape: %#v", d2)
	}
	// NewTable duplicate via public constructor
	if _, err := NewTable([]TableEntry{{Key: "a"}, {Key: "a"}}); err == nil {
		t.Fatal("public dup must fail")
	}
}

func TestCoverageBattery2(t *testing.T) {
	// negative-year and minimal-fraction timestamp formatting (pad4/pad9)
	ts := DaysFromCivil(-1, 1, 1) * 86400
	if got := FormatTimestamp(ts, 0); got != "-0001-01-01T00:00:00Z" {
		t.Fatalf("negative year: %q", got)
	}
	if got := FormatTimestamp(0, 1); got != "1970-01-01T00:00:00.000000001Z" {
		t.Fatalf("ns pad9: %q", got)
	}
	// tomlQuote escape branches through a key
	out, err := TomlEncode(mkTable(t,
		TableEntry{Key: "a\tb\nc\fd\re\bf\"g\\h", Value: NewInt(1)},
	), nil)
	if err != nil {
		t.Fatalf("quote key: %v", err)
	}
	want := "\"a\\tb\\nc\\fd\\re\\bf\\\"g\\\\h\" = 1\n"
	if string(out) != want {
		t.Fatalf("quote key out: %q want %q", out, want)
	}
	// TableGet binary-search branches
	tv := TableUnchecked([]TableEntry{
		{Key: "a", Value: NewInt(1)},
		{Key: "m", Value: NewInt(2)},
		{Key: "z", Value: NewInt(3)},
	})
	wantInt := map[string]int64{"a": 1, "m": 2, "z": 3}
	for k, w := range wantInt {
		v, ok := tv.TableGet(k)
		if !ok || v.Int != w {
			t.Fatalf("get %s", k)
		}
	}
	if _, ok := tv.TableGet("b"); ok {
		t.Fatal("miss between")
	}
	// hex/oct/bin with underscores and full ranges
	d, err := TomlDecode([]byte("a = 0xFF\nc = 0o7\nd = 0b1\n"), nil)
	if err != nil {
		t.Fatalf("radix: %v", err)
	}
	if v, _ := d.TableGet("a"); v.Int != 255 {
		t.Fatalf("0xFF: %d", v.Int)
	}
	// signs are not allowed on hex/oct/bin (TOML v1.0 ABNF; vector
	// toml_dec_syntax_sign_hex) — must match the Rust reference
	if _, err := TomlDecode([]byte("x = -0x1\n"), nil); err == nil {
		t.Fatal("signed hex must be rejected")
	}
	// msgpack uint encoding families via encode only
	uo, err := MsgpackEncode(NewUint(4294967296), nil)
	if err != nil || len(uo) != 9 || uo[0] != 0xCF {
		t.Fatalf("u32+1: %x %v", uo, err)
	}
}

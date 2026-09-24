package json

import (
	"testing"

	serde "github.com/codinglombok/LombokSerde/go"
)

func TestParseNull(t *testing.T) {
	v, err := Parse("null")
	if err != nil {
		t.Fatal(err)
	}
	if v.Kind != serde.KindNull {
		t.Errorf("expected null, got %s", v.TypeName())
	}
}

func TestParseBool(t *testing.T) {
	v, _ := Parse("true")
	if !v.Bool {
		t.Error("expected true")
	}
	v, _ = Parse("false")
	if v.Bool {
		t.Error("expected false")
	}
}

func TestParseInteger(t *testing.T) {
	v, _ := Parse("42")
	if v.Integer != 42 {
		t.Errorf("expected 42, got %d", v.Integer)
	}
	v, _ = Parse("-17")
	if v.Integer != -17 {
		t.Errorf("expected -17, got %d", v.Integer)
	}
}

func TestParseFloat(t *testing.T) {
	v, _ := Parse("3.14")
	if v.Float != 3.14 {
		t.Errorf("expected 3.14, got %f", v.Float)
	}
}

func TestParseString(t *testing.T) {
	v, _ := Parse(`"hello"`)
	if v.Str != "hello" {
		t.Errorf("expected hello, got %s", v.Str)
	}
}

func TestParseArray(t *testing.T) {
	v, _ := Parse("[1, 2, 3]")
	if len(v.Array) != 3 {
		t.Errorf("expected 3 elements, got %d", len(v.Array))
	}
}

func TestParseObject(t *testing.T) {
	v, _ := Parse(`{"a": 1, "b": "hello"}`)
	if v.Map["a"].Integer != 1 {
		t.Error("expected a=1")
	}
	if v.Map["b"].Str != "hello" {
		t.Error("expected b=hello")
	}
}

func TestSerialize(t *testing.T) {
	v := serde.Map(map[string]*serde.Value{
		"a": serde.Integer(1),
	})
	s := ToString(v)
	if s != `{"a":1}` {
		t.Errorf("expected {\"a\":1}, got %s", s)
	}
}

func TestRoundtrip(t *testing.T) {
	input := `{"name":"test","values":[1,2,3],"flag":true}`
	v, err := Parse(input)
	if err != nil {
		t.Fatal(err)
	}
	output := ToString(v)
	v2, err := Parse(output)
	if err != nil {
		t.Fatal(err)
	}
	if v2.Map["name"].Str != "test" {
		t.Error("roundtrip failed for name")
	}
	if len(v2.Map["values"].Array) != 3 {
		t.Error("roundtrip failed for values")
	}
}

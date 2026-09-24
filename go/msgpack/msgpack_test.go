package msgpack

import (
	"testing"

	serde "github.com/codinglombok/LombokSerde/go"
)

func TestRoundtripNull(t *testing.T) {
	data := Encode(serde.Null())
	v, err := Decode(data)
	if err != nil {
		t.Fatal(err)
	}
	if v.Kind != serde.KindNull {
		t.Error("expected null")
	}
}

func TestRoundtripBool(t *testing.T) {
	data := Encode(serde.Bool(true))
	v, _ := Decode(data)
	if !v.Bool {
		t.Error("expected true")
	}

	data = Encode(serde.Bool(false))
	v, _ = Decode(data)
	if v.Bool {
		t.Error("expected false")
	}
}

func TestRoundtripInteger(t *testing.T) {
	tests := []int64{0, 1, 42, 127, 128, 255, 256, 1000, 100000, -1, -32, -33, -128, -129}
	for _, n := range tests {
		data := Encode(serde.Integer(n))
		v, err := Decode(data)
		if err != nil {
			t.Fatalf("decode failed for %d: %v", n, err)
		}
		if v.Integer != n {
			t.Errorf("expected %d, got %d", n, v.Integer)
		}
	}
}

func TestRoundtripString(t *testing.T) {
	data := Encode(serde.String("hello"))
	v, _ := Decode(data)
	if v.Str != "hello" {
		t.Errorf("expected hello, got %s", v.Str)
	}
}

func TestRoundtripArray(t *testing.T) {
	arr := serde.Array(serde.Integer(1), serde.Integer(2), serde.Integer(3))
	data := Encode(arr)
	v, _ := Decode(data)
	if len(v.Array) != 3 {
		t.Errorf("expected 3, got %d", len(v.Array))
	}
}

func TestRoundtripMap(t *testing.T) {
	m := serde.Map(map[string]*serde.Value{
		"a": serde.Integer(1),
		"b": serde.String("hello"),
	})
	data := Encode(m)
	v, _ := Decode(data)
	if v.Map["a"].Integer != 1 {
		t.Error("expected a=1")
	}
	if v.Map["b"].Str != "hello" {
		t.Error("expected b=hello")
	}
}

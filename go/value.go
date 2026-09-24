package lombokserde

// ValueKind identifies the type of a Value.
type ValueKind int

const (
	KindNull ValueKind = iota
	KindBool
	KindInteger
	KindFloat
	KindString
	KindArray
	KindMap
	KindBytes
	KindDateTime
)

// DateTimeKind identifies datetime subtypes.
type DateTimeKind int

const (
	DTOffset        DateTimeKind = iota
	DTLocalDateTime
	DTLocalDate
	DTLocalTime
)

// DateTime represents a TOML datetime value.
type DateTime struct {
	Kind  DateTimeKind
	Value string
}

// Value represents a generic serialization value.
type Value struct {
	Kind     ValueKind
	Bool     bool
	Integer  int64
	Float    float64
	Str      string
	Array    []*Value
	Map      map[string]*Value
	Bytes    []byte
	DateTime *DateTime
}

// Constructors

func Null() *Value {
	return &Value{Kind: KindNull}
}

func Bool(v bool) *Value {
	return &Value{Kind: KindBool, Bool: v}
}

func Integer(v int64) *Value {
	return &Value{Kind: KindInteger, Integer: v}
}

func Float(v float64) *Value {
	return &Value{Kind: KindFloat, Float: v}
}

func String(v string) *Value {
	return &Value{Kind: KindString, Str: v}
}

func Array(items ...*Value) *Value {
	return &Value{Kind: KindArray, Array: items}
}

func Map(m map[string]*Value) *Value {
	return &Value{Kind: KindMap, Map: m}
}

func Bytes(data []byte) *Value {
	return &Value{Kind: KindBytes, Bytes: data}
}

func DateTimeVal(kind DateTimeKind, value string) *Value {
	return &Value{Kind: KindDateTime, DateTime: &DateTime{Kind: kind, Value: value}}
}

// IsNull returns true if the value is null.
func (v *Value) IsNull() bool { return v == nil || v.Kind == KindNull }

// TypeName returns a human-readable type name.
func (v *Value) TypeName() string {
	if v == nil {
		return "null"
	}
	switch v.Kind {
	case KindNull:
		return "null"
	case KindBool:
		return "bool"
	case KindInteger:
		return "integer"
	case KindFloat:
		return "float"
	case KindString:
		return "string"
	case KindArray:
		return "array"
	case KindMap:
		return "map"
	case KindBytes:
		return "bytes"
	case KindDateTime:
		return "datetime"
	default:
		return "unknown"
	}
}

// Get retrieves a map entry by key.
func (v *Value) Get(key string) *Value {
	if v == nil || v.Kind != KindMap || v.Map == nil {
		return nil
	}
	return v.Map[key]
}

// Index retrieves an array element by index.
func (v *Value) Index(i int) *Value {
	if v == nil || v.Kind != KindArray || i < 0 || i >= len(v.Array) {
		return nil
	}
	return v.Array[i]
}

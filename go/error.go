package lombokserde

import "fmt"

// Stable error codes shared across all ports (SPEC section 6).
const (
	ErrJSONSyntax     = "SERDE_JSON_SYNTAX"
	ErrJSONUTF8       = "SERDE_JSON_UTF8"
	ErrJSONDepth      = "SERDE_JSON_DEPTH"
	ErrJSONTrailing   = "SERDE_JSON_TRAILING"
	ErrJSONIntRange   = "SERDE_JSON_INT_RANGE"
	ErrJSONFloatNaN   = "SERDE_JSON_FLOAT_NANINF"
	ErrJSONBytes      = "SERDE_JSON_BYTES"
	ErrJSONDatetime   = "SERDE_JSON_DATETIME"
	ErrTOMLSyntax     = "SERDE_TOML_SYNTAX"
	ErrTOMLUTF8       = "SERDE_TOML_UTF8"
	ErrTOMLDuplicate  = "SERDE_TOML_DUPLICATE"
	ErrTOMLDepth      = "SERDE_TOML_DEPTH"
	ErrTOMLRoot       = "SERDE_TOML_ROOT"
	ErrTOMLBytes      = "SERDE_TOML_BYTES"
	ErrTOMLDatetime   = "SERDE_TOML_DATETIME"
	ErrMPTruncated    = "SERDE_MP_TRUNCATED"
	ErrMPUnexpected   = "SERDE_MP_UNEXPECTED"
	ErrMPTrailing     = "SERDE_MP_TRAILING"
	ErrMPUTF8         = "SERDE_MP_UTF8"
	ErrMPExt          = "SERDE_MP_EXT"
	ErrMPDepth        = "SERDE_MP_DEPTH"
	ErrMPDuplicate    = "SERDE_MP_DUPLICATE"
	ErrMPDatetime     = "SERDE_MP_DATETIME"
	ErrTableDuplicate = "SERDE_TABLE_DUPLICATE"
)

// Error is the shared error type: `[CODE] message` and, with a position,
// `[CODE] message (at byte N)`.
type Error struct {
	Code    string
	Message string
	// Offset is the byte offset into the input, when one applies.
	Offset *int
}

// NewError builds an Error; offset may be nil.
func NewError(code, message string, offset *int) *Error {
	return &Error{Code: code, Message: message, Offset: offset}
}

func (e *Error) Error() string {
	if e.Offset != nil {
		return fmt.Sprintf("[%s] %s (at byte %d)", e.Code, e.Message, *e.Offset)
	}
	return fmt.Sprintf("[%s] %s", e.Code, e.Message)
}

func syntaxErr(code string, offset int, detail string) *Error {
	return NewError(code, detail, &offset)
}

package lombokserde

import "fmt"

// SerdeErrorCode represents error categories.
type SerdeErrorCode int

const (
	ErrSyntaxError   SerdeErrorCode = iota
	ErrUnexpectedEof
	ErrTypeMismatch
	ErrMissingField
	ErrUnknownField
	ErrOutOfRange
	ErrDepthExceeded
	ErrInvalidUnicode
	ErrDuplicateKey
	ErrUnsupported
	ErrCustom
)

func (c SerdeErrorCode) String() string {
	switch c {
	case ErrSyntaxError:
		return "SyntaxError"
	case ErrUnexpectedEof:
		return "UnexpectedEof"
	case ErrTypeMismatch:
		return "TypeMismatch"
	case ErrMissingField:
		return "MissingField"
	case ErrUnknownField:
		return "UnknownField"
	case ErrOutOfRange:
		return "OutOfRange"
	case ErrDepthExceeded:
		return "DepthExceeded"
	case ErrInvalidUnicode:
		return "InvalidUnicode"
	case ErrDuplicateKey:
		return "DuplicateKey"
	case ErrUnsupported:
		return "Unsupported"
	case ErrCustom:
		return "Custom"
	default:
		return "Unknown"
	}
}

// SerdeError is the error type for serialization/deserialization.
type SerdeError struct {
	Code    SerdeErrorCode
	Message string
	Line    int
	Column  int
}

func (e *SerdeError) Error() string {
	if e.Line > 0 {
		return fmt.Sprintf("%s: %s at line %d, col %d", e.Code, e.Message, e.Line, e.Column)
	}
	return fmt.Sprintf("%s: %s", e.Code, e.Message)
}

func newError(code SerdeErrorCode, msg string) *SerdeError {
	return &SerdeError{Code: code, Message: msg}
}

func newErrorAt(code SerdeErrorCode, msg string, line, col int) *SerdeError {
	return &SerdeError{Code: code, Message: msg, Line: line, Column: col}
}

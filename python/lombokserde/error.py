"""Serde error types."""

from enum import Enum
from typing import Optional


class SerdeErrorCode(Enum):
    SYNTAX_ERROR = "SyntaxError"
    UNEXPECTED_EOF = "UnexpectedEof"
    TYPE_MISMATCH = "TypeMismatch"
    MISSING_FIELD = "MissingField"
    UNKNOWN_FIELD = "UnknownField"
    OUT_OF_RANGE = "OutOfRange"
    DEPTH_EXCEEDED = "DepthExceeded"
    INVALID_UNICODE = "InvalidUnicode"
    DUPLICATE_KEY = "DuplicateKey"
    UNSUPPORTED = "Unsupported"
    CUSTOM = "Custom"


class SerdeError(Exception):
    def __init__(
        self,
        code: SerdeErrorCode,
        message: str,
        line: Optional[int] = None,
        column: Optional[int] = None,
    ):
        self.code = code
        self.message = message
        self.line = line
        self.column = column
        if line is not None and column is not None:
            super().__init__(f"{code.value}: {message} at line {line}, col {column}")
        else:
            super().__init__(f"{code.value}: {message}")

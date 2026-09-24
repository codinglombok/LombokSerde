/**
 * Error codes for LombokSerde operations.
 */
export enum SerdeErrorCode {
  SyntaxError = 'SYNTAX_ERROR',
  UnexpectedEof = 'UNEXPECTED_EOF',
  TypeMismatch = 'TYPE_MISMATCH',
  MissingField = 'MISSING_FIELD',
  OutOfRange = 'OUT_OF_RANGE',
  DepthExceeded = 'DEPTH_EXCEEDED',
  InvalidUnicode = 'INVALID_UNICODE',
  DuplicateKey = 'DUPLICATE_KEY',
  Unsupported = 'UNSUPPORTED',
}

/**
 * Error class for serialization/deserialization failures.
 */
export class SerdeError extends Error {
  readonly code: SerdeErrorCode;
  readonly line?: number;
  readonly column?: number;

  constructor(code: SerdeErrorCode, message: string, line?: number, column?: number) {
    super(message);
    this.name = 'SerdeError';
    this.code = code;
    this.line = line;
    this.column = column;
  }
}

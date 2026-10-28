/** Error type shared by every LombokSerde port (SPEC section 6). */
export class SerdeError extends Error {
  /** Stable error code, e.g. `SERDE_JSON_SYNTAX`. */
  readonly code: string;
  /** Byte offset into the input when a position applies. */
  readonly offset: number | null;

  constructor(code: string, message: string, offset: number | null) {
    super(
      offset === null ? `[${code}] ${message}` : `[${code}] ${message} (at byte ${offset})`,
    );
    this.name = 'SerdeError';
    this.code = code;
    this.offset = offset;
  }
}

export function syntaxErr(
  code: string,
  offset: number,
  detail: string,
): SerdeError {
  return new SerdeError(code, detail, offset);
}

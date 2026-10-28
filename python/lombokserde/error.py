"""Error type shared by every LombokSerde port (SPEC section 6)."""

from __future__ import annotations


class SerdeError(Exception):
    """`[CODE] message` and, with a position, `[CODE] message (at byte N)`.

    ``code`` is one of the stable ``SERDE_*`` codes listed in the SPEC;
    ``offset`` is the byte offset into the input when one applies.
    """

    def __init__(self, code: str, message: str, offset: int | None) -> None:
        self.code = code
        self.message = message
        self.offset = offset
        if offset is None:
            super().__init__(f"[{code}] {message}")
        else:
            super().__init__(f"[{code}] {message} (at byte {offset})")


def syntax_err(code: str, offset: int, detail: str) -> SerdeError:
    return SerdeError(code, detail, offset)

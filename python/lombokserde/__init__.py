"""LombokSerde — zero-dependency serialization with byte-identical
behavior across languages: JSON (RFC 8259), TOML (v1.0), MessagePack.

The Python port consumes the shared deterministic vectors in
vectors/lombokserde-vectors-v1.json. See docs/SPEC_LombokSerde_v0.1.0.md
for the normative specification.
"""

from ._json import JsonOptions, json_decode, json_encode
from ._msgpack import MsgPackOptions, msgpack_decode, msgpack_encode
from ._toml import TomlOptions, toml_decode, toml_encode
from .error import SerdeError
from .value import (
    DEFAULT_DEPTH_LIMIT,
    Datetime,
    DatetimeKind,
    Value,
    make_table,
    table_get,
)

__version__ = "0.1.0"

__all__ = [
    "SerdeError",
    "Value",
    "Datetime",
    "DatetimeKind",
    "make_table",
    "table_get",
    "JsonOptions",
    "json_decode",
    "json_encode",
    "TomlOptions",
    "toml_decode",
    "toml_encode",
    "MsgPackOptions",
    "msgpack_decode",
    "msgpack_encode",
    "DEFAULT_DEPTH_LIMIT",
]

/** LombokSerde — zero-dependency serialization with byte-identical
 * behavior across languages: JSON (RFC 8259), TOML (v1.0), MessagePack.
 *
 * The TypeScript port is the npm publication path of the Lombok Ecosystem
 * contract; it must pass the shared deterministic vectors in
 * vectors/lombokserde-vectors-v1.json bit-identically. See
 * docs/SPEC_LombokSerde_v0.1.0.md for the normative specification.
 */

export { SerdeError } from './error.js';
export type { JsonOptions } from './json.js';
export { jsonDecode, jsonEncode, jsonEncodeText } from './json.js';
export type { TomlOptions } from './toml.js';
export { tomlDecode, tomlEncode, tomlEncodeText } from './toml.js';
export type { MsgPackOptions } from './msgpack.js';
export { msgpackDecode, msgpackEncode } from './msgpack.js';
export {
  DEFAULT_DEPTH_LIMIT,
  makeTable,
  tableGet,
  tableUnchecked,
} from './value.js';
export type { Datetime, DatetimeKind, Value } from './value.js';

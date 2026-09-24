/**
 * Value intermediate representation.
 */

export type DateTimeKind = 'offset' | 'local-datetime' | 'local-date' | 'local-time';

export interface DateTimeValue {
  kind: DateTimeKind;
  value: string;
}

/** Universal intermediate representation for serialized data. */
export type Value =
  | null
  | boolean
  | number
  | string
  | Value[]
  | { [key: string]: Value }
  | Uint8Array
  | DateTimeValue;

/** Check if value is a DateTimeValue. */
export function isDateTime(v: Value): v is DateTimeValue {
  return v !== null && typeof v === 'object' && !Array.isArray(v) && !(v instanceof Uint8Array) && 'kind' in v && 'value' in v;
}

/** Check if value is a map (plain object, not bytes or datetime). */
export function isMap(v: Value): v is { [key: string]: Value } {
  return v !== null && typeof v === 'object' && !Array.isArray(v) && !(v instanceof Uint8Array) && !isDateTime(v);
}

/** Get the type name of a Value. */
export function typeName(v: Value): string {
  if (v === null) return 'null';
  if (typeof v === 'boolean') return 'bool';
  if (typeof v === 'number') return Number.isInteger(v) ? 'integer' : 'float';
  if (typeof v === 'string') return 'string';
  if (Array.isArray(v)) return 'array';
  if (v instanceof Uint8Array) return 'bytes';
  if (isDateTime(v)) return 'datetime';
  return 'map';
}

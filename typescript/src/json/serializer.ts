/**
 * JSON serializer — compact and pretty-print.
 */

import { Value, isDateTime, isMap } from '../value.js';

/** Serialize a Value to a compact JSON string. */
export function stringify(value: Value): string {
  return writeValue(value);
}

/** Serialize a Value to a pretty-printed JSON string. */
export function stringifyPretty(value: Value, indent = 2): string {
  return writeValuePretty(value, 0, indent) + '\n';
}

function writeValue(value: Value): string {
  if (value === null) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return writeNumber(value);
  if (typeof value === 'string') return writeString(value);
  if (Array.isArray(value)) {
    return '[' + value.map(v => writeValue(v)).join(',') + ']';
  }
  if (value instanceof Uint8Array) {
    return '[' + Array.from(value).join(',') + ']';
  }
  if (isDateTime(value)) {
    return writeString(value.value);
  }
  // Map
  const entries = Object.entries(value);
  return '{' + entries.map(([k, v]) => writeString(k) + ':' + writeValue(v)).join(',') + '}';
}

function writeValuePretty(value: Value, level: number, indent: number): string {
  if (value === null) return 'null';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return writeNumber(value);
  if (typeof value === 'string') return writeString(value);

  const pad = ' '.repeat((level + 1) * indent);
  const closePad = ' '.repeat(level * indent);

  if (Array.isArray(value)) {
    if (value.length === 0) return '[]';
    const items = value.map(v => pad + writeValuePretty(v, level + 1, indent));
    return '[\n' + items.join(',\n') + '\n' + closePad + ']';
  }
  if (value instanceof Uint8Array) {
    return '[' + Array.from(value).join(',') + ']';
  }
  if (isDateTime(value)) {
    return writeString(value.value);
  }

  const entries = Object.entries(value);
  if (entries.length === 0) return '{}';
  const items = entries.map(([k, v]) =>
    pad + writeString(k) + ': ' + writeValuePretty(v, level + 1, indent)
  );
  return '{\n' + items.join(',\n') + '\n' + closePad + '}';
}

function writeNumber(n: number): string {
  if (!isFinite(n)) return 'null';
  const s = String(n);
  return s;
}

function writeString(s: string): string {
  let out = '"';
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    const code = s.charCodeAt(i);
    switch (ch) {
      case '"': out += '\\"'; break;
      case '\\': out += '\\\\'; break;
      case '\b': out += '\\b'; break;
      case '\f': out += '\\f'; break;
      case '\n': out += '\\n'; break;
      case '\r': out += '\\r'; break;
      case '\t': out += '\\t'; break;
      default:
        if (code < 0x20) {
          out += '\\u' + code.toString(16).padStart(4, '0');
        } else {
          out += ch;
        }
    }
  }
  return out + '"';
}

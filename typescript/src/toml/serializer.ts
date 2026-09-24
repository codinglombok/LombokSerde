/**
 * TOML serializer — outputs normalized TOML v1.0.
 */

import type { Value } from '../value.js';
import { isDateTime, isMap } from '../value.js';

/** Serialize a Value (object) to a TOML string. */
export function stringify(value: { [key: string]: Value }): string {
  let out = '';
  out = writeTable(value, [], out);
  return out;
}

function writeTable(map: { [key: string]: Value }, path: string[], out: string): string {
  // Simple key-value pairs first
  for (const [key, value] of Object.entries(map)) {
    if (!isTableOrArrayOfTables(value)) {
      out += writeKey(key) + ' = ' + writeValue(value) + '\n';
    }
  }

  // Sub-tables
  for (const [key, value] of Object.entries(map)) {
    if (isMap(value) && !isInlineTable(value)) {
      const newPath = [...path, key];
      out += '\n[' + newPath.map(writeKey).join('.') + ']\n';
      out = writeTable(value as { [key: string]: Value }, newPath, out);
    } else if (Array.isArray(value) && isArrayOfTables(value)) {
      const newPath = [...path, key];
      for (const item of value) {
        if (isMap(item)) {
          out += '\n[[' + newPath.map(writeKey).join('.') + ']]\n';
          out = writeTable(item as { [key: string]: Value }, newPath, out);
        }
      }
    }
  }

  return out;
}

function isTableOrArrayOfTables(value: Value): boolean {
  if (isMap(value) && !isInlineTable(value as { [key: string]: Value })) return true;
  if (Array.isArray(value) && isArrayOfTables(value)) return true;
  return false;
}

function isInlineTable(map: { [key: string]: Value }): boolean {
  const entries = Object.entries(map);
  if (entries.length > 4) return false;
  return entries.every(([_, v]) =>
    v === null || typeof v === 'boolean' || typeof v === 'number' ||
    typeof v === 'string' || v instanceof Uint8Array || isDateTime(v)
  );
}

function isArrayOfTables(arr: Value[]): boolean {
  return arr.length > 0 && arr.every(v => isMap(v));
}

function writeKey(key: string): string {
  if (isBareKey(key)) return key;
  return writeBasicString(key);
}

function isBareKey(key: string): boolean {
  return key.length > 0 && /^[A-Za-z0-9_-]+$/.test(key);
}

function writeValue(value: Value): string {
  if (value === null) return '"null"';
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') {
    if (isNaN(value)) return 'nan';
    if (!isFinite(value)) return value < 0 ? '-inf' : 'inf';
    const s = String(value);
    if (!s.includes('.') && !s.includes('e') && !s.includes('E')) return s + '.0';
    return s;
  }
  if (typeof value === 'string') return writeBasicString(value);
  if (value instanceof Uint8Array) {
    return '[' + Array.from(value).join(', ') + ']';
  }
  if (isDateTime(value)) return value.value;
  if (Array.isArray(value)) {
    return '[' + value.map(writeValue).join(', ') + ']';
  }
  // Inline table
  const entries = Object.entries(value);
  return '{' + entries.map(([k, v]) => writeKey(k) + ' = ' + writeValue(v)).join(', ') + '}';
}

function writeBasicString(s: string): string {
  let out = '"';
  for (const ch of s) {
    switch (ch) {
      case '"': out += '\\"'; break;
      case '\\': out += '\\\\'; break;
      case '\b': out += '\\b'; break;
      case '\t': out += '\\t'; break;
      case '\n': out += '\\n'; break;
      case '\f': out += '\\f'; break;
      case '\r': out += '\\r'; break;
      default:
        if (ch.charCodeAt(0) < 0x20) {
          out += '\\u' + ch.charCodeAt(0).toString(16).padStart(4, '0').toUpperCase();
        } else {
          out += ch;
        }
    }
  }
  return out + '"';
}

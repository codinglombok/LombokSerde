/**
 * MessagePack encoder.
 */

import type { Value } from '../value.js';
import { isDateTime, isMap } from '../value.js';

/** Encode a Value to MessagePack bytes. */
export function encode(value: Value): Uint8Array {
  const parts: number[] = [];
  encodeValue(value, parts);
  return new Uint8Array(parts);
}

function encodeValue(value: Value, buf: number[]): void {
  if (value === null) { buf.push(0xC0); return; }
  if (typeof value === 'boolean') { buf.push(value ? 0xC3 : 0xC2); return; }
  if (typeof value === 'number') {
    if (Number.isInteger(value) && value >= -2147483648 && value <= 2147483647) {
      encodeInteger(value, buf);
    } else {
      encodeFloat64(value, buf);
    }
    return;
  }
  if (typeof value === 'string') { encodeString(value, buf); return; }
  if (value instanceof Uint8Array) { encodeBin(value, buf); return; }
  if (isDateTime(value)) { encodeString(value.value, buf); return; }
  if (Array.isArray(value)) { encodeArray(value, buf); return; }
  // Map
  encodeMap(value as { [key: string]: Value }, buf);
}

function encodeInteger(n: number, buf: number[]): void {
  if (n >= 0) {
    if (n <= 127) {
      buf.push(n);
    } else if (n <= 0xFF) {
      buf.push(0xCC, n);
    } else if (n <= 0xFFFF) {
      buf.push(0xCD, (n >> 8) & 0xFF, n & 0xFF);
    } else {
      buf.push(0xCE,
        (n >>> 24) & 0xFF, (n >>> 16) & 0xFF,
        (n >>> 8) & 0xFF, n & 0xFF);
    }
  } else {
    if (n >= -32) {
      buf.push(n & 0xFF);
    } else if (n >= -128) {
      buf.push(0xD0, n & 0xFF);
    } else if (n >= -32768) {
      buf.push(0xD1, (n >> 8) & 0xFF, n & 0xFF);
    } else {
      buf.push(0xD2,
        (n >> 24) & 0xFF, (n >> 16) & 0xFF,
        (n >> 8) & 0xFF, n & 0xFF);
    }
  }
}

function encodeFloat64(f: number, buf: number[]): void {
  buf.push(0xCB);
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, f);
  for (let i = 0; i < 8; i++) buf.push(view.getUint8(i));
}

function encodeString(s: string, buf: number[]): void {
  const bytes = new TextEncoder().encode(s);
  const len = bytes.length;
  if (len <= 31) {
    buf.push(0xA0 | len);
  } else if (len <= 0xFF) {
    buf.push(0xD9, len);
  } else if (len <= 0xFFFF) {
    buf.push(0xDA, (len >> 8) & 0xFF, len & 0xFF);
  } else {
    buf.push(0xDB, (len >>> 24) & 0xFF, (len >>> 16) & 0xFF, (len >>> 8) & 0xFF, len & 0xFF);
  }
  for (const b of bytes) buf.push(b);
}

function encodeBin(data: Uint8Array, buf: number[]): void {
  const len = data.length;
  if (len <= 0xFF) {
    buf.push(0xC4, len);
  } else if (len <= 0xFFFF) {
    buf.push(0xC5, (len >> 8) & 0xFF, len & 0xFF);
  } else {
    buf.push(0xC6, (len >>> 24) & 0xFF, (len >>> 16) & 0xFF, (len >>> 8) & 0xFF, len & 0xFF);
  }
  for (const b of data) buf.push(b);
}

function encodeArray(arr: Value[], buf: number[]): void {
  const len = arr.length;
  if (len <= 15) {
    buf.push(0x90 | len);
  } else if (len <= 0xFFFF) {
    buf.push(0xDC, (len >> 8) & 0xFF, len & 0xFF);
  } else {
    buf.push(0xDD, (len >>> 24) & 0xFF, (len >>> 16) & 0xFF, (len >>> 8) & 0xFF, len & 0xFF);
  }
  for (const v of arr) encodeValue(v, buf);
}

function encodeMap(map: { [key: string]: Value }, buf: number[]): void {
  const entries = Object.entries(map);
  const len = entries.length;
  if (len <= 15) {
    buf.push(0x80 | len);
  } else if (len <= 0xFFFF) {
    buf.push(0xDE, (len >> 8) & 0xFF, len & 0xFF);
  } else {
    buf.push(0xDF, (len >>> 24) & 0xFF, (len >>> 16) & 0xFF, (len >>> 8) & 0xFF, len & 0xFF);
  }
  for (const [k, v] of entries) {
    encodeString(k, buf);
    encodeValue(v, buf);
  }
}

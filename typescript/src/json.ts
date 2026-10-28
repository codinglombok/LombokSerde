/** JSON codec (RFC 8259) — canonical, byte-precise (see SPEC). */

import { SerdeError, syntaxErr } from './error.js';
import { renderFloat } from './float.js';
import {
  DEFAULT_DEPTH_LIMIT,
  INT64_MAX,
  INT64_MIN,
  UINT64_MAX,
  makeTable,
  tableUnchecked,
  type Value,
} from './value.js';

const E_SYNTAX = 'SERDE_JSON_SYNTAX';
const E_UTF8 = 'SERDE_JSON_UTF8';
const E_DEPTH = 'SERDE_JSON_DEPTH';
const E_TRAILING = 'SERDE_JSON_TRAILING';
const E_INT_RANGE = 'SERDE_JSON_INT_RANGE';
const E_FLOAT_NANINF = 'SERDE_JSON_FLOAT_NANINF';
const E_BYTES = 'SERDE_JSON_BYTES';
const E_DATETIME = 'SERDE_JSON_DATETIME';

/** Options for the JSON codec. */
export interface JsonOptions {
  /** Maximum container nesting; the outermost container is depth 1. */
  readonly depthLimit?: number;
}


function depthOf(opts?: JsonOptions): number {
  return opts?.depthLimit ?? DEFAULT_DEPTH_LIMIT;
}

/** Decode exactly one JSON value; trailing non-whitespace is an error. */
export function jsonDecode(data: Uint8Array, opts?: JsonOptions): Value {
  const bad = utf8FirstBadOffset(data);
  if (bad !== -1) {
    throw syntaxErr(E_UTF8, bad, 'invalid UTF-8');
  }
  const p = new Parser(data, depthOf(opts));
  const v = p.parseValue(1);
  p.skipWs();
  if (p.i !== data.length) {
    throw syntaxErr(
      E_TRAILING,
      p.i,
      'trailing characters after the top-level value',
    );
  }
  return v;
}

/** Encode a value as canonical compact JSON (UTF-8 bytes). */
export function jsonEncode(v: Value, opts?: JsonOptions): Uint8Array {
  const out: string[] = [];
  writeValue(out, v, 1, depthOf(opts));
  return new TextEncoder().encode(out.join(''));
}

/** Encode a value as canonical compact JSON text (same bytes, as a string). */
export function jsonEncodeText(v: Value, opts?: JsonOptions): string {
  const out: string[] = [];
  writeValue(out, v, 1, depthOf(opts));
  return out.join('');
}

class Parser {
  private b: Uint8Array;
  i: number;
  private limit: number;

  constructor(b: Uint8Array, limit: number) {
    this.b = b;
    this.i = 0;
    this.limit = limit;
  }

  skipWs(): void {
    while (
      this.i < this.b.length &&
      (this.b[this.i] === 0x20 ||
        this.b[this.i] === 0x09 ||
        this.b[this.i] === 0x0a ||
        this.b[this.i] === 0x0d)
    ) {
      this.i++;
    }
  }

  private fail(detail: string): SerdeError {
    return syntaxErr(E_SYNTAX, this.i, detail);
  }

  parseValue(depth: number): Value {
    this.skipWs();
    if (this.i >= this.b.length) {
      throw this.fail('unexpected end of input');
    }
    const c = this.b[this.i];
    if (c === 0x7b) {
      if (depth > this.limit) {
        throw syntaxErr(E_DEPTH, this.i, 'depth limit exceeded');
      }
      return this.parseObject(depth);
    }
    if (c === 0x5b) {
      if (depth > this.limit) {
        throw syntaxErr(E_DEPTH, this.i, 'depth limit exceeded');
      }
      return this.parseArray(depth);
    }
    if (c === 0x22) {
      return { t: 'str', v: this.parseString() };
    }
    if (c === 0x74) {
      this.expect('true');
      return { t: 'bool', v: true };
    }
    if (c === 0x66) {
      this.expect('false');
      return { t: 'bool', v: false };
    }
    if (c === 0x6e) {
      this.expect('null');
      return null;
    }
    if (c === 0x2d || (c >= 0x30 && c <= 0x39)) {
      return this.parseNumber();
    }
    throw this.fail('unexpected character');
  }

  private expect(word: string): void {
    const w = new TextEncoder().encode(word);
    if (this.b.length - this.i < w.length) {
      throw this.fail('invalid literal');
    }
    for (let i = 0; i < w.length; i++) {
      if (this.b[this.i + i] !== w[i]) {
        throw this.fail('invalid literal');
      }
    }
    this.i += w.length;
  }

  private parseObject(depth: number): Value {
    this.i++; // {
    const pairs: Array<[string, Value]> = [];
    this.skipWs();
    if (this.i < this.b.length && this.b[this.i] === 0x7d) {
      this.i++;
      return tableUnchecked(pairs);
    }
    for (;;) {
      this.skipWs();
      if (this.i >= this.b.length || this.b[this.i] !== 0x22) {
        throw this.fail('expected object key');
      }
      const k = this.parseString();
      this.skipWs();
      if (this.i >= this.b.length || this.b[this.i] !== 0x3a) {
        throw this.fail("expected ':'");
      }
      this.i++;
      const v = this.parseValue(depth + 1);
      pairs.push([k, v]);
      this.skipWs();
      if (this.i >= this.b.length) {
        throw this.fail('unterminated object');
      }
      const c = this.b[this.i];
      if (c === 0x2c) {
        this.i++;
        continue;
      }
      if (c === 0x7d) {
        this.i++;
        return makeTable(pairs, () =>
          syntaxErr(E_SYNTAX, this.i, 'duplicate object key'),
        );
      }
      throw this.fail("expected ',' or '}'");
    }
  }

  private parseArray(depth: number): Value {
    this.i++; // [
    const items: Value[] = [];
    this.skipWs();
    if (this.i < this.b.length && this.b[this.i] === 0x5d) {
      this.i++;
      return { t: 'array', v: items };
    }
    for (;;) {
      items.push(this.parseValue(depth + 1));
      this.skipWs();
      if (this.i >= this.b.length) {
        throw this.fail('unterminated array');
      }
      const c = this.b[this.i];
      if (c === 0x2c) {
        this.i++;
        continue;
      }
      if (c === 0x5d) {
        this.i++;
        return { t: 'array', v: items };
      }
      throw this.fail("expected ',' or ']'");
    }
  }

  private parseString(): string {
    this.i++; // opening quote
    let out = '';
    for (;;) {
      if (this.i >= this.b.length) {
        throw this.fail('unterminated string');
      }
      const c = this.b[this.i];
      if (c === 0x22) {
        this.i++;
        return out;
      }
      if (c === 0x5c) {
        this.i++;
        if (this.i >= this.b.length) {
          throw this.fail('unterminated escape');
        }
        const e = this.b[this.i];
        switch (e) {
          case 0x22:
            out += '"';
            this.i++;
            break;
          case 0x5c:
            out += '\\';
            this.i++;
            break;
          case 0x2f:
            out += '/';
            this.i++;
            break;
          case 0x62:
            out += '\b';
            this.i++;
            break;
          case 0x66:
            out += '\f';
            this.i++;
            break;
          case 0x6e:
            out += '\n';
            this.i++;
            break;
          case 0x72:
            out += '\r';
            this.i++;
            break;
          case 0x74:
            out += '\t';
            this.i++;
            break;
          case 0x75: {
            const cp = this.parseHex4();
            if (cp >= 0xd800 && cp <= 0xdbff) {
              // after parseHex4 the cursor sits on the next char: a trailing
              // pair escape starts here
              if (
                this.i + 1 < this.b.length &&
                this.b[this.i] === 0x5c &&
                this.b[this.i + 1] === 0x75
              ) {
                this.i += 1; // land on the 'u' of the low escape
                const lo = this.parseHex4();
                if (lo >= 0xdc00 && lo <= 0xdfff) {
                  const cc = 0x10000 + ((cp - 0xd800) << 10) + (lo - 0xdc00);
                  out += String.fromCodePoint(cc);
                } else {
                  throw this.fail('invalid low surrogate');
                }
              } else {
                throw this.fail('lone high surrogate');
              }
            } else if (cp >= 0xdc00 && cp <= 0xdfff) {
              throw this.fail('lone low surrogate');
            } else {
              out += String.fromCodePoint(cp);
            }
            break;
          }
          default:
            throw this.fail('invalid escape');
        }
        continue;
      }
      if (c < 0x20) {
        throw this.fail('raw control character in string');
      }
      // consume one UTF-8 code point (input is pre-validated)
      const n = c < 0x80 ? 1 : c < 0xe0 ? 2 : c < 0xf0 ? 3 : 4;
      const cp =
        n === 1
          ? c
          : n === 2
            ? ((c & 0x1f) << 6) | (this.b[this.i + 1] & 0x3f)
            : n === 3
              ? ((c & 0x0f) << 12) |
                ((this.b[this.i + 1] & 0x3f) << 6) |
                (this.b[this.i + 2] & 0x3f)
              : ((c & 0x07) << 18) |
                ((this.b[this.i + 1] & 0x3f) << 12) |
                ((this.b[this.i + 2] & 0x3f) << 6) |
                (this.b[this.i + 3] & 0x3f);
      out += String.fromCodePoint(cp);
      this.i += n;
    }
  }

  private parseHex4(): number {
    // defensive: callers only enter after seeing the 'u' marker
    /* v8 ignore next 3 */
    if (this.i >= this.b.length || this.b[this.i] !== 0x75) {
      throw this.fail('expected \\u');
    }
    if (this.i + 4 >= this.b.length) {
      throw this.fail('truncated \\u escape');
    }
    const h = String.fromCharCode(...this.b.subarray(this.i + 1, this.i + 5));
    if (!/^[0-9a-fA-F]{4}$/.test(h)) {
      throw this.fail('invalid \\u escape');
    }
    const cp = parseInt(h, 16);
    this.i += 5;
    return cp;
  }

  private parseNumber(): Value {
    const start = this.i;
    const b = this.b;
    if (b[this.i] === 0x2d) {
      this.i++;
      if (this.i >= b.length) {
        throw this.fail('unexpected end of input');
      }
    }
    if (b[this.i] === 0x30) {
      this.i++;
    } else if (b[this.i] >= 0x31 && b[this.i] <= 0x39) {
      while (this.i < b.length && b[this.i] >= 0x30 && b[this.i] <= 0x39) {
        this.i++;
      }
    } else {
      throw this.fail('invalid number');
    }
    let isFloat = false;
    if (this.i < b.length && b[this.i] === 0x2e) {
      isFloat = true;
      this.i++;
      if (this.i >= b.length || b[this.i] < 0x30 || b[this.i] > 0x39) {
        throw this.fail("expected digit after '.'");
      }
      while (this.i < b.length && b[this.i] >= 0x30 && b[this.i] <= 0x39) {
        this.i++;
      }
    }
    if (this.i < b.length && (b[this.i] === 0x65 || b[this.i] === 0x45)) {
      isFloat = true;
      this.i++;
      if (this.i < b.length && (b[this.i] === 0x2b || b[this.i] === 0x2d)) {
        this.i++;
      }
      if (this.i >= b.length || b[this.i] < 0x30 || b[this.i] > 0x39) {
        throw this.fail('expected digit in exponent');
      }
      while (this.i < b.length && b[this.i] >= 0x30 && b[this.i] <= 0x39) {
        this.i++;
      }
    }
    const text = String.fromCharCode(...b.subarray(start, this.i));
    if (!isFloat) {
      const n = BigInt(text);
      if (n >= INT64_MIN && n <= INT64_MAX) {
        return { t: 'int', v: n };
      }
      if (n >= 0n && n <= UINT64_MAX) {
        return { t: 'uint', v: n };
      }
      throw syntaxErr(E_INT_RANGE, start, 'integer out of 64-bit range');
    }
    return { t: 'float', v: Number(text) };
  }
}

function writeValue(
  out: string[],
  v: Value,
  depth: number,
  limit: number,
): void {
  if (v === null) {
    out.push('null');
  } else if (v.t === 'bool') {
    out.push(v.v ? 'true' : 'false');
  } else if (v.t === 'int' || v.t === 'uint') {
    out.push(v.v.toString());
  } else if (v.t === 'float') {
    const f = v.v;
    if (Number.isNaN(f) || !Number.isFinite(f)) {
      throw new SerdeError(
        E_FLOAT_NANINF,
        'non-finite float is not valid JSON',
        null,
      );
    }
    out.push(renderFloat(f));
  } else if (v.t === 'str') {
    writeJsonString(out, v.v);
  } else if (v.t === 'bytes') {
    throw new SerdeError(
      E_BYTES,
      'Bytes values cannot be encoded as JSON',
      null,
    );
  } else if (v.t === 'datetime') {
    throw new SerdeError(
      E_DATETIME,
      'Datetime values cannot be encoded as JSON',
      null,
    );
  } else if (v.t === 'array') {
    if (depth > limit) {
      throw new SerdeError(E_DEPTH, 'depth limit exceeded', null);
    }
    out.push('[');
    for (let i = 0; i < v.v.length; i++) {
      if (i > 0) {
        out.push(',');
      }
      writeValue(out, v.v[i], depth + 1, limit);
    }
    out.push(']');
  } else {
    if (depth > limit) {
      throw new SerdeError(E_DEPTH, 'depth limit exceeded', null);
    }
    out.push('{');
    for (let i = 0; i < v.v.length; i++) {
      if (i > 0) {
        out.push(',');
      }
      writeJsonString(out, v.v[i][0]);
      out.push(':');
      writeValue(out, v.v[i][1], depth + 1, limit);
    }
    out.push('}');
  }
}

function writeJsonString(out: string[], s: string): void {
  out.push('"');
  for (const ch of s) {
    const o = ch.codePointAt(0) as number;
    if (ch === '"') {
      out.push('\\"');
    } else if (ch === '\\') {
      out.push('\\\\');
    } else if (o === 0x08) {
      out.push('\\b');
    } else if (o === 0x09) {
      out.push('\\t');
    } else if (o === 0x0a) {
      out.push('\\n');
    } else if (o === 0x0c) {
      out.push('\\f');
    } else if (o === 0x0d) {
      out.push('\\r');
    } else if (o < 0x20) {
      out.push(`\\u${o.toString(16).padStart(4, '0')}`);
    } else {
      out.push(ch);
    }
  }
  out.push('"');
}

/** Byte-precise UTF-8 validation; returns the first bad offset or -1. */
export function utf8FirstBadOffset(b: Uint8Array): number {
  let i = 0;
  const n = b.length;
  while (i < n) {
    const c = b[i];
    if (c < 0x80) {
      i++;
      continue;
    }
    let len: number;
    let lower: number;
    let upper: number;
    if (c >= 0xc2 && c <= 0xdf) {
      len = 2;
      lower = 0x80;
      upper = 0xbf;
    } else if (c === 0xe0) {
      len = 3;
      lower = 0xa0;
      upper = 0xbf;
    } else if (c >= 0xe1 && c <= 0xec) {
      len = 3;
      lower = 0x80;
      upper = 0xbf;
    } else if (c === 0xed) {
      len = 3;
      lower = 0x80;
      upper = 0x9f;
    } else if (c >= 0xee && c <= 0xef) {
      len = 3;
      lower = 0x80;
      upper = 0xbf;
    } else if (c === 0xf0) {
      len = 4;
      lower = 0x90;
      upper = 0xbf;
    } else if (c >= 0xf1 && c <= 0xf3) {
      len = 4;
      lower = 0x80;
      upper = 0xbf;
    } else if (c === 0xf4) {
      len = 4;
      lower = 0x80;
      upper = 0x8f;
    } else {
      return i;
    }
    if (i + len > n) {
      return i;
    }
    for (let j = 1; j < len; j++) {
      const cc = b[i + j];
      const bound = j === 1 ? { lower, upper } : { lower: 0x80, upper: 0xbf };
      if (cc < bound.lower || cc > bound.upper) {
        return i;
      }
    }
    i += len;
  }
  return -1;
}

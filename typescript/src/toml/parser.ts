/**
 * TOML v1.0 parser.
 */

import { SerdeError, SerdeErrorCode } from '../error.js';
import type { Value, DateTimeValue } from '../value.js';

/** Parse a TOML string into a Value (object). */
export function parse(input: string): { [key: string]: Value } {
  const parser = new TomlParser(input);
  return parser.parse();
}

class TomlParser {
  private input: string;
  private pos = 0;
  private line = 1;
  private col = 1;

  constructor(input: string) {
    this.input = input;
  }

  parse(): { [key: string]: Value } {
    const root: { [key: string]: Value } = {};
    let currentPath: string[] = [];

    while (true) {
      this.skipWsAndNewlines();
      if (this.pos >= this.input.length) break;

      const ch = this.input[this.pos];
      if (ch === '#') { this.skipComment(); continue; }

      if (ch === '[') {
        this.pos++;
        const isArray = this.input[this.pos] === '[';
        if (isArray) this.pos++;
        this.skipWs();
        const keys = this.parseKey();
        this.skipWs();
        if (isArray) { this.expect(']'); this.expect(']'); }
        else { this.expect(']'); }
        this.skipWs();
        if (this.pos < this.input.length && this.input[this.pos] === '#') this.skipComment();

        if (isArray) {
          this.ensureArrayOfTables(root, keys);
        } else {
          this.ensureTable(root, keys);
        }
        currentPath = keys;
        continue;
      }

      // Key-value pair
      const keys = this.parseKey();
      this.skipWs();
      this.expect('=');
      this.skipWs();
      const value = this.parseValue();
      this.skipWs();
      if (this.pos < this.input.length && this.input[this.pos] === '#') this.skipComment();

      this.insertValue(root, currentPath, keys, value);
    }

    return root;
  }

  private parseKey(): string[] {
    const keys = [this.parseSimpleKey()];
    while (true) {
      this.skipWs();
      if (this.pos < this.input.length && this.input[this.pos] === '.') {
        this.pos++;
        this.skipWs();
        keys.push(this.parseSimpleKey());
      } else break;
    }
    return keys;
  }

  private parseSimpleKey(): string {
    const ch = this.input[this.pos];
    if (ch === '"') return this.parseBasicString();
    if (ch === "'") return this.parseLiteralString();
    return this.parseBareKey();
  }

  private parseBareKey(): string {
    const start = this.pos;
    while (this.pos < this.input.length && isBareKeyChar(this.input[this.pos])) this.pos++;
    if (this.pos === start) throw this.error('empty bare key');
    return this.input.slice(start, this.pos);
  }

  private parseBasicString(): string {
    this.expect('"');
    if (this.input[this.pos] === '"' && this.input[this.pos + 1] === '"') {
      this.pos += 2;
      return this.parseMultilineBasicString();
    }
    let s = '';
    while (true) {
      if (this.pos >= this.input.length) throw this.eof();
      const ch = this.input[this.pos++];
      if (ch === '"') return s;
      if (ch === '\\') { s += this.parseEscape(); continue; }
      s += ch;
    }
  }

  private parseMultilineBasicString(): string {
    if (this.input[this.pos] === '\n') this.pos++;
    else if (this.input[this.pos] === '\r') { this.pos++; if (this.input[this.pos] === '\n') this.pos++; }
    let s = '';
    while (true) {
      if (this.pos >= this.input.length) throw this.eof();
      const ch = this.input[this.pos++];
      if (ch === '"' && this.input.slice(this.pos, this.pos + 2) === '""') {
        this.pos += 2;
        return s;
      }
      if (ch === '\\') {
        const next = this.input[this.pos];
        if (next === '\n' || next === '\r') {
          this.skipWsAndNewlines();
          continue;
        }
        s += this.parseEscape();
        continue;
      }
      s += ch;
    }
  }

  private parseLiteralString(): string {
    this.expect("'");
    if (this.input[this.pos] === "'" && this.input[this.pos + 1] === "'") {
      this.pos += 2;
      return this.parseMultilineLiteralString();
    }
    const start = this.pos;
    while (this.pos < this.input.length && this.input[this.pos] !== "'") this.pos++;
    const s = this.input.slice(start, this.pos);
    this.expect("'");
    return s;
  }

  private parseMultilineLiteralString(): string {
    if (this.input[this.pos] === '\n') this.pos++;
    else if (this.input[this.pos] === '\r') { this.pos++; if (this.input[this.pos] === '\n') this.pos++; }
    let s = '';
    while (true) {
      if (this.pos >= this.input.length) throw this.eof();
      const ch = this.input[this.pos++];
      if (ch === "'" && this.input.slice(this.pos, this.pos + 2) === "''") {
        this.pos += 2;
        return s;
      }
      s += ch;
    }
  }

  private parseEscape(): string {
    const ch = this.input[this.pos++];
    switch (ch) {
      case 'b': return '\b';
      case 't': return '\t';
      case 'n': return '\n';
      case 'f': return '\f';
      case 'r': return '\r';
      case '"': return '"';
      case '\\': return '\\';
      case 'u': return this.parseUnicodeEscape(4);
      case 'U': return this.parseUnicodeEscape(8);
      default: throw this.error('invalid escape');
    }
  }

  private parseUnicodeEscape(digits: number): string {
    const hex = this.input.slice(this.pos, this.pos + digits);
    this.pos += digits;
    const cp = parseInt(hex, 16);
    if (isNaN(cp)) throw this.error('invalid unicode escape');
    return String.fromCodePoint(cp);
  }

  private parseValue(): Value {
    const ch = this.input[this.pos];
    if (ch === '"') return this.parseBasicString();
    if (ch === "'") return this.parseLiteralString();
    if (ch === 't') { this.expectStr('true'); return true; }
    if (ch === 'f') { this.expectStr('false'); return false; }
    if (ch === '[') return this.parseArray();
    if (ch === '{') return this.parseInlineTable();
    if (ch === 'i') { this.expectStr('inf'); return Infinity; }
    if (ch === 'n' && this.input.slice(this.pos, this.pos + 3) === 'nan') { this.pos += 3; return NaN; }
    if (ch === '-' || ch === '+' || (ch >= '0' && ch <= '9')) return this.parseNumberOrDate();
    throw this.error('expected value');
  }

  private parseArray(): Value[] {
    this.expect('[');
    const arr: Value[] = [];
    while (true) {
      this.skipWsNewlinesComments();
      if (this.input[this.pos] === ']') { this.pos++; return arr; }
      arr.push(this.parseValue());
      this.skipWsNewlinesComments();
      if (this.input[this.pos] === ',') this.pos++;
    }
  }

  private parseInlineTable(): { [key: string]: Value } {
    this.expect('{');
    const map: { [key: string]: Value } = {};
    this.skipWs();
    if (this.input[this.pos] === '}') { this.pos++; return map; }
    while (true) {
      this.skipWs();
      const keys = this.parseKey();
      this.skipWs();
      this.expect('=');
      this.skipWs();
      const value = this.parseValue();
      this.insertIntoMap(map, keys, value);
      this.skipWs();
      if (this.input[this.pos] === ',') { this.pos++; }
      else break;
    }
    this.skipWs();
    this.expect('}');
    return map;
  }

  private parseNumberOrDate(): Value {
    const start = this.pos;
    const sign = this.input[this.pos];
    if (sign === '+' || sign === '-') this.pos++;

    // Check for special float
    if (this.input.slice(this.pos, this.pos + 3) === 'inf') {
      this.pos += 3;
      return sign === '-' ? -Infinity : Infinity;
    }
    if (this.input.slice(this.pos, this.pos + 3) === 'nan') {
      this.pos += 3;
      return NaN;
    }

    while (this.pos < this.input.length) {
      const c = this.input[this.pos];
      if (/[0-9a-fA-F_.:+\-TtZxXoObB]/.test(c)) this.pos++;
      else break;
    }

    const raw = this.input.slice(start, this.pos);
    const clean = raw.replace(/_/g, '');

    // Datetime detection
    if (looksLikeDatetime(clean)) {
      return parseDatetime(clean);
    }

    // Hex, octal, binary
    const noSign = (sign === '+' || sign === '-') ? clean.slice(1) : clean;
    if (noSign.startsWith('0x') || noSign.startsWith('0X')) {
      return parseInt(noSign, 16) * (sign === '-' ? -1 : 1);
    }
    if (noSign.startsWith('0o') || noSign.startsWith('0O')) {
      return parseInt(noSign.slice(2), 8) * (sign === '-' ? -1 : 1);
    }
    if (noSign.startsWith('0b') || noSign.startsWith('0B')) {
      return parseInt(noSign.slice(2), 2) * (sign === '-' ? -1 : 1);
    }

    if (clean.includes('.') || clean.includes('e') || clean.includes('E')) {
      return parseFloat(clean);
    }
    return parseInt(clean, 10);
  }

  // --- Table navigation ---

  private ensureTable(root: { [key: string]: Value }, keys: string[]): void {
    let current = root;
    for (const key of keys) {
      if (!(key in current)) {
        current[key] = {};
      }
      const val = current[key];
      if (Array.isArray(val)) {
        current = val[val.length - 1] as { [key: string]: Value };
      } else if (typeof val === 'object' && val !== null && !(val instanceof Uint8Array)) {
        current = val as { [key: string]: Value };
      } else {
        throw new SerdeError(SerdeErrorCode.DuplicateKey, 'duplicate key');
      }
    }
  }

  private ensureArrayOfTables(root: { [key: string]: Value }, keys: string[]): void {
    let current = root;
    for (let i = 0; i < keys.length - 1; i++) {
      const key = keys[i];
      if (!(key in current)) { current[key] = {}; }
      const val = current[key];
      if (Array.isArray(val)) {
        current = val[val.length - 1] as { [key: string]: Value };
      } else if (typeof val === 'object' && val !== null && !(val instanceof Uint8Array)) {
        current = val as { [key: string]: Value };
      } else {
        throw new SerdeError(SerdeErrorCode.DuplicateKey, 'duplicate key');
      }
    }
    const lastKey = keys[keys.length - 1];
    if (!(lastKey in current)) {
      current[lastKey] = [{}];
    } else {
      const val = current[lastKey];
      if (Array.isArray(val)) {
        val.push({});
      } else {
        throw new SerdeError(SerdeErrorCode.DuplicateKey, 'duplicate key');
      }
    }
  }

  private insertValue(root: { [key: string]: Value }, tablePath: string[], keys: string[], value: Value): void {
    let current = root;
    for (const key of tablePath) {
      const val = current[key];
      if (Array.isArray(val)) {
        current = val[val.length - 1] as { [key: string]: Value };
      } else {
        current = val as { [key: string]: Value };
      }
    }
    this.insertIntoMap(current, keys, value);
  }

  private insertIntoMap(map: { [key: string]: Value }, keys: string[], value: Value): void {
    if (keys.length === 1) {
      if (keys[0] in map) throw new SerdeError(SerdeErrorCode.DuplicateKey, 'duplicate key');
      map[keys[0]] = value;
    } else {
      if (!(keys[0] in map)) map[keys[0]] = {};
      const sub = map[keys[0]];
      if (typeof sub === 'object' && sub !== null && !Array.isArray(sub) && !(sub instanceof Uint8Array)) {
        this.insertIntoMap(sub as { [key: string]: Value }, keys.slice(1), value);
      } else {
        throw new SerdeError(SerdeErrorCode.DuplicateKey, 'duplicate key');
      }
    }
  }

  // --- Helpers ---

  private expect(ch: string): void {
    if (this.pos >= this.input.length || this.input[this.pos] !== ch) {
      throw this.error(`expected '${ch}'`);
    }
    this.pos++;
  }

  private expectStr(s: string): void {
    for (let i = 0; i < s.length; i++) {
      if (this.input[this.pos + i] !== s[i]) throw this.error(`expected '${s}'`);
    }
    this.pos += s.length;
  }

  private skipWs(): void {
    while (this.pos < this.input.length && (this.input[this.pos] === ' ' || this.input[this.pos] === '\t')) this.pos++;
  }

  private skipWsAndNewlines(): void {
    while (this.pos < this.input.length && /[ \t\r\n]/.test(this.input[this.pos])) this.pos++;
  }

  private skipWsNewlinesComments(): void {
    while (true) {
      this.skipWsAndNewlines();
      if (this.pos < this.input.length && this.input[this.pos] === '#') this.skipComment();
      else break;
    }
  }

  private skipComment(): void {
    while (this.pos < this.input.length && this.input[this.pos] !== '\n') this.pos++;
    if (this.pos < this.input.length) this.pos++;
  }

  private error(msg: string): SerdeError {
    return new SerdeError(SerdeErrorCode.SyntaxError, msg, this.line, this.col);
  }

  private eof(): SerdeError {
    return new SerdeError(SerdeErrorCode.UnexpectedEof, 'unexpected end of input');
  }
}

function isBareKeyChar(ch: string): boolean {
  return /[A-Za-z0-9_-]/.test(ch);
}

function looksLikeDatetime(s: string): boolean {
  if (s.length >= 10 && s[4] === '-' && s[7] === '-' && /\d/.test(s[0])) return true;
  if (s.length >= 5 && s[2] === ':' && /\d/.test(s[0])) return true;
  return false;
}

function parseDatetime(s: string): DateTimeValue {
  if ((s.includes('T') || s.includes('t')) && s.length > 10) {
    const rest = s.slice(10);
    if (rest.includes('Z') || rest.includes('+') || rest.lastIndexOf('-') > 0) {
      return { kind: 'offset', value: s };
    }
    return { kind: 'local-datetime', value: s };
  }
  if (s.length === 10 && s[4] === '-') {
    return { kind: 'local-date', value: s };
  }
  if (s.includes(':') && !s.includes('-')) {
    return { kind: 'local-time', value: s };
  }
  return { kind: 'local-datetime', value: s };
}

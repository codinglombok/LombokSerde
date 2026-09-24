/**
 * JSON parser (RFC 8259) — recursive descent.
 */

import { SerdeError, SerdeErrorCode } from '../error.js';
import { Value } from '../value.js';

export interface JsonParseOptions {
  maxDepth?: number;
}

/** Parse a JSON string into a Value. */
export function parse(input: string, options?: JsonParseOptions): Value {
  const parser = new JsonParser(input, options?.maxDepth ?? 128);
  return parser.parse();
}

class JsonParser {
  private input: string;
  private pos = 0;
  private line = 1;
  private col = 1;
  private maxDepth: number;

  constructor(input: string, maxDepth: number) {
    this.input = input;
    this.maxDepth = maxDepth;
  }

  parse(): Value {
    this.skipWhitespace();
    const value = this.parseValue(0);
    this.skipWhitespace();
    if (this.pos < this.input.length) {
      throw this.error('trailing data after JSON value');
    }
    return value;
  }

  private parseValue(depth: number): Value {
    if (depth > this.maxDepth) {
      throw new SerdeError(SerdeErrorCode.DepthExceeded, `nesting depth exceeded (max ${this.maxDepth})`);
    }
    this.skipWhitespace();
    const ch = this.peek();
    if (ch === undefined) throw this.eof();
    switch (ch) {
      case '"': return this.parseString();
      case '{': return this.parseObject(depth);
      case '[': return this.parseArray(depth);
      case 't': return this.parseLiteral('true', true);
      case 'f': return this.parseLiteral('false', false);
      case 'n': return this.parseLiteral('null', null);
      default:
        if (ch === '-' || (ch >= '0' && ch <= '9')) return this.parseNumber();
        throw this.error('unexpected character');
    }
  }

  private parseString(): string {
    this.expect('"');
    let s = '';
    while (true) {
      const ch = this.nextChar();
      if (ch === '"') return s;
      if (ch === '\\') {
        const esc = this.nextChar();
        switch (esc) {
          case '"': s += '"'; break;
          case '\\': s += '\\'; break;
          case '/': s += '/'; break;
          case 'b': s += '\b'; break;
          case 'f': s += '\f'; break;
          case 'n': s += '\n'; break;
          case 'r': s += '\r'; break;
          case 't': s += '\t'; break;
          case 'u': {
            const cp = this.parseHex4();
            if (cp >= 0xD800 && cp <= 0xDBFF) {
              this.expect('\\');
              this.expect('u');
              const low = this.parseHex4();
              if (low < 0xDC00 || low > 0xDFFF) throw this.error('invalid surrogate pair');
              s += String.fromCodePoint(0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00));
            } else if (cp >= 0xDC00 && cp <= 0xDFFF) {
              throw this.error('unexpected low surrogate');
            } else {
              s += String.fromCodePoint(cp);
            }
            break;
          }
          default: throw this.error('invalid escape sequence');
        }
      } else if (ch.charCodeAt(0) < 0x20) {
        throw this.error('control character in string');
      } else {
        s += ch;
      }
    }
  }

  private parseHex4(): number {
    let val = 0;
    for (let i = 0; i < 4; i++) {
      const ch = this.nextChar();
      const d = parseInt(ch, 16);
      if (isNaN(d)) throw this.error('invalid hex digit in \\uXXXX');
      val = (val << 4) | d;
    }
    return val;
  }

  private parseNumber(): Value {
    const start = this.pos;
    let isFloat = false;

    if (this.peek() === '-') this.advance();

    if (this.peek() === '0') {
      this.advance();
    } else {
      while (this.peek() !== undefined && this.peek()! >= '0' && this.peek()! <= '9') this.advance();
    }

    if (this.peek() === '.') {
      isFloat = true;
      this.advance();
      while (this.peek() !== undefined && this.peek()! >= '0' && this.peek()! <= '9') this.advance();
    }

    if (this.peek() === 'e' || this.peek() === 'E') {
      isFloat = true;
      this.advance();
      if (this.peek() === '+' || this.peek() === '-') this.advance();
      while (this.peek() !== undefined && this.peek()! >= '0' && this.peek()! <= '9') this.advance();
    }

    const text = this.input.slice(start, this.pos);
    const num = Number(text);
    if (isNaN(num)) throw this.error('invalid number');

    // Return integer for non-float numbers in safe integer range
    if (!isFloat && Number.isSafeInteger(num)) {
      return num;
    }
    return num;
  }

  private parseObject(depth: number): { [key: string]: Value } {
    this.expect('{');
    this.skipWhitespace();
    const map: { [key: string]: Value } = {};

    if (this.peek() === '}') {
      this.advance();
      return map;
    }

    while (true) {
      this.skipWhitespace();
      const key = this.parseString();
      this.skipWhitespace();
      this.expect(':');
      const value = this.parseValue(depth + 1);

      if (key in map) {
        throw new SerdeError(SerdeErrorCode.DuplicateKey, 'duplicate key');
      }
      map[key] = value;

      this.skipWhitespace();
      const ch = this.peek();
      if (ch === ',') {
        this.advance();
      } else if (ch === '}') {
        this.advance();
        return map;
      } else {
        throw this.error("expected ',' or '}'");
      }
    }
  }

  private parseArray(depth: number): Value[] {
    this.expect('[');
    this.skipWhitespace();
    const arr: Value[] = [];

    if (this.peek() === ']') {
      this.advance();
      return arr;
    }

    while (true) {
      arr.push(this.parseValue(depth + 1));
      this.skipWhitespace();
      const ch = this.peek();
      if (ch === ',') {
        this.advance();
      } else if (ch === ']') {
        this.advance();
        return arr;
      } else {
        throw this.error("expected ',' or ']'");
      }
    }
  }

  private parseLiteral<T>(expected: string, value: T): T {
    for (const ch of expected) {
      if (this.nextChar() !== ch) throw this.error('invalid literal');
    }
    return value;
  }

  // --- Helpers ---

  private peek(): string | undefined {
    return this.input[this.pos];
  }

  private advance(): void {
    if (this.pos < this.input.length) {
      if (this.input[this.pos] === '\n') { this.line++; this.col = 1; }
      else { this.col++; }
      this.pos++;
    }
  }

  private nextChar(): string {
    if (this.pos >= this.input.length) throw this.eof();
    const ch = this.input[this.pos];
    this.advance();
    return ch;
  }

  private expect(ch: string): void {
    if (this.nextChar() !== ch) throw this.error('unexpected character');
  }

  private skipWhitespace(): void {
    while (this.pos < this.input.length) {
      const ch = this.input[this.pos];
      if (ch === ' ' || ch === '\t' || ch === '\r' || ch === '\n') this.advance();
      else break;
    }
  }

  private error(msg: string): SerdeError {
    return new SerdeError(SerdeErrorCode.SyntaxError, `${msg} at ${this.line}:${this.col}`, this.line, this.col);
  }

  private eof(): SerdeError {
    return new SerdeError(SerdeErrorCode.UnexpectedEof, 'unexpected end of input');
  }
}

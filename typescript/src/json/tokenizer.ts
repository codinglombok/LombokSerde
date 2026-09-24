/**
 * Streaming JSON tokenizer.
 */

import { SerdeError, SerdeErrorCode } from '../error.js';

export type JsonTokenType =
  | 'object_start' | 'object_end'
  | 'array_start' | 'array_end'
  | 'string' | 'number' | 'bool' | 'null'
  | 'colon' | 'comma';

export interface JsonToken {
  type: JsonTokenType;
  value?: string | number | boolean | null;
}

/** Streaming JSON tokenizer. */
export class JsonTokenizer {
  private input: string;
  private pos = 0;

  constructor(input: string) {
    this.input = input;
  }

  nextToken(): JsonToken | null {
    this.skipWhitespace();
    if (this.pos >= this.input.length) return null;

    const ch = this.input[this.pos];
    switch (ch) {
      case '{': this.pos++; return { type: 'object_start' };
      case '}': this.pos++; return { type: 'object_end' };
      case '[': this.pos++; return { type: 'array_start' };
      case ']': this.pos++; return { type: 'array_end' };
      case ':': this.pos++; return { type: 'colon' };
      case ',': this.pos++; return { type: 'comma' };
      case '"': return { type: 'string', value: this.readString() };
      case 't': this.readLiteral('true'); return { type: 'bool', value: true };
      case 'f': this.readLiteral('false'); return { type: 'bool', value: false };
      case 'n': this.readLiteral('null'); return { type: 'null', value: null };
      default:
        if (ch === '-' || (ch >= '0' && ch <= '9')) {
          return { type: 'number', value: this.readNumber() };
        }
        throw new SerdeError(SerdeErrorCode.SyntaxError, `unexpected character '${ch}'`);
    }
  }

  collectAll(): JsonToken[] {
    const tokens: JsonToken[] = [];
    let tok: JsonToken | null;
    while ((tok = this.nextToken()) !== null) {
      tokens.push(tok);
    }
    return tokens;
  }

  private readString(): string {
    this.pos++; // skip "
    let s = '';
    while (this.pos < this.input.length) {
      const ch = this.input[this.pos++];
      if (ch === '"') return s;
      if (ch === '\\') {
        const esc = this.input[this.pos++];
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
            const hex = this.input.slice(this.pos, this.pos + 4);
            this.pos += 4;
            const cp = parseInt(hex, 16);
            if (cp >= 0xD800 && cp <= 0xDBFF) {
              if (this.input[this.pos] === '\\' && this.input[this.pos + 1] === 'u') {
                this.pos += 2;
                const hex2 = this.input.slice(this.pos, this.pos + 4);
                this.pos += 4;
                const low = parseInt(hex2, 16);
                s += String.fromCodePoint(0x10000 + ((cp - 0xD800) << 10) + (low - 0xDC00));
              }
            } else {
              s += String.fromCodePoint(cp);
            }
            break;
          }
        }
      } else {
        s += ch;
      }
    }
    throw new SerdeError(SerdeErrorCode.UnexpectedEof, 'unterminated string');
  }

  private readNumber(): number {
    const start = this.pos;
    if (this.input[this.pos] === '-') this.pos++;
    while (this.pos < this.input.length && this.input[this.pos] >= '0' && this.input[this.pos] <= '9') this.pos++;
    if (this.pos < this.input.length && this.input[this.pos] === '.') {
      this.pos++;
      while (this.pos < this.input.length && this.input[this.pos] >= '0' && this.input[this.pos] <= '9') this.pos++;
    }
    if (this.pos < this.input.length && (this.input[this.pos] === 'e' || this.input[this.pos] === 'E')) {
      this.pos++;
      if (this.pos < this.input.length && (this.input[this.pos] === '+' || this.input[this.pos] === '-')) this.pos++;
      while (this.pos < this.input.length && this.input[this.pos] >= '0' && this.input[this.pos] <= '9') this.pos++;
    }
    return Number(this.input.slice(start, this.pos));
  }

  private readLiteral(expected: string): void {
    for (let i = 0; i < expected.length; i++) {
      if (this.input[this.pos + i] !== expected[i]) {
        throw new SerdeError(SerdeErrorCode.SyntaxError, `expected '${expected}'`);
      }
    }
    this.pos += expected.length;
  }

  private skipWhitespace(): void {
    while (this.pos < this.input.length) {
      const ch = this.input[this.pos];
      if (ch === ' ' || ch === '\t' || ch === '\r' || ch === '\n') this.pos++;
      else break;
    }
  }
}

/** TOML v1.0 codec — canonical, byte-precise (see SPEC). */

import { SerdeError, syntaxErr } from './error.js';
import { renderFloat } from './float.js';
import {
  INT64_MAX,
  INT64_MIN,
  makeTable,
  tableUnchecked,
  type Datetime,
  type DatetimeKind,
  type Value,
} from './value.js';

const E_SYNTAX = 'SERDE_TOML_SYNTAX';
const E_UTF8 = 'SERDE_TOML_UTF8';
const E_DUPLICATE = 'SERDE_TOML_DUPLICATE';
const E_DEPTH = 'SERDE_TOML_DEPTH';
const E_ROOT = 'SERDE_TOML_ROOT';
const E_BYTES = 'SERDE_TOML_BYTES';
const E_DATETIME = 'SERDE_TOML_DATETIME';

/** Options for the TOML codec. */
export interface TomlOptions {
  readonly depthLimit?: number;
}

function depthOf(opts?: TomlOptions): number {
  return opts?.depthLimit ?? 128;
}

function err(
  code: string,
  offset: number,
  detail: string,
): SerdeError {
  return syntaxErr(code, offset, detail);
}

/** Decode a TOML document into a table value. */
export function tomlDecode(data: Uint8Array, opts?: TomlOptions): Value {
  const bad = utf8FirstBadOffsetT(data);
  if (bad !== -1) {
    throw err(E_UTF8, bad, 'invalid UTF-8');
  }
  const p = new TomlParser(data, depthOf(opts));
  return p.parse();
}

/** Encode a table value as canonical TOML. The root must be a table. */
export function tomlEncode(v: Value, opts?: TomlOptions): Uint8Array {
  if (v === null || v.t !== 'table') {
    throw new SerdeError(
      E_ROOT,
      'TOML documents encode from a table root',
      null,
    );
  }
  const out: string[] = [];
  emitTable(v, [], out, 1, depthOf(opts));
  return new TextEncoder().encode(out.join(''));
}

/** Encode a table value as canonical TOML text (same bytes, as a string). */
export function tomlEncodeText(v: Value, opts?: TomlOptions): string {
  if (v === null || v.t !== 'table') {
    throw new SerdeError(
      E_ROOT,
      'TOML documents encode from a table root',
      null,
    );
  }
  const out: string[] = [];
  emitTable(v, [], out, 1, depthOf(opts));
  return out.join('');
}

type State = 'implicit' | 'explicit' | 'dotted' | 'aot';

interface Node {
  state: State;
  pairs: Map<string, Value>;
  elems: Node[] | null;
}

function newNode(state: State): Node {
  return { state, pairs: new Map(), elems: null };
}

function isPseudo(seg: string): boolean {
  return seg.startsWith('#');
}

class TomlParser {
  private b: Uint8Array;
  private i = 0;
  private limit: number;
  private root: Map<string, Node>;
  private cur: string[];

  constructor(b: Uint8Array, limit: number) {
    this.b = b;
    this.limit = limit;
    this.root = new Map();
    this.root.set(this.key([]), newNode('explicit'));
    this.cur = [];
  }

  private fail(detail: string): SerdeError {
    return err(E_SYNTAX, this.i, detail);
  }

  private dup(): SerdeError {
    return err(E_DUPLICATE, this.i, 'duplicate key or table definition');
  }

  private peek(): number | undefined {
    return this.b[this.i];
  }

  private skipInlineWs(): void {
    while (this.peek() === 0x20 || this.peek() === 0x09) {
      this.i++;
    }
  }

  private skipComment(): void {
    if (this.peek() === 0x23) {
      while (this.peek() !== undefined && this.peek() !== 0x0a && this.peek() !== 0x0d) {
        this.i++;
      }
    }
  }

  private expectLineEnd(): void {
    this.skipInlineWs();
    this.skipComment();
    const c = this.peek();
    if (c === undefined) {
      return;
    }
    if (c === 0x0a) {
      this.i++;
      return;
    }
    if (c === 0x0d) {
      this.i++;
      if (this.peek() === 0x0a) {
        this.i++;
      }
      return;
    }
    throw this.fail('expected end of line');
  }

  parse(): Value {
    for (;;) {
      this.skipInlineWs();
      const c = this.peek();
      if (c === undefined) {
        break;
      }
      if (c === 0x0a) {
        this.i++;
        continue;
      }
      if (c === 0x0d) {
        this.i++;
        if (this.peek() === 0x0a) {
          this.i++;
        }
        continue;
      }
      if (c === 0x23) {
        this.skipComment();
        continue;
      }
      if (c === 0x5b) {
        if (this.b[this.i + 1] === 0x5b) {
          this.parseAotHeader();
        } else {
          this.parseTableHeader();
        }
      } else {
        this.parseKeyval();
      }
      this.expectLineEnd();
    }
    return this.toValue([], 1);
  }

  // --- headers -----------------------------------------------------------

  private parseTableHeader(): void {
    const start = this.i;
    this.i++; // [
    const path = this.parseKeyPath();
    this.skipInlineWs();
    if (this.peek() !== 0x5d) {
      throw this.fail("expected ']'");
    }
    this.i++;
    if (path.length + 1 > this.limit) {
      throw err(E_DEPTH, start, 'depth limit exceeded');
    }
    this.defineTable(path);
    this.cur = path;
  }

  private parseAotHeader(): void {
    const start = this.i;
    this.i += 2; // [[
    const path = this.parseKeyPath();
    this.skipInlineWs();
    if (this.peek() !== 0x5d || this.b[this.i + 1] !== 0x5d) {
      throw this.fail("expected ']]'");
    }
    this.i += 2;
    if (path.length + 1 > this.limit) {
      throw err(E_DEPTH, start, 'depth limit exceeded');
    }
    this.defineAot(path);
    this.cur = path;
  }

  private key(p: string[]): string {
    // JSON encoding is injective: [] (root) and [''] (empty key) differ.
    return JSON.stringify(p);
  }

  private unkey(k: string): string[] {
    return JSON.parse(k) as string[];
  }

  private resolve(path: string[]): string[] {
    const out: string[] = [];
    for (const seg of path) {
      const node = this.root.get(this.key(out));
      if (node !== undefined && node.state === 'aot') {
        out.push(`#${(node.elems as Node[]).length - 1}`);
      }
      out.push(seg);
    }
    return out;
  }

  private defineTable(path: string[]): void {
    const concrete = this.resolve(path);
    for (let j = 1; j <= concrete.length; j++) {
      if (isPseudo(concrete[j - 1])) {
        continue;
      }
      const sp = this.key(concrete.slice(0, j));
      const st = this.root.get(sp)?.state;
      if (st === undefined) {
        this.root.set(sp, newNode('implicit'));
      } else if (st === 'dotted') {
        throw err(
          E_DUPLICATE,
          this.i,
          'dotted-key table redefined by header',
        );
      }
    }
    const ck = this.key(concrete);
    const node = this.root.get(ck);
    if (node === undefined) {
      this.root.set(ck, newNode('explicit'));
      return;
    }
    if (node.state === 'implicit') {
      node.state = 'explicit';
      return;
    }
    throw this.dup();
  }

  private defineAot(path: string[]): void {
    const concrete = this.resolve(path);
    for (let j = 1; j <= concrete.length; j++) {
      if (isPseudo(concrete[j - 1])) {
        continue;
      }
      const sp = this.key(concrete.slice(0, j));
      const st = this.root.get(sp)?.state;
      if (st === undefined) {
        this.root.set(sp, newNode('implicit'));
      } else if (st === 'dotted') {
        throw err(
          E_DUPLICATE,
          this.i,
          'dotted-key table redefined by header',
        );
      }
    }
    const ck = this.key(concrete);
    const node = this.root.get(ck);
    if (node === undefined) {
      throw this.dup();
    }
    if (node.state === 'aot') {
      node.elems?.push(newNode('explicit'));
    } else if (node.state === 'implicit') {
      node.state = 'aot';
      node.elems = [newNode('explicit')];
    } else {
      throw this.dup();
    }
  }

  // --- keys ---------------------------------------------------------------

  private parseKeyPath(): string[] {
    const keys: string[] = [];
    this.skipInlineWs();
    for (;;) {
      keys.push(this.parseSingleKey());
      this.skipInlineWs();
      if (this.peek() === 0x2e) {
        this.i++;
        this.skipInlineWs();
        continue;
      }
      break;
    }
    return keys;
  }

  private parseSingleKey(): string {
    const c = this.peek();
    if (c === undefined) {
      throw this.fail('expected key');
    }
    if (c === 0x22) {
      const k = this.parseBasicString();
      this.checkReserved(k);
      return k;
    }
    if (c === 0x27) {
      const k = this.parseLiteralString();
      this.checkReserved(k);
      return k;
    }
    const s = this.i;
    while (this.peek() !== undefined && isBareKeyByte(this.peek() as number)) {
      this.i++;
    }
    if (this.i === s) {
      throw this.fail('invalid key');
    }
    return utf8DecodeSlice(this.b, s, this.i);
  }

  /** '#'-prefixed keys are reserved: they collide with the internal
   * array-of-tables element markers (fail-closed v1 restriction). */
  private checkReserved(key: string): void {
    if (key.startsWith('#')) {
      throw err(E_SYNTAX, this.i, "keys starting with '#' are reserved");
    }
  }

  // --- keyval ---------------------------------------------------------------

  private parseKeyval(): void {
    const keys = this.parseKeyPath();
    this.skipInlineWs();
    if (this.peek() !== 0x3d) {
      throw this.fail("expected '='");
    }
    this.i++;
    this.skipInlineWs();
    const v = this.parseValue(this.cur.length + keys.length + 1);
    const base = this.resolve(this.cur);
    const inter = keys.slice(0, keys.length - 1);
    if (
      inter.length > 0 &&
      this.root.get(this.key(base))?.state === 'aot'
    ) {
      // v1: dotted keys cannot extend array-of-tables elements
      throw err(
        E_SYNTAX,
        this.i,
        'dotted keys cannot extend array-of-tables elements',
      );
    }
    for (let j = 1; j <= inter.length; j++) {
      const sp = this.key([...base, ...inter.slice(0, j)]);
      // note: '#'-prefixed keys are rejected at parse time, so inter can
      // never contain an AoT element marker here
      const st = this.root.get(sp)?.state;
      if (st === undefined) {
        this.root.set(sp, newNode('dotted'));
      } else if (st === 'explicit') {
        throw err(
          E_DUPLICATE,
          this.i,
          'dotted key extends a header-defined table',
        );
      } else if (st === 'aot') {
        throw err(
          E_SYNTAX,
          this.i,
          'dotted keys cannot extend array-of-tables elements',
        );
      }
    }
    const parentPath = [...base, ...inter];
    const last = keys[keys.length - 1];
    const leaf = this.key([...parentPath, last]);
    if (this.root.has(leaf)) {
      throw this.dup();
    }
    const pk = this.key(parentPath);
    if (!this.root.has(pk)) {
      this.root.set(pk, newNode('dotted'));
    }
    const node = this.root.get(pk) as Node;
    if (node.state === 'aot') {
      // keyvals directly under [[a]] write into the most recent element
      const elem = (node.elems as Node[])[(node.elems as Node[]).length - 1];
      if (elem.pairs.has(last)) {
        throw this.dup();
      }
      elem.pairs.set(last, v);
      return;
    }
    if (node.pairs.has(last)) {
      throw this.dup();
    }
    node.pairs.set(last, v);
  }

  // --- values ---------------------------------------------------------------

  private parseValue(depth: number): Value {
    const c = this.peek();
    if (c === undefined) {
      throw this.fail('expected value');
    }
    if (c === 0x22) {
      if (this.startsWith(bq3())) {
        return { t: 'str', v: this.parseMlBasic() };
      }
      return { t: 'str', v: this.parseBasicString() };
    }
    if (c === 0x27) {
      if (this.startsWith(lq3())) {
        return { t: 'str', v: this.parseMlLiteral() };
      }
      return { t: 'str', v: this.parseLiteralString() };
    }
    if (c === 0x5b) {
      return this.parseArray(depth);
    }
    if (c === 0x7b) {
      return this.parseInlineTable(depth);
    }
    if (this.startsWith([0x74, 0x72, 0x75, 0x65])) {
      this.i += 4;
      return { t: 'bool', v: true };
    }
    if (this.startsWith([0x66, 0x61, 0x6c, 0x73, 0x65])) {
      this.i += 5;
      return { t: 'bool', v: false };
    }
    return this.parseNumberOrDatetime();
  }

  private startsWith(prefix: number[]): boolean {
    for (let j = 0; j < prefix.length; j++) {
      if (this.b[this.i + j] !== prefix[j]) {
        return false;
      }
    }
    return true;
  }

  private parseArray(depth: number): Value {
    this.i++; // [
    const items: Value[] = [];
    for (;;) {
      this.skipArrayWs();
      const c = this.peek();
      if (c === undefined) {
        throw this.fail('unterminated array');
      }
      if (c === 0x5d) {
        this.i++;
        return { t: 'array', v: items };
      }
      items.push(this.parseValue(depth + 1));
      this.skipArrayWs();
      const c2 = this.peek();
      if (c2 === 0x2c) {
        this.i++;
        continue;
      }
      if (c2 === 0x5d) {
        this.i++;
        return { t: 'array', v: items };
      }
      throw this.fail("expected ',' or ']'");
    }
  }

  private skipArrayWs(): void {
    for (;;) {
      const c = this.peek();
      if (c === 0x20 || c === 0x09 || c === 0x0a || c === 0x0d) {
        this.i++;
      } else if (c === 0x23) {
        while (this.peek() !== undefined && this.peek() !== 0x0a && this.peek() !== 0x0d) {
          this.i++;
        }
      } else {
        break;
      }
    }
  }

  private parseInlineTable(depth: number): Value {
    if (depth > this.limit) {
      throw err(E_DEPTH, this.i, 'depth limit exceeded');
    }
    this.i++; // {
    const pairs: Array<[string, Value]> = [];
    this.skipInlineWs();
    if (this.peek() === 0x7d) {
      this.i++;
      return tableUnchecked(pairs);
    }
    for (;;) {
      this.skipInlineWs();
      const keys = this.parseKeyPath();
      this.skipInlineWs();
      if (this.peek() !== 0x3d) {
        throw this.fail("expected '='");
      }
      this.i++;
      this.skipInlineWs();
      const v = this.parseValue(depth + 1);
      if (keys.length > 1) {
        pairs.push([keys[0], nestDotted(keys.slice(1), v)]);
      } else {
        pairs.push([keys[0], v]);
      }
      this.skipInlineWs();
      const c = this.peek();
      if (c === 0x2c) {
        this.i++;
        continue;
      }
      if (c === 0x7d) {
        this.i++;
        return makeTable(pairs, () =>
          err(E_SYNTAX, this.i - 1, 'duplicate key in inline table'),
        );
      }
      throw this.fail("expected ',' or '}' in inline table");
    }
  }

  private parseBasicString(): string {
    this.i++; // "
    let out = '';
    for (;;) {
      const c = this.peek();
      if (c === undefined) {
        throw this.fail('unterminated string');
      }
      if (c === 0x22) {
        this.i++;
        return out;
      }
      if (c === 0x0a || c === 0x0d) {
        throw this.fail('newline in basic string');
      }
      if (c === 0x5c) {
        this.i++;
        out = this.parseEscapeInto(out);
        continue;
      }
      if (c < 0x20 && c !== 0x09) {
        throw this.fail('raw control character in string');
      }
      const [ch, len] = utf8DecodeOne(this.b, this.i);
      out += ch;
      this.i += len;
    }
  }

  private parseEscapeInto(out: string): string {
    const e = this.peek();
    if (e === undefined) {
      throw this.fail('unterminated escape');
    }
    switch (e) {
      case 0x62:
        this.i++;
        return out + '\b';
      case 0x74:
        this.i++;
        return out + '\t';
      case 0x6e:
        this.i++;
        return out + '\n';
      case 0x66:
        this.i++;
        return out + '\f';
      case 0x72:
        this.i++;
        return out + '\r';
      case 0x22:
        this.i++;
        return out + '"';
      case 0x5c:
        this.i++;
        return out + '\\';
      case 0x75:
      case 0x55: {
        const width = e === 0x75 ? 4 : 8;
        this.i++;
        if (this.i + width > this.b.length) {
          throw this.fail('truncated unicode escape');
        }
        const h = utf8DecodeSlice(this.b, this.i, this.i + width);
        if (!/^[0-9a-fA-F]+$/.test(h)) {
          throw this.fail('invalid unicode escape');
        }
        const cp = parseInt(h, 16);
        if (!Number.isSafeInteger(cp) || cp > 0x10ffff) {
          throw this.fail('invalid scalar value');
        }
        this.i += width;
        return out + String.fromCodePoint(cp);
      }
      case 0x0a:
      case 0x0d:
      case 0x20:
      case 0x09: {
        // possible line-ending backslash (multiline strings only)
        let j = this.i;
        let sawNl = false;
        while (j < this.b.length) {
          const c = this.b[j];
          if (c === 0x20 || c === 0x09 || c === 0x0d || c === 0x0a) {
            if (c === 0x0a || c === 0x0d) {
              sawNl = true;
            }
            j++;
          } else {
            break;
          }
        }
        if (sawNl) {
          this.i = j;
          return out;
        }
        throw this.fail('invalid escape');
      }
      default:
        throw this.fail('invalid escape');
    }
  }

  private parseLiteralString(): string {
    this.i++; // '
    const s = this.i;
    for (;;) {
      const c = this.peek();
      if (c === undefined) {
        throw this.fail('unterminated string');
      }
      if (c === 0x27) {
        const r = utf8DecodeSlice(this.b, s, this.i);
        this.i++;
        return r;
      }
      if ((c < 0x20 && c !== 0x09) || c === 0x7f) {
        throw this.fail('raw control character in literal string');
      }
      this.i++;
    }
  }

  private parseMlBasic(): string {
    this.i += 3;
    if (this.peek() === 0x0a) {
      this.i++;
    } else if (this.peek() === 0x0d && this.b[this.i + 1] === 0x0a) {
      this.i += 2;
    }
    let out = '';
    for (;;) {
      if (this.i >= this.b.length) {
        throw this.fail('unterminated multiline string');
      }
      if (this.startsWith([0x22, 0x22, 0x22])) {
        this.i += 3;
        let extra = 0;
        while (this.peek() === 0x22 && extra < 2) {
          out += '"';
          this.i++;
          extra++;
        }
        return out;
      }
      if (this.b[this.i] === 0x5c) {
        this.i++;
        out = this.parseEscapeInto(out);
        continue;
      }
      const c = this.b[this.i];
      if (c < 0x20 && c !== 0x09 && c !== 0x0a && c !== 0x0d) {
        throw this.fail('raw control character in multiline string');
      }
      const [ch, len] = utf8DecodeOne(this.b, this.i);
      out += ch;
      this.i += len;
    }
  }

  private parseMlLiteral(): string {
    this.i += 3;
    if (this.peek() === 0x0a) {
      this.i++;
    } else if (this.peek() === 0x0d && this.b[this.i + 1] === 0x0a) {
      this.i += 2;
    }
    const s = this.i;
    for (;;) {
      if (this.i >= this.b.length) {
        throw this.fail('unterminated multiline string');
      }
      if (this.startsWith([0x27, 0x27, 0x27])) {
        const r = utf8DecodeSlice(this.b, s, this.i);
        this.i += 3;
        return r;
      }
      const c = this.b[this.i];
      if (c < 0x20 && c !== 0x09 && c !== 0x0a && c !== 0x0d) {
        throw this.fail('raw control character in multiline string');
      }
      this.i++;
    }
  }

  // --- numbers & datetimes --------------------------------------------------

  private parseNumberOrDatetime(): Value {
    const start = this.i;
    const scanned = this.scanDatetime();
    if (scanned.error !== null) {
      throw scanned.error;
    }
    if (scanned.kind !== null) {
      const raw = utf8DecodeSlice(this.b, start, scanned.end);
      this.i = scanned.end;
      return { t: 'datetime', kind: scanned.kind, raw };
    }
    let sign = 1n;
    let signSeen = false;
    if (this.peek() === 0x2b || this.peek() === 0x2d) {
      if (this.peek() === 0x2d) {
        sign = -1n;
      }
      signSeen = true;
      this.i++;
    }
    if (this.startsWith([0x69, 0x6e, 0x66])) {
      this.i += 3;
      return {
        t: 'float',
        v: sign < 0n ? Number.NEGATIVE_INFINITY : Number.POSITIVE_INFINITY,
      };
    }
    if (this.startsWith([0x6e, 0x61, 0x6e])) {
      this.i += 3;
      return { t: 'float', v: Number.NaN };
    }
    const digitsStart = this.i;
    this.readDigits(10);
    const base =
      this.i - digitsStart === 1 &&
      this.b[digitsStart] === 0x30 &&
      this.peek() === 0x78
        ? 16
        : this.i - digitsStart === 1 &&
            this.b[digitsStart] === 0x30 &&
            this.peek() === 0x6f
          ? 8
          : this.i - digitsStart === 1 &&
              this.b[digitsStart] === 0x30 &&
              this.peek() === 0x62
            ? 2
            : 10;
    if (base !== 10) {
      if (signSeen) {
        throw this.fail('signs are not allowed on hex/oct/bin integers');
      }
      this.i++;
      this.readDigits(base);
      const text = utf8DecodeSlice(this.b, digitsStart + 2, this.i).replace(/_/g, '');
      const n = sign * BigInt(prefixFor(base) + text);
      if (n < INT64_MIN || n > INT64_MAX) {
        throw err(E_SYNTAX, start, 'integer out of 64-bit range');
      }
      return { t: 'int', v: n };
    }
    let isFloat = false;
    if (this.peek() === 0x2e) {
      isFloat = true;
      this.i++;
      this.readDigits(10);
    }
    if (this.peek() === 0x65 || this.peek() === 0x45) {
      isFloat = true;
      this.i++;
      if (this.peek() === 0x2b || this.peek() === 0x2d) {
        this.i++;
      }
      const c = this.peek();
      if (c === undefined || c < 0x30 || c > 0x39) {
        throw this.fail('expected digit in exponent');
      }
      this.readDigits(10);
    }
    const text = utf8DecodeSlice(this.b, digitsStart, this.i).replace(/_/g, '');
    if (!isFloat) {
      if (text.length > 1 && text.startsWith('0')) {
        throw this.fail('leading zero in integer');
      }
      const n = sign * BigInt(text);
      if (n < INT64_MIN || n > INT64_MAX) {
        throw err(E_SYNTAX, start, 'integer out of 64-bit range');
      }
      return { t: 'int', v: n };
    }
    return { t: 'float', v: Number(text) };
  }

  private readDigits(base: number): void {
    const allowed = (c: number): boolean =>
      base === 10
        ? c >= 0x30 && c <= 0x39
        : base === 16
          ? (c >= 0x30 && c <= 0x39) ||
            (c >= 0x41 && c <= 0x46) ||
            (c >= 0x61 && c <= 0x66)
          : base === 8
            ? c >= 0x30 && c <= 0x37
            : c === 0x30 || c === 0x31;
    let count = 0;
    while (this.i < this.b.length) {
      const c = this.b[this.i];
      if (allowed(c)) {
        count++;
        this.i++;
      } else if (c === 0x5f) {
        if (count === 0) {
          throw this.fail('leading underscore');
        }
        const next = this.b[this.i + 1];
        if (next === undefined || !allowed(next)) {
          throw this.fail('trailing underscore');
        }
        this.i++;
      } else {
        break;
      }
    }
    if (count === 0) {
      throw this.fail('expected digit');
    }
  }

  private scanDatetime(): {
    kind: DatetimeKind | null;
    end: number;
    error: SerdeError | null;
  } {
    const i = this.i;
    const n = this.b.length;
    let j = i;
    while (j < n) {
      const c = this.b[j];
      if ((c >= 0x30 && c <= 0x39) || c === 0x2d || c === 0x3a) {
        j++;
      } else {
        break;
      }
    }
    const seg = utf8DecodeSlice(this.b, i, j);
    const hasDash = seg.includes('-');
    const hasColon = seg.includes(':');
    if (!hasDash && !hasColon) {
      return { kind: null, end: i, error: null };
    }
    if (hasDash && !hasColon) {
      if (j - i !== 10) {
        return { kind: null, end: i, error: null };
      }
      const c = j < n ? this.b[j] : undefined;
      if (c === 0x54 || c === 0x74 || c === 0x20) {
        const m = j + 1;
        let k = m;
        while (k < n) {
          const cc = this.b[k];
          if ((cc >= 0x30 && cc <= 0x39) || cc === 0x3a) {
            k++;
          } else {
            break;
          }
        }
        const tseg = utf8DecodeSlice(this.b, m, k);
        if (!tseg.includes(':')) {
          return this.validateDatetime(i, j, 'date');
        }
        const fz = this.scanFracZone(k);
        if (fz === null) {
          return { kind: null, end: i, error: null };
        }
        return this.validateDatetime(i, fz.end, fz.zone ? 'offset' : 'localdt');
      }
      return this.validateDatetime(i, j, 'date');
    }
    if (hasColon && !hasDash) {
      let k = j;
      if (k < n && this.b[k] === 0x2e) {
        k++;
        if (k < n && this.b[k] >= 0x30 && this.b[k] <= 0x39) {
          while (k < n && this.b[k] >= 0x30 && this.b[k] <= 0x39) {
            k++;
          }
        } else {
          return { kind: null, end: i, error: null };
        }
      }
      return this.validateDatetime(i, k, 'time');
    }
    return { kind: null, end: i, error: null };
  }

  private scanFracZone(k: number): { end: number; zone: boolean } | null {
    const n = this.b.length;
    let end = k;
    if (end < n && this.b[end] === 0x2e) {
      end++;
      if (end < n && this.b[end] >= 0x30 && this.b[end] <= 0x39) {
        while (end < n && this.b[end] >= 0x30 && this.b[end] <= 0x39) {
          end++;
        }
      } else {
        return null;
      }
    }
    if (end < n && (this.b[end] === 0x5a || this.b[end] === 0x7a)) {
      return { end: end + 1, zone: true };
    }
    if (
      end + 6 <= n &&
      (this.b[end] === 0x2b || this.b[end] === 0x2d) &&
      this.b[end + 3] === 0x3a
    ) {
      return { end: end + 6, zone: true };
    }
    return { end, zone: false };
  }

  private validateDatetime(
    s: number,
    end: number,
    kind: DatetimeKind,
  ): { kind: DatetimeKind | null; end: number; error: SerdeError | null } {
    const text = utf8DecodeSlice(this.b, s, end);
    if (datetimeOk(text, kind)) {
      return { kind, end, error: null };
    }
    // the token has datetime shape but is invalid: fail at its start
    return { kind: null, end: s, error: err(E_SYNTAX, s, 'invalid datetime') };
  }

  // --- tree -> Value -----------------------------------------------------------

  private toValue(path: string[], depth: number): Value {
    const node = this.root.get(this.key(path));
    if (node === undefined) {
      throw this.fail('missing table');
    }
    if (node.state === 'aot') {
      const elems: Value[] = [];
      (node.elems as Node[]).forEach((el, idx) => {
        elems.push(this.collectFrom(el.pairs, [...path, `#${idx}`], depth));
      });
      return { t: 'array', v: elems };
    }
    return this.collect(path, depth);
  }

  private collect(path: string[], depth: number): Value {
    const node = this.root.get(this.key(path));
    if (node === undefined) {
      throw this.fail('missing table');
    }
    return this.collectFrom(node.pairs, path, depth);
  }

  private collectFrom(
    pairs: Map<string, Value>,
    basePath: string[],
    depth: number,
  ): Value {
    const out: Array<[string, Value]> = [...pairs.entries()];
    // child tables whose parent path is base_path (root map is insertion-
    // ordered; results are sorted at the end, so iteration order is safe)
    for (const p of this.root.keys()) {
      const segs = this.unkey(p);
      if (segs.length !== basePath.length + 1) {
        continue;
      }
      if (!startsWithPath(segs, basePath)) {
        continue;
      }
      const k = segs[segs.length - 1];
      if (isPseudo(k)) {
        continue;
      }
      if (out.some(([pk]) => pk === k)) {
        throw err(E_DUPLICATE, this.i, 'table and value share a key');
      }
      out.push([k, this.toValue(segs, depth + 1)]);
    }
    out.sort((a, b) => bytewiseCmp(a[0], b[0]));
    return { t: 'table', v: out };
  }
}

function bq3(): number[] {
  return [0x22, 0x22, 0x22];
}
function lq3(): number[] {
  return [0x27, 0x27, 0x27];
}

function startsWithPath(segs: string[], base: string[]): boolean {
  for (let j = 0; j < base.length; j++) {
    if (segs[j] !== base[j]) {
      return false;
    }
  }
  return true;
}

function prefixFor(base: number): string {
  return base === 16 ? '0x' : base === 8 ? '0o' : '0b';
}

function nestDotted(keys: string[], v: Value): Value {
  let inner: Value = v;
  for (let j = keys.length - 1; j >= 0; j--) {
    inner = tableUnchecked([[keys[j], inner]]);
  }
  return inner;
}

function isBareKeyByte(c: number): boolean {
  return (
    (c >= 0x41 && c <= 0x5a) ||
    (c >= 0x61 && c <= 0x7a) ||
    (c >= 0x30 && c <= 0x39) ||
    c === 0x5f ||
    c === 0x2d
  );
}

export function datetimeOk(text: string, kind: DatetimeKind): boolean {
  const b = new TextEncoder().encode(text);
  const seg = (from: number, to: number): number | null => {
    let v = 0;
    for (let j = from; j < to; j++) {
      if (b[j] < 0x30 || b[j] > 0x39) {
        return null;
      }
      v = v * 10 + (b[j] - 0x30);
    }
    return v;
  };
  if (kind === 'date') {
    if (b.length !== 10 || b[4] !== 0x2d || b[7] !== 0x2d) {
      return false;
    }
    const y = seg(0, 4);
    const mo = seg(5, 7);
    const d = seg(8, 10);
    return y !== null && mo !== null && d !== null && mo >= 1 && mo <= 12 && d >= 1 && d <= 31;
  }
  if (kind === 'time') {
    if (b.length < 8 || b[2] !== 0x3a || b[5] !== 0x3a) {
      return false;
    }
    const h = seg(0, 2);
    const mi = seg(3, 5);
    const se = seg(6, 8);
    if (h === null || mi === null || se === null || h > 23 || mi > 59 || se > 60) {
      return false;
    }
    if (b.length === 8) {
      return true;
    }
    if (b.length <= 9 || b[8] !== 0x2e) {
      return false;
    }
    for (let j = 9; j < b.length; j++) {
      if (b[j] < 0x30 || b[j] > 0x39) {
        return false;
      }
    }
    return true;
  }
  // localdt / offset
  const minLen = kind === 'localdt' ? 19 : 20;
  if (b.length < minLen) {
    return false;
  }
  if (
    !(
      b[4] === 0x2d &&
      b[7] === 0x2d &&
      (b[10] === 0x54 || b[10] === 0x74 || b[10] === 0x20) &&
      b[13] === 0x3a &&
      b[16] === 0x3a
    )
  ) {
    return false;
  }
  const mo = seg(5, 7);
  const d = seg(8, 10);
  const h = seg(11, 13);
  const mi = seg(14, 16);
  const se = seg(17, 19);
  if (
    mo === null || d === null || h === null || mi === null || se === null ||
    mo < 1 || mo > 12 || d < 1 || d > 31 || h > 23 || mi > 59 || se > 60
  ) {
    return false;
  }
  let i = 19;
  if (i < b.length && b[i] === 0x2e) {
    i++;
    const start = i;
    while (i < b.length && b[i] >= 0x30 && b[i] <= 0x39) {
      i++;
    }
    if (i === start) {
      return false;
    }
  }
  if (kind === 'localdt') {
    return i === b.length;
  }
  if (i === b.length) {
    return false;
  }
  if (b[i] === 0x5a || b[i] === 0x7a) {
    return i + 1 === b.length;
  }
  if (i + 6 !== b.length || (b[i] !== 0x2b && b[i] !== 0x2d) || b[i + 3] !== 0x3a) {
    return false;
  }
  const zh = seg(i + 1, i + 3);
  const zm = seg(i + 4, i + 6);
  return zh !== null && zm !== null && zh <= 23 && zm <= 59;
}

// --- serializer -----------------------------------------------------------

function isAot(v: Value): boolean {
  return (
    v !== null &&
    v.t === 'array' &&
    v.v.length > 0 &&
    v.v.every((x) => x !== null && x.t === 'table')
  );
}

function emitTable(
  tbl: Value & { readonly t: 'table' },
  path: string[],
  out: string[],
  depth: number,
  limit: number,
): void {
  if (depth > limit) {
    throw new SerdeError(E_DEPTH, 'depth limit exceeded', null);
  }
  const pairs = tbl.v;
  const scalars: Array<[string, Value]> = [];
  const subtables: Array<[string, Value & { readonly t: 'table' }]> = [];
  const aots: Array<[string, Value & { readonly t: 'array' }]> = [];
  for (const [k, x] of pairs) {
    if (x !== null && x.t === 'table') {
      subtables.push([k, x]);
    } else if (x !== null && x.t === 'array' && isAot(x)) {
      aots.push([k, x]);
    } else {
      scalars.push([k, x]);
    }
  }
  const prefix = path.map(tomlKey).join('.');
  for (const [k, x] of scalars) {
    out.push(`${tomlKey(k)} = ${inlineValue(x, depth, limit)}\n`);
  }
  for (const [k, x] of subtables) {
    out.push(`[${prefix ? `${prefix}.${tomlKey(k)}` : tomlKey(k)}]\n`);
    emitTable(x, [...path, k], out, depth + 1, limit);
  }
  for (const [k, x] of aots) {
    for (const el of x.v) {
      out.push(`[[${prefix ? `${prefix}.${tomlKey(k)}` : tomlKey(k)}]]\n`);
      emitTable(el as Value & { readonly t: 'table' }, [...path, k], out, depth + 1, limit);
    }
  }
}

function tomlKey(k: string): string {
  const bytes = new TextEncoder().encode(k);
  if (k.length > 0 && bytes.every(isBareKeyByte)) {
    return k;
  }
  return tomlQuote(k);
}

function tomlQuote(s: string): string {
  let out = '"';
  for (const ch of s) {
    const o = ch.codePointAt(0) as number;
    if (ch === '"') {
      out += '\\"';
    } else if (ch === '\\') {
      out += '\\\\';
    } else if (o === 0x08) {
      out += '\\b';
    } else if (o === 0x09) {
      out += '\\t';
    } else if (o === 0x0a) {
      out += '\\n';
    } else if (o === 0x0c) {
      out += '\\f';
    } else if (o === 0x0d) {
      out += '\\r';
    } else if (o < 0x20 || o === 0x7f) {
      out += `\\u${o.toString(16).padStart(4, '0')}`;
    } else {
      out += ch;
    }
  }
  out += '"';
  return out;
}

function inlineValue(v: Value, depth: number, limit: number): string {
  if (v === null) {
    throw new SerdeError(E_SYNTAX, 'null is not a TOML value', null);
  }
  switch (v.t) {
    case 'bool':
      return v.v ? 'true' : 'false';
    case 'int':
      return v.v.toString();
    case 'uint':
      if (v.v > INT64_MAX) {
        throw new SerdeError(
          E_SYNTAX,
          'unsigned value out of TOML 64-bit signed range',
          null,
        );
      }
      return v.v.toString();
    case 'float': {
      const f = v.v;
      if (Number.isNaN(f)) {
        return 'nan';
      }
      if (!Number.isFinite(f)) {
        return f > 0 ? 'inf' : '-inf';
      }
      return renderFloat(f);
    }
    case 'str':
      return tomlQuote(v.v);
    case 'datetime':
      if (!datetimeOk(v.raw, v.kind)) {
        throw new SerdeError(
          E_DATETIME,
          'invalid datetime raw text',
          null,
        );
      }
      return v.raw;
    case 'bytes':
      throw new SerdeError(
        E_BYTES,
        'Bytes values cannot be encoded as TOML',
        null,
      );
    case 'array': {
      if (depth > limit) {
        throw new SerdeError(E_DEPTH, 'depth limit exceeded', null);
      }
      const parts = v.v.map((x) => inlineValue(x, depth + 1, limit));
      return `[${parts.join(', ')}]`;
    }
    case 'table': {
      if (depth > limit) {
        throw new SerdeError(E_DEPTH, 'depth limit exceeded', null);
      }
      if (v.v.length === 0) {
        return '{}';
      }
      const parts = v.v.map(
        ([k, x]) => `${tomlKey(k)} = ${inlineValue(x, depth + 1, limit)}`,
      );
      return `{ ${parts.join(', ')} }`;
    }
    default:
      throw new Error('unreachable');
  }
}

// --- UTF-8 helpers (byte-precise, mirrors the Rust reference) -------------

function utf8DecodeOne(b: Uint8Array, i: number): [string, number] {
  const c = b[i];
  if (c < 0x80) {
    return [String.fromCharCode(c), 1];
  }
  const n = c < 0xe0 ? 2 : c < 0xf0 ? 3 : 4;
  const cp =
    n === 2
      ? ((c & 0x1f) << 6) | (b[i + 1] & 0x3f)
      : n === 3
        ? ((c & 0x0f) << 12) | ((b[i + 1] & 0x3f) << 6) | (b[i + 2] & 0x3f)
        : ((c & 0x07) << 18) |
          ((b[i + 1] & 0x3f) << 12) |
          ((b[i + 2] & 0x3f) << 6) |
          (b[i + 3] & 0x3f);
  return [String.fromCodePoint(cp), n];
}

function utf8DecodeSlice(b: Uint8Array, from: number, to: number): string {
  // input is pre-validated; decode byte range exactly
  let out = '';
  let i = from;
  while (i < to) {
    const [ch, len] = utf8DecodeOne(b, i);
    out += ch;
    i += len;
  }
  return out;
}

export function utf8FirstBadOffsetT(b: Uint8Array): number {
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
      const lo = j === 1 ? lower : 0x80;
      const hi = j === 1 ? upper : 0xbf;
      if (cc < lo || cc > hi) {
        return i;
      }
    }
    i += len;
  }
  return -1;
}

function bytewiseCmp(a: string, b: string): number {
  const ua = new TextEncoder().encode(a);
  const ub = new TextEncoder().encode(b);
  const n = Math.min(ua.length, ub.length);
  for (let i = 0; i < n; i++) {
    if (ua[i] !== ub[i]) {
      return ua[i] < ub[i] ? -1 : 1;
    }
  }
  return ua.length === ub.length ? 0 : ua.length < ub.length ? -1 : 1;
}

export type { Datetime };

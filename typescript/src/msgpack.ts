/** MessagePack codec — canonical, byte-precise (see SPEC). */

import { SerdeError, syntaxErr } from './error.js';
import {
  INT64_MAX,
  UINT64_MAX,
  makeTable,
  type Datetime,
  type Value,
} from './value.js';

const E_TRUNCATED = 'SERDE_MP_TRUNCATED';
const E_UNEXPECTED = 'SERDE_MP_UNEXPECTED';
const E_TRAILING = 'SERDE_MP_TRAILING';
const E_UTF8 = 'SERDE_MP_UTF8';
const E_EXT = 'SERDE_MP_EXT';
const E_DEPTH = 'SERDE_MP_DEPTH';
const E_DUPLICATE = 'SERDE_MP_DUPLICATE';
const E_DATETIME = 'SERDE_MP_DATETIME';

/** Options for the MessagePack codec. */
export interface MsgPackOptions {
  readonly depthLimit?: number;
}

function depthOf(opts?: MsgPackOptions): number {
  return opts?.depthLimit ?? 128;
}

/** Decode exactly one MessagePack value; trailing bytes are an error. */
export function msgpackDecode(data: Uint8Array, opts?: MsgPackOptions): Value {
  const p = new MpParser(data, depthOf(opts));
  const v = p.readValue(1);
  if (p.i !== data.length) {
    throw syntaxErr(E_TRAILING, p.i, 'trailing bytes after the top-level value');
  }
  return v;
}

/** Encode a value with the canonical (minimal) encoding rules. */
export function msgpackEncode(v: Value, opts?: MsgPackOptions): Uint8Array {
  const out: number[] = [];
  writeValue(out, v, 1, depthOf(opts));
  return Uint8Array.from(out);
}

class MpParser {
  private b: Uint8Array;
  i = 0;
  private limit: number;

  constructor(b: Uint8Array, limit: number) {
    this.b = b;
    this.limit = limit;
  }

  private take(n: number): Uint8Array {
    if (this.i + n > this.b.length) {
      throw syntaxErr(E_TRUNCATED, this.b.length, 'unexpected end of input');
    }
    const s = this.b.subarray(this.i, this.i + n);
    this.i += n;
    return s;
  }

  readValue(depth: number): Value {
    const m = this.take(1)[0];
    if (m <= 0x7f) {
      return { t: 'int', v: BigInt(m) };
    }
    if (m >= 0xe0) {
      return { t: 'int', v: BigInt(m - 0x100) };
    }
    if (m >= 0x80 && m <= 0x8f) {
      return this.readMap(m & 0x0f, depth);
    }
    if (m >= 0x90 && m <= 0x9f) {
      return this.readArray(m & 0x0f, depth);
    }
    if (m >= 0xa0 && m <= 0xbf) {
      return { t: 'str', v: this.readStr(m & 0x1f) };
    }
    switch (m) {
      case 0xc0:
        return null;
      case 0xc1:
        throw syntaxErr(E_UNEXPECTED, this.i - 1, 'reserved type code 0xc1');
      case 0xc2:
        return { t: 'bool', v: false };
      case 0xc3:
        return { t: 'bool', v: true };
      case 0xca: {
        const raw = this.take(4);
        const bits =
          ((raw[0] << 24) | (raw[1] << 16) | (raw[2] << 8) | raw[3]) >>> 0;
        const f = new DataView(new ArrayBuffer(4));
        f.setUint32(0, bits);
        return { t: 'float', v: f.getFloat32(0) };
      }
      case 0xcb: {
        const raw = this.take(8);
        let bits = 0n;
        for (const byte of raw) {
          bits = (bits << 8n) | BigInt(byte);
        }
        const dv = new DataView(new ArrayBuffer(8));
        dv.setBigUint64(0, bits);
        return { t: 'float', v: dv.getFloat64(0) };
      }
      case 0xd0:
      case 0xd1:
      case 0xd2:
      case 0xd3: {
        const n = 1 << (m - 0xd0);
        const raw = this.take(n);
        let v: bigint;
        if (n === 1) {
          v = raw[0] >= 0x80 ? BigInt(raw[0] - 256) : BigInt(raw[0]);
        } else {
          let u = 0n;
          for (const byte of raw) {
            u = (u << 8n) | BigInt(byte);
          }
          const half = 1n << BigInt(8 * n - 1);
          v = u >= half ? u - (1n << BigInt(8 * n)) : u;
        }
        return { t: 'int', v };
      }
      case 0xcc:
      case 0xcd:
      case 0xce:
      case 0xcf: {
        const n = 1 << (m - 0xcc);
        const raw = this.take(n);
        let u = 0n;
        for (const byte of raw) {
          u = (u << 8n) | BigInt(byte);
        }
        return intOrUint(u);
      }
      case 0xd4:
      case 0xd5:
      case 0xd6:
      case 0xd7:
      case 0xd8: {
        const n = 1 << (m - 0xd4);
        return this.readExt(n);
      }
      case 0xd9:
      case 0xda:
      case 0xdb: {
        const n = this.readLen(m - 0xd9, 1);
        return { t: 'str', v: this.readStr(n) };
      }
      case 0xdc:
      case 0xdd: {
        const n = this.readLen(m - 0xdb, 2);
        return this.readArray(n, depth);
      }
      case 0xde:
      case 0xdf: {
        const n = this.readLen(m - 0xdd, 2);
        return this.readMap(n, depth);
      }
      case 0xc4:
      case 0xc5:
      case 0xc6: {
        const n = this.readLen(m - 0xc4, 1);
        return { t: 'bytes', v: new Uint8Array(this.take(n)) };
      }
      case 0xc7:
      case 0xc8:
      case 0xc9: {
        const n = this.readLen(m - 0xc7, 1);
        return this.readExt(n);
      }
      default:
        // every one of the 256 first bytes is matched above
        /* v8 ignore next */
        throw syntaxErr(E_UNEXPECTED, this.i - 1, 'invalid type code');
    }
  }

  private readLen(sizeClass: number, minBytes: number): number {
    let n: number;
    if (sizeClass === 0) {
      n = this.take(1)[0];
    } else if (sizeClass === 1) {
      const raw = this.take(2);
      n = (raw[0] << 8) | raw[1];
    } else {
      const raw = this.take(4);
      n = ((raw[0] << 24) | (raw[1] << 16) | (raw[2] << 8) | raw[3]) >>> 0;
    }
    if (n < minBytes) {
      throw syntaxErr(
        E_UNEXPECTED,
        this.i,
        'length field below the minimum for this type',
      );
    }
    return n;
  }

  private readStr(n: number): string {
    const start = this.i;
    const raw = this.take(n);
    const bad = utf8BadOffset(raw);
    if (bad !== -1) {
      throw syntaxErr(E_UTF8, start + bad, 'invalid UTF-8 in string');
    }
    return new TextDecoder('utf-8').decode(raw);
  }

  private readArray(n: number, depth: number): Value {
    if (depth > this.limit) {
      throw syntaxErr(E_DEPTH, this.i, 'depth limit exceeded');
    }
    const items: Value[] = [];
    for (let j = 0; j < n; j++) {
      items.push(this.readValue(depth + 1));
    }
    return { t: 'array', v: items };
  }

  private readMap(n: number, depth: number): Value {
    if (depth > this.limit) {
      throw syntaxErr(E_DEPTH, this.i, 'depth limit exceeded');
    }
    const pairs: Array<[string, Value]> = [];
    for (let j = 0; j < n; j++) {
      const k = this.readValue(depth + 1);
      if (k === null || k.t !== 'str') {
        throw syntaxErr(E_UNEXPECTED, this.i, 'map key is not a string');
      }
      const v = this.readValue(depth + 1);
      pairs.push([k.v, v]);
    }
    return makeTable(pairs, () =>
      syntaxErr(E_DUPLICATE, this.i, 'duplicate map key'),
    );
  }

  private readExt(n: number): Value {
    const typeRaw = this.take(1)[0];
    const etype = typeRaw >= 0x80 ? typeRaw - 0x100 : typeRaw;
    if (etype !== -1) {
      throw syntaxErr(E_EXT, this.i - 1, 'unsupported extension type');
    }
    if (n === 4) {
      const raw = this.take(4);
      const sec =
        ((raw[0] << 24) | (raw[1] << 16) | (raw[2] << 8) | raw[3]) >>> 0;
      return datetimeFromTimestamp(sec, 0);
    }
    if (n === 8) {
      const raw = this.take(8);
      let bits = 0n;
      for (const byte of raw) {
        bits = (bits << 8n) | BigInt(byte);
      }
      const ns = Number(bits >> 34n);
      const sec = Number(bits & ((1n << 34n) - 1n));
      if (ns > 999_999_999) {
        throw syntaxErr(E_UNEXPECTED, this.i - 8, 'nanoseconds out of range');
      }
      return datetimeFromTimestamp(sec, ns);
    }
    if (n === 12) {
      const raw = this.take(12);
      const ns =
        ((raw[0] << 24) | (raw[1] << 16) | (raw[2] << 8) | raw[3]) >>> 0;
      let sec = 0n;
      for (let j = 4; j < 12; j++) {
        sec = (sec << 8n) | BigInt(raw[j]);
      }
      if (sec >= 1n << 63n) {
        sec -= 1n << 64n;
      }
      if (ns > 999_999_999) {
        throw syntaxErr(E_UNEXPECTED, this.i - 12, 'nanoseconds out of range');
      }
      return datetimeFromTimestamp(Number(sec), ns);
    }
    throw syntaxErr(
      E_EXT,
      this.i - 1,
      'unsupported timestamp payload length',
    );
  }
}

function intOrUint(v: bigint): Value {
  if (v <= INT64_MAX) {
    return { t: 'int', v };
  }
  return { t: 'uint', v };
}

function datetimeFromTimestamp(sec: number, ns: number): Value {
  return {
    t: 'datetime',
    kind: 'offset',
    raw: formatTimestamp(sec, ns),
  };
}

function writeValue(
  out: number[],
  v: Value,
  depth: number,
  limit: number,
): void {
  if (v === null) {
    out.push(0xc0);
  } else if (v.t === 'bool') {
    out.push(v.v ? 0xc3 : 0xc2);
  } else if (v.t === 'int') {
    writeInt(out, v.v);
  } else if (v.t === 'uint') {
    const n = v.v;
    if (n <= 0x7fn) {
      out.push(Number(n));
    } else if (n <= 0xffn) {
      out.push(0xcc, Number(n));
    } else if (n <= 0xffffn) {
      out.push(0xcd, Number(n >> 8n), Number(n & 0xffn));
    } else if (n <= 0xffffffffn) {
      out.push(0xce);
      for (let j = 3; j >= 0; j--) {
        out.push(Number((n >> BigInt(8 * j)) & 0xffn));
      }
    } else if (n <= UINT64_MAX) {
      out.push(0xcf);
      for (let j = 7; j >= 0; j--) {
        out.push(Number((n >> BigInt(8 * j)) & 0xffn));
      }
    } else {
      // defensive: uint values above u64 cannot be constructed from decoders
      /* v8 ignore next */
      throw new SerdeError(E_UNEXPECTED, 'uint out of 64-bit range', null);
    }
  } else if (v.t === 'float') {
    out.push(0xcb);
    const dv = new DataView(new ArrayBuffer(8));
    dv.setFloat64(0, v.v);
    for (let j = 0; j < 8; j++) {
      out.push(dv.getUint8(j));
    }
  } else if (v.t === 'str') {
    const sb = new TextEncoder().encode(v.v);
    const n = sb.length;
    if (n <= 31) {
      out.push(0xa0 | n);
    } else if (n <= 0xff) {
      out.push(0xd9, n);
    } else if (n <= 0xffff) {
      out.push(0xda, n >> 8, n & 0xff);
    } else {
      out.push(0xdb, (n >>> 24) & 0xff, (n >>> 16) & 0xff, (n >>> 8) & 0xff, n & 0xff);
    }
    for (const byte of sb) {
      out.push(byte);
    }
  } else if (v.t === 'bytes') {
    const n = v.v.length;
    if (n <= 0xff) {
      out.push(0xc4, n);
    } else if (n <= 0xffff) {
      out.push(0xc5, n >> 8, n & 0xff);
    } else {
      out.push(0xc6, (n >>> 24) & 0xff, (n >>> 16) & 0xff, (n >>> 8) & 0xff, n & 0xff);
    }
    for (const byte of v.v) {
      out.push(byte);
    }
  } else if (v.t === 'array') {
    if (depth > limit) {
      throw new SerdeError(E_DEPTH, 'depth limit exceeded', null);
    }
    const n = v.v.length;
    if (n <= 15) {
      out.push(0x90 | n);
    } else if (n <= 0xffff) {
      out.push(0xdc, n >> 8, n & 0xff);
    } else {
      out.push(0xdd, (n >>> 24) & 0xff, (n >>> 16) & 0xff, (n >>> 8) & 0xff, n & 0xff);
    }
    for (const x of v.v) {
      writeValue(out, x, depth + 1, limit);
    }
  } else if (v.t === 'table') {
    if (depth > limit) {
      throw new SerdeError(E_DEPTH, 'depth limit exceeded', null);
    }
    const n = v.v.length;
    if (n <= 15) {
      out.push(0x80 | n);
    } else if (n <= 0xffff) {
      out.push(0xde, n >> 8, n & 0xff);
    } else {
      out.push(0xdf, (n >>> 24) & 0xff, (n >>> 16) & 0xff, (n >>> 8) & 0xff, n & 0xff);
    }
    for (const [k, x] of v.v) {
      writeValue(out, { t: 'str', v: k }, depth, limit);
      writeValue(out, x, depth + 1, limit);
    }
  } else {
    writeDatetime(out, v);
  }
}

function writeInt(out: number[], n: bigint): void {
  if (n >= 0n && n <= 0x7fn) {
    out.push(Number(n));
  } else if (n > 0n) {
    if (n <= 0xffn) {
      out.push(0xcc, Number(n));
    } else if (n <= 0xffffn) {
      out.push(0xcd, Number(n >> 8n), Number(n & 0xffn));
    } else if (n <= 0xffffffffn) {
      out.push(0xce);
      for (let j = 3; j >= 0; j--) {
        out.push(Number((n >> BigInt(8 * j)) & 0xffn));
      }
    } else {
      out.push(0xcf);
      for (let j = 7; j >= 0; j--) {
        out.push(Number((n >> BigInt(8 * j)) & 0xffn));
      }
    }
  } else if (n >= -32n) {
    out.push(Number(0xe0n | (n + 32n)));
  } else if (n >= -128n) {
    out.push(0xd0, Number(n + 256n));
  } else if (n >= -32768n) {
    const u = n + 65536n;
    out.push(0xd1, Number(u >> 8n), Number(u & 0xffn));
  } else if (n >= -2147483648n) {
    const u = n + 4294967296n;
    out.push(0xd2);
    for (let j = 3; j >= 0; j--) {
      out.push(Number((u >> BigInt(8 * j)) & 0xffn));
    }
  } else {
    const u = n + 18446744073709551616n;
    out.push(0xd3);
    for (let j = 7; j >= 0; j--) {
      out.push(Number((u >> BigInt(8 * j)) & 0xffn));
    }
  }
}

function writeDatetime(out: number[], dt: Datetime): void {
  if (dt.kind !== 'offset') {
    throw new SerdeError(
      E_DATETIME,
      'only Offset datetimes map to MessagePack timestamps',
      null,
    );
  }
  const parsed = parseOffsetDatetime(dt.raw);
  if (parsed === null) {
    throw new SerdeError(
      E_DATETIME,
      'datetime raw text is not a valid RFC 3339 offset datetime',
      null,
    );
  }
  const [sec, ns] = parsed;
  if (ns === 0 && sec >= 0 && sec <= 0xffffffff) {
    out.push(0xd6, 0xff, (sec >>> 24) & 0xff, (sec >>> 16) & 0xff, (sec >>> 8) & 0xff, sec & 0xff);
  } else if (sec >= 0 && sec <= (1n << 34n) - 1n) {
    const bits = (BigInt(ns) << 34n) | BigInt(sec);
    out.push(0xd7, 0xff);
    for (let j = 7; j >= 0; j--) {
      out.push(Number((bits >> BigInt(8 * j)) & 0xffn));
    }
  } else {
    out.push(0xc7, 12, 0xff);
    for (let j = 3; j >= 0; j--) {
      out.push(Number((BigInt(ns) >> BigInt(8 * j)) & 0xffn));
    }
    const ub = BigInt.asUintN(64, BigInt(sec));
    for (let j = 7; j >= 0; j--) {
      out.push(Number((ub >> BigInt(8 * j)) & 0xffn));
    }
  }
}

// --- calendar math (identical integer arithmetic in every port) -----------

export function daysFromCivil(y: number, m: number, d: number): number {
  const yy = y - (m <= 2 ? 1 : 0);
  const era = Math.floor((y >= 0 ? yy : yy - 399) / 400);
  const yoe = yy - era * 400;
  const mp = m > 2 ? m - 3 : m + 9;
  const doy = Math.floor((153 * mp + 2) / 5) + d - 1;
  const doe = yoe * 365 + Math.floor(yoe / 4) - Math.floor(yoe / 100) + doy;
  return era * 146097 + doe - 719468;
}

export function civilFromDays(z: number): [number, number, number] {
  const zz = z + 719468;
  const era = Math.floor((zz >= 0 ? zz : zz - 146096) / 146097);
  const doe = zz - era * 146097;
  const yoe = Math.floor(
    (doe - Math.floor(doe / 1460) + Math.floor(doe / 36524) - Math.floor(doe / 146096)) / 365,
  );
  const y = yoe + era * 400;
  const doy = doe - (365 * yoe + Math.floor(yoe / 4) - Math.floor(yoe / 100));
  const mp = Math.floor((5 * doy + 2) / 153);
  const d = doy - Math.floor((153 * mp + 2) / 5) + 1;
  const m = mp < 10 ? mp + 3 : mp - 9;
  return [y + (m <= 2 ? 1 : 0), m, d];
}

/** RFC 3339 offset datetime -> [epoch seconds, nanoseconds], or null. */
export function parseOffsetDatetime(raw: string): [number, number] | null {
  const b = new TextEncoder().encode(raw);
  const digits = (from: number, to: number): number | null => {
    let v = 0;
    for (let j = from; j < to; j++) {
      if (b[j] === undefined || b[j] < 0x30 || b[j] > 0x39) {
        return null;
      }
      v = v * 10 + (b[j] - 0x30);
    }
    return v;
  };
  if (b.length < 20) {
    return null;
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
    return null;
  }
  const y = digits(0, 4);
  const mo = digits(5, 7);
  const d = digits(8, 10);
  const h = digits(11, 13);
  const mi = digits(14, 16);
  const s = digits(17, 19);
  if (y === null || mo === null || d === null || h === null || mi === null || s === null) {
    return null;
  }
  let i = 19;
  let ns = 0;
  if (i < b.length && b[i] === 0x2e) {
    i++;
    const start = i;
    while (i < b.length && b[i] >= 0x30 && b[i] <= 0x39) {
      i++;
    }
    if (i === start) {
      return null;
    }
    let frac = 0;
    let scale = 100000000;
    for (let j = start; j < i && scale > 0; j++) {
      frac += (b[j] - 0x30) * scale;
      scale = Math.floor(scale / 10);
    }
    ns = frac;
  }
  if (s === 60) {
    return null; // leap seconds are not representable in MessagePack
  }
  if (mo < 1 || mo > 12 || d < 1 || d > 31 || h > 23 || mi > 59) {
    return null;
  }
  let sec: number;
  if (i < b.length && (b[i] === 0x5a || b[i] === 0x7a)) {
    if (i + 1 !== b.length) {
      return null;
    }
    sec = daysFromCivil(y, mo, d) * 86400 + h * 3600 + mi * 60 + s;
  } else if (
    i + 5 < b.length &&
    (b[i] === 0x2b || b[i] === 0x2d) &&
    b[i + 3] === 0x3a
  ) {
    if (i + 6 !== b.length) {
      return null;
    }
    const oh = digits(i + 1, i + 3);
    const om = digits(i + 4, i + 6);
    if (oh === null || om === null || oh > 23 || om > 59) {
      return null;
    }
    const off = oh * 3600 + om * 60;
    const base = daysFromCivil(y, mo, d) * 86400 + h * 3600 + mi * 60 + s;
    sec = b[i] === 0x2b ? base - off : base + off;
  } else {
    return null;
  }
  return [sec, ns];
}

/** Epoch seconds + nanoseconds -> canonical `...Z` text. */
export function formatTimestamp(sec: number, ns: number): string {
  const days = Math.floor(sec / 86400);
  const rem = ((sec % 86400) + 86400) % 86400;
  const [y, mo, d] = civilFromDays(days);
  const h = Math.floor(rem / 3600);
  const mi = Math.floor((rem % 3600) / 60);
  const s = rem % 60;
  let frac = '';
  if (ns !== 0) {
    frac = `.${ns.toString().padStart(9, '0')}`;
    while (frac.endsWith('0')) {
      frac = frac.slice(0, -1);
    }
  }
  const ypad = y < 0 ? `-${Math.abs(y).toString().padStart(4, '0')}` : y.toString().padStart(4, '0');
  return `${ypad}-${mo.toString().padStart(2, '0')}-${d
    .toString()
    .padStart(2, '0')}T${h.toString().padStart(2, '0')}:${mi
    .toString()
    .padStart(2, '0')}:${s.toString().padStart(2, '0')}${frac}Z`;
}

function utf8BadOffset(b: Uint8Array): number {
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

/** Shared vector-runner helpers: VVE parsing and bit-identical value
 * comparison, mirroring rust/tests/vectors.rs. */
import {
  tableUnchecked,
  type DatetimeKind,
  type Value,
} from '../src/value.js';

/** Compare values with bit-identical float semantics. */
export function valueEq(a: Value, b: Value): boolean {
  if (a === null || b === null) {
    return a === null && b === null;
  }
  if (a.t !== b.t) {
    return false;
  }
  switch (a.t) {
    case 'bool':
      return a.v === (b as typeof a).v;
    case 'int':
    case 'uint':
      return a.v === (b as typeof a).v;
    case 'float': {
      const y = (b as typeof a).v;
      if (Number.isNaN(a.v) || Number.isNaN(y)) {
        return Number.isNaN(a.v) && Number.isNaN(y);
      }
      return sameBits(a.v, y);
    }
    case 'str':
      return a.v === (b as typeof a).v;
    case 'bytes': {
      const y = (b as typeof a).v;
      return (
        a.v.length === y.length && a.v.every((x, j) => x === y[j])
      );
    }
    case 'datetime':
      return a.kind === (b as typeof a).kind && a.raw === (b as typeof a).raw;
    case 'array': {
      const y = (b as typeof a).v;
      return a.v.length === y.length && a.v.every((x, j) => valueEq(x, y[j]));
    }
    case 'table': {
      const y = (b as typeof a).v;
      return (
        a.v.length === y.length &&
        a.v.every(([ka, va], j) => ka === y[j][0] && valueEq(va, y[j][1]))
      );
    }
    default:
      return false;
  }
}

function sameBits(x: number, y: number): boolean {
  const dx = new DataView(new ArrayBuffer(8));
  const dy = new DataView(new ArrayBuffer(8));
  dx.setFloat64(0, x);
  dy.setFloat64(0, y);
  for (let i = 0; i < 8; i++) {
    if (dx.getUint8(i) !== dy.getUint8(i)) {
      return false;
    }
  }
  return true;
}

/** Parse the VVE (vector value encoding) into a Value. */
export function vveParse(v: Value): Value {
  if (v === null || v.t === 'bool' || v.t === 'str') {
    return v;
  }
  if (v.t === 'array') {
    return { t: 'array', v: v.v.map(vveParse) };
  }
  if (v.t !== 'table' || v.v.length !== 1) {
    throw new Error('VVE object must have exactly one key');
  }
  const [tag, payload] = v.v[0];
  switch (tag) {
    case '$i':
      if (payload.t === 'str') {
        return { t: 'int', v: BigInt(payload.v) };
      }
      throw new Error('$i payload must be a string');
    case '$u':
      if (payload.t === 'str') {
        return { t: 'uint', v: BigInt(payload.v) };
      }
      throw new Error('$u payload must be a string');
    case '$f':
      if (payload.t === 'str') {
        if (payload.v === 'inf') {
          return { t: 'float', v: Number.POSITIVE_INFINITY };
        }
        if (payload.v === '-inf') {
          return { t: 'float', v: Number.NEGATIVE_INFINITY };
        }
        if (payload.v === 'nan') {
          return { t: 'float', v: Number.NaN };
        }
        return { t: 'float', v: Number(payload.v) };
      }
      throw new Error('$f payload must be a string');
    case '$b':
      if (payload.t === 'str') {
        return { t: 'bytes', v: hexDecode(payload.v) };
      }
      throw new Error('$b payload must be a string');
    case '$d': {
      if (payload.t !== 'array' || payload.v.length !== 2) {
        throw new Error('$d payload must be [kind, raw]');
      }
      const kind = payload.v[0];
      const raw = payload.v[1];
      if (kind.t !== 'str' || raw.t !== 'str') {
        throw new Error('$d payload must be [kind, raw] strings');
      }
      const kinds: DatetimeKind[] = ['offset', 'localdt', 'date', 'time'];
      if (!kinds.includes(kind.v as DatetimeKind)) {
        throw new Error(`bad datetime kind ${kind.v}`);
      }
      return {
        t: 'datetime',
        kind: kind.v as DatetimeKind,
        raw: raw.v,
      };
    }
    case '$t': {
      if (payload.t !== 'array') {
        throw new Error('$t payload must be an array of pairs');
      }
      const ps: Array<[string, Value]> = payload.v.map((e) => {
        if (e.t !== 'array' || e.v.length !== 2) {
          throw new Error('table entries must be [key, value] pairs');
        }
        if (e.v[0].t !== 'str') {
          throw new Error('table key must be a string');
        }
        return [e.v[0].v, vveParse(e.v[1])];
      });
      return tableUnchecked(ps);
    }
    default:
      throw new Error(`unknown VVE tag ${tag}`);
  }
}

export function hexDecode(s: string): Uint8Array {
  if (s.length % 2 !== 0) {
    throw new Error('odd-length hex');
  }
  const out = new Uint8Array(s.length / 2);
  for (let i = 0; i < out.length; i++) {
    out[i] = parseInt(s.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

export function hexEncode(b: Uint8Array): string {
  return Array.from(b)
    .map((x) => x.toString(16).padStart(2, '0'))
    .join('');
}

export function utf8Decode(b: Uint8Array): string {
  return new TextDecoder('utf-8').decode(b);
}

export function utf8Encode(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

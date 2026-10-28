/** The canonical value model shared by all formats and all ports (SPEC). */
export type DatetimeKind = 'offset' | 'localdt' | 'date' | 'time';

export interface Datetime {
  readonly kind: DatetimeKind;
  /** Exact source text for TOML decode; canonical `...Z` for MessagePack. */
  readonly raw: string;
}

export type Value =
  | null
  | { readonly t: 'bool'; readonly v: boolean }
  | { readonly t: 'int'; readonly v: bigint }
  | { readonly t: 'uint'; readonly v: bigint }
  | { readonly t: 'float'; readonly v: number }
  | { readonly t: 'str'; readonly v: string }
  | { readonly t: 'bytes'; readonly v: Uint8Array }
  | { readonly t: 'array'; readonly v: Value[] }
  | { readonly t: 'table'; readonly v: ReadonlyArray<[string, Value]> }
  | ({ readonly t: 'datetime' } & Datetime);

export const INT64_MIN = -(2n ** 63n);
export const INT64_MAX = 2n ** 63n - 1n;
export const UINT64_MAX = 2n ** 64n - 1n;

/** Build a table: sorted bytewise by key, duplicates are an error. */
export function makeTable(
  pairs: Array<[string, Value]>,
  dupError: () => SerdeErrorLike,
): Value {
  const sorted = [...pairs].sort((a, b) => bytewiseCompare(a[0], b[0]));
  for (let i = 1; i < sorted.length; i++) {
    if (sorted[i - 1][0] === sorted[i][0]) {
      throw dupError();
    }
  }
  return { t: 'table', v: sorted };
}

/** Build a table from pairs known to be duplicate-free. */
export function tableUnchecked(pairs: Array<[string, Value]>): Value {
  const sorted = [...pairs].sort((a, b) => bytewiseCompare(a[0], b[0]));
  return { t: 'table', v: sorted };
}

export function bytewiseCompare(a: string, b: string): number {
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

/** Look up a key in a table value (binary search over the sorted entries). */
export function tableGet(v: Value, key: string): Value | undefined {
  if (v === null || v.t !== 'table') {
    return undefined;
  }
  let lo = 0;
  let hi = v.v.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    const c = bytewiseCompare(v.v[mid][0], key);
    if (c === 0) {
      return v.v[mid][1];
    }
    if (c < 0) {
      lo = mid + 1;
    } else {
      hi = mid;
    }
  }
  return undefined;
}

export interface SerdeErrorLike {
  readonly code: string;
  readonly message: string;
  readonly offset: number | null;
}

/** Default maximum container nesting depth for every format and port. */
export const DEFAULT_DEPTH_LIMIT = 128;

/** Unit tests covering encoder/validator branches beyond the shared
 * vectors (S4: >= 95% statements, >= 90% branches). */
import { describe, expect, it } from 'vitest';
import { SerdeError } from '../src/error.js';
import { renderFloat, shortestDigits } from '../src/float.js';
import {
  jsonDecode,
  jsonEncode,
  jsonEncodeText,
  utf8FirstBadOffset,
  type Value,
} from '../src/json.js';
import {
  civilFromDays,
  daysFromCivil,
  formatTimestamp,
  msgpackDecode,
  msgpackEncode,
  parseOffsetDatetime,
} from '../src/msgpack.js';
import {
  datetimeOk,
  tomlDecode,
  tomlEncodeText,
  utf8FirstBadOffsetT,
} from '../src/toml.js';
import {
  DEFAULT_DEPTH_LIMIT,
  makeTable,
  tableGet,
  tableUnchecked,
} from '../src/value.js';

function enc(s: string): Uint8Array {
  return new TextEncoder().encode(s);
}

function dec(b: Uint8Array): string {
  return new TextDecoder().decode(b);
}

const THROW = (): SerdeError =>
  new SerdeError('SERDE_TEST', 'duplicate', null);

describe('value model', () => {
  it('makeTable sorts bytewise and rejects duplicates', () => {
    const t = makeTable(
      [
        ['b', { t: 'int', v: 1n }],
        ['a', { t: 'int', v: 2n }],
      ],
      THROW,
    );
    expect(t.t === 'table' && t.v[0][0]).toBe('a');
    expect(() =>
      makeTable(
        [
          ['a', null],
          ['a', null],
        ],
        THROW,
      ),
    ).toThrowError(SerdeError);
  });

  it('tableGet performs binary search with bytewise order', () => {
    const t = tableUnchecked([
      ['B', { t: 'int', v: 1n }],
      ['a', { t: 'int', v: 2n }],
      ['c', { t: 'int', v: 3n }],
    ]);
    expect(tableGet(t, 'a')).toEqual({ t: 'int', v: 2n });
    expect(tableGet(t, 'B')).toEqual({ t: 'int', v: 1n });
    expect(tableGet(t, 'zz')).toBeUndefined();
    expect(tableGet(null, 'a')).toBeUndefined();
    expect(tableGet({ t: 'str', v: 'x' }, 'a')).toBeUndefined();
  });

  it('exposes the default depth limit', () => {
    expect(DEFAULT_DEPTH_LIMIT).toBe(128);
  });
});

describe('float rendering', () => {
  it('covers all presentation regimes', () => {
    expect(renderFloat(0)).toBe('0.0');
    expect(renderFloat(-0)).toBe('-0.0');
    expect(renderFloat(1)).toBe('1.0');
    expect(renderFloat(-1.5)).toBe('-1.5');
    expect(renderFloat(0.001)).toBe('0.001');
    expect(renderFloat(1e-6)).toBe('0.000001');
    expect(renderFloat(1e-7)).toBe('1e-7');
    expect(renderFloat(2.5e-10)).toBe('2.5e-10');
    expect(renderFloat(1e20)).toBe('100000000000000000000.0');
    expect(renderFloat(1e21)).toBe('1e+21');
    expect(renderFloat(-1.5e300)).toBe('-1.5e+300');
    expect(renderFloat(5e-324)).toBe('5e-324');
    expect(renderFloat(123.456)).toBe('123.456');
    expect(renderFloat(9007199254740991)).toBe('9007199254740991.0');
  });

  it('shortestDigits strips trailing zeros', () => {
    expect(shortestDigits(1.5)).toEqual(['15', 0]);
    expect(shortestDigits(0.1)).toEqual(['1', -1]);
  });
});

describe('json extras', () => {
  it('jsonEncode matches jsonEncodeText bytes', () => {
    const v: Value = { t: 'str', v: 'héllo' };
    expect(dec(jsonEncode(v))).toBe(jsonEncodeText(v));
  });

  it('rejects raw control characters and partial literals', () => {
    expect(() => jsonDecode(enc('"a\tb"'))).toThrowError(SerdeError);
    expect(() => jsonDecode(enc('nul'))).toThrowError(SerdeError);
    expect(() => jsonDecode(enc('{"a" 1}'))).toThrowError(/:/);
    expect(() => jsonDecode(enc('[1 2]'))).toThrowError(/',' /u);
  });

  it('utf8FirstBadOffset validates byte-precisely', () => {
    expect(utf8FirstBadOffset(enc('ok'))).toBe(-1);
    expect(utf8FirstBadOffset(enc('é中'))).toBe(-1);
    expect(utf8FirstBadOffset(new Uint8Array([0x41, 0xc0, 0x41]))).toBe(1); // overlong
    expect(utf8FirstBadOffset(new Uint8Array([0xe0, 0x80, 0x80]))).toBe(0); // overlong
    expect(utf8FirstBadOffset(new Uint8Array([0xed, 0xa0, 0x80]))).toBe(0); // surrogate
    expect(utf8FirstBadOffset(new Uint8Array([0xf4, 0x90, 0x80, 0x80]))).toBe(0); // > U+10FFFF
    expect(utf8FirstBadOffset(new Uint8Array([0xf4, 0x8f, 0xbf, 0xbf]))).toBe(-1); // U+10FFFF ok
    expect(utf8FirstBadOffset(new Uint8Array([0xc3]))).toBe(0); // truncated
    expect(utf8FirstBadOffset(new Uint8Array([0x80]))).toBe(0); // stray continuation
  });

  it('roundtrips lone-surrogate and bad-escape failures with offsets', () => {
    expect(() => jsonDecode(enc('"\\udc00 x"'))).toThrowError(/low surrogate/);
    expect(() => jsonDecode(enc('"\\ud83dzz"'))).toThrowError(/lone high/);
    try {
      jsonDecode(enc('"\\ud83dzz"'));
    } catch (e) {
      expect((e as SerdeError).offset).toBe(7);
    }
  });

  it('depth option is honored on decode', () => {
    expect(() => jsonDecode(enc('[[1]]'), { depthLimit: 1 })).toThrowError(
      /depth/,
    );
    expect(jsonDecode(enc('[[1]]'), { depthLimit: 2 })).not.toBeNull();
  });
});

describe('toml extras', () => {
  it('datetimeOk validates all four kinds', () => {
    expect(datetimeOk('1979-05-27', 'date')).toBe(true);
    expect(datetimeOk('1979-13-27', 'date')).toBe(false);
    expect(datetimeOk('1979-05-2', 'date')).toBe(false);
    expect(datetimeOk('07:32:00', 'time')).toBe(true);
    expect(datetimeOk('07:32:60', 'time')).toBe(true); // leap second
    expect(datetimeOk('24:00:00', 'time')).toBe(false);
    expect(datetimeOk('07:32:00.', 'time')).toBe(false);
    expect(datetimeOk('1979-05-27T07:32:00', 'localdt')).toBe(true);
    expect(datetimeOk('1979-05-27t07:32:00.5', 'localdt')).toBe(true);
    expect(datetimeOk('1979-05-27 07:32:00', 'localdt')).toBe(true);
    expect(datetimeOk('1979-05-27T07:32:00Z', 'localdt')).toBe(false);
    expect(datetimeOk('1979-05-27T07:32:00Z', 'offset')).toBe(true);
    expect(datetimeOk('1979-05-27T07:32:00z', 'offset')).toBe(true);
    expect(datetimeOk('1979-05-27T07:32:00+07:00', 'offset')).toBe(true);
    expect(datetimeOk('1979-05-27T07:32:00+99:00', 'offset')).toBe(false);
    expect(datetimeOk('1979-05-27T07:32:00+0700', 'offset')).toBe(false);
    expect(datetimeOk('1979-05-27T07:32', 'offset')).toBe(false);
  });

  it('escapes and quotes in encoder output', () => {
    const t = makeTable(
      [
        ['s', { t: 'str', v: 'q"b\\c\nd\u0007\u001f é' }],
        ['k"', { t: 'int', v: 1n }],
        ['1', { t: 'int', v: 2n }],
      ],
      THROW,
    );
    const out = tomlEncodeText(t);
    expect(out).toContain('"k\\"" = 1');
    expect(out).toContain('1 = 2');
    expect(out).toContain('\\u0007');
    expect(out).toContain('\\u001f');
    expect(out).toContain('é');
  });

  it('parses line-ending backslash, U escapes and literal strings', () => {
    const doc = tomlDecode(
      enc('a = """x\\\n  y"""\nb = "\\u00e9"\nc = \'\\n\'\nd = """\ne"""'),
    );
    expect(tableGet(tableGet(doc, 'a') as Value, 'a')).toBeUndefined();
    const a = tableGet(doc, 'a');
    expect(a !== null && a.t === 'str' && a.v).toBe('xy');
    const b = tableGet(doc, 'b');
    expect(b !== null && b.t === 'str' && b.v).toBe('é');
    const c = tableGet(doc, 'c');
    expect(c !== null && c.t === 'str' && c.v).toBe('\\n');
    const d = tableGet(doc, 'd');
    // the first newline after a multiline opener is trimmed
    expect(d !== null && d.t === 'str' && d.v).toBe('e');
  });

  it('rejects inline-table duplicates, bad underscores and bad escapes', () => {
    expect(() => tomlDecode(enc('t = { a = 1, a = 2 }'))).toThrowError(/duplicate/);
    expect(() => tomlDecode(enc('x = _1'))).toThrowError(/leading underscore|invalid/u);
    expect(() => tomlDecode(enc('x = 1_'))).toThrowError(/trailing underscore|expected/u);
    expect(() => tomlDecode(enc('x = "\\\q"'))).toThrowError(/invalid escape/);
    expect(() => tomlDecode(enc('x = 0x'))).toThrowError();
    expect(() => tomlDecode(enc('[]'))).toThrowError();
    expect(() => tomlDecode(enc('[a]]'))).toThrowError();
  });

  it('utf8FirstBadOffsetT mirrors the JSON validator', () => {
    expect(utf8FirstBadOffsetT(enc('ok é'))).toBe(-1);
    expect(utf8FirstBadOffsetT(new Uint8Array([0xff]))).toBe(0);
  });
});

describe('msgpack extras', () => {
  it('calendar math agrees across the roundtrip', () => {
    expect(daysFromCivil(1970, 1, 1)).toBe(0);
    expect(civilFromDays(0)).toEqual([1970, 1, 1]);
    expect(daysFromCivil(1979, 5, 27)).toBe(3433);
    const [y, m, d] = civilFromDays(daysFromCivil(2262, 4, 11));
    expect([y, m, d]).toEqual([2262, 4, 11]);
    const [py, pm, pd] = civilFromDays(daysFromCivil(1969, 12, 31));
    expect([py, pm, pd]).toEqual([1969, 12, 31]);
  });

  it('formatTimestamp renders canonical forms', () => {
    expect(formatTimestamp(0, 0)).toBe('1970-01-01T00:00:00Z');
    expect(formatTimestamp(1, 500000000)).toBe('1970-01-01T00:00:01.5Z');
    expect(formatTimestamp(-1, 0)).toBe('1969-12-31T23:59:59Z');
  });

  it('parseOffsetDatetime handles offsets and separators', () => {
    expect(parseOffsetDatetime('1970-01-01T00:00:00Z')).toEqual([0, 0]);
    expect(parseOffsetDatetime('1970-01-01T00:01:00.25Z')).toEqual([60, 250000000]);
    expect(parseOffsetDatetime('1970-01-01 01:00:00+01:00')).toEqual([0, 0]);
    expect(parseOffsetDatetime('1970-01-01T01:00:00-01:00')).toEqual([7200, 0]);
    expect(parseOffsetDatetime('1970-01-01T00:00:60Z')).toBeNull(); // leap second
    // structural validation only: month/day calendar consistency is not
    // checked (pinned in the SPEC); per-field ranges (day <= 31) still apply
    expect(parseOffsetDatetime('1970-04-31T00:00:00Z')).not.toBeNull();
    expect(parseOffsetDatetime('1970-01-32T00:00:00Z')).toBeNull();
    expect(parseOffsetDatetime('x')).toBeNull();
    expect(parseOffsetDatetime('1970-01-01T00:00:00Zx')).toBeNull();
    expect(parseOffsetDatetime('1970-01-01T00:00:00')).toBeNull();
    expect(parseOffsetDatetime('1970-01-01T00:00:00.')).toBeNull();
  });

  it('encodes and decodes all int/str/bin/map size families', () => {
    const roundtrip = (v: Value): Value =>
      msgpackDecode(msgpackEncode(v));
    expect(roundtrip({ t: 'int', v: 127n })).toEqual({ t: 'int', v: 127n });
    expect(roundtrip({ t: 'int', v: 128n })).toEqual({ t: 'int', v: 128n });
    expect(roundtrip({ t: 'int', v: 65536n })).toEqual({ t: 'int', v: 65536n });
    expect(roundtrip({ t: 'int', v: -2147483648n })).toEqual({
      t: 'int',
      v: -2147483648n,
    });
    expect(roundtrip({ t: 'uint', v: 18446744073709551615n })).toEqual({
      t: 'uint',
      v: 18446744073709551615n,
    });
    const longStr = 'x'.repeat(300);
    expect(roundtrip({ t: 'str', v: longStr })).toEqual({
      t: 'str',
      v: longStr,
    });
    const longBin = new Uint8Array(300).fill(7);
    expect(roundtrip({ t: 'bytes', v: longBin })).toEqual({
      t: 'bytes',
      v: longBin,
    });
    const bigArr: Value = {
      t: 'array',
      v: Array.from({ length: 20 }, (_, j) => ({ t: 'int', v: BigInt(j) })),
    };
    expect(roundtrip(bigArr)).toEqual(bigArr);
    const bigMap = makeTable(
      Array.from({ length: 20 }, (_, j) => [
        `k${j.toString().padStart(2, '0')}`,
        { t: 'int', v: BigInt(j) },
      ]),
      THROW,
    );
    expect(roundtrip(bigMap)).toEqual(bigMap);
  });

  it('rejects truncated lengths and bad float keys', () => {
    expect(() => msgpackDecode(new Uint8Array([0xc4]))).toThrowError(/end of input/);
    expect(() => msgpackDecode(new Uint8Array([0xd9, 0x00, 0x01]))).toThrowError(
      /minimum/,
    );
    expect(() =>
      msgpackDecode(new Uint8Array([0x81, 0x01, 0x01])),
    ).toThrowError(/map key/);
    expect(() => msgpackDecode(new Uint8Array([0xd4, 0x05, 0x01]))).toThrowError(
      /extension/,
    );
    // ext8 with type -1 and a 4-byte payload is a valid timestamp32 carrier
    expect(msgpackDecode(new Uint8Array([0xc7, 0x04, 0xff, 1, 2, 3, 4]))).toEqual(
      msgpackDecode(new Uint8Array([0xd6, 0xff, 1, 2, 3, 4])),
    );
    expect(() =>
      msgpackDecode(new Uint8Array([0xc7, 0x03, 0xff, 1, 2, 3])),
    ).toThrowError(/payload length|timestamp/u);
  });

  it('decodes float32 with exact promotion', () => {
    const v = msgpackDecode(new Uint8Array([0xca, 0x3f, 0xc0, 0x00, 0x00]));
    expect(v.t === 'float' && v.v).toBe(1.5);
  });
});

describe('toml datetime matrix (validator branches)', () => {
  const bad: Array<[string, Parameters<typeof datetimeOk>[1]]> = [
    ['1979-05-27T', 'date'],
    ['x979-05-27', 'date'],
    ['1979-5-271', 'date'],
    ['1979-00-27', 'date'],
    ['1979-05-00', 'date'],
    ['07:3:00', 'time'],
    ['07:32:61', 'time'],
    ['07:32:00.x', 'time'],
    ['07:32:0', 'time'],
    ['1979-05-27T07:32', 'localdt'],
    ['1979-05-27  07:32:00', 'localdt'],
    ['1979-05-27X07:32:00', 'localdt'],
    ['1979-13-27T07:32:00', 'localdt'],
    ['1979-05-27T24:32:00', 'localdt'],
    ['1979-05-27T07:60:00', 'localdt'],
    ['1979-05-27T07:32:61', 'localdt'],
    ['1979-05-27T07:32:00.', 'localdt'],
    ['1979-05-27T07:32:00Z', 'localdt'],
    ['1979-05-27T07:32:00', 'offset'],
    ['1979-05-27T07:32:00Zx', 'offset'],
    ['1979-05-27T07:32:00+24:00', 'offset'],
    ['1979-05-27T07:32:00+07:60', 'offset'],
    ['1979-05-27T07:32:00+07', 'offset'],
  ];
  for (const [text, kind] of bad) {
    it(`rejects ${text} (${kind})`, () => {
      expect(datetimeOk(text, kind)).toBe(false);
    });
  }
  it('accepts lowercase t and space separators', () => {
    expect(datetimeOk('1979-05-27t07:32:00Z', 'offset')).toBe(true);
    expect(datetimeOk('1979-05-27 07:32:00.25-03:30', 'offset')).toBe(true);
  });
});

describe('toml encoder failures', () => {
  const enc = (v: Value): string =>
    tomlEncodeText(v as Value);
  it('rejects null, bytes, uint overflow and invalid datetimes', () => {
    expect(() => enc(null)).toThrowError(/table root/);
    const wrap = (v: Value): Value => tableUnchecked([['k', v]]);
    expect(() => enc(wrap({ t: 'bytes', v: new Uint8Array([1]) }))).toThrowError(
      /Bytes/,
    );
    expect(() => enc(wrap({ t: 'uint', v: 18446744073709551615n }))).toThrowError(
      /64-bit/,
    );
    expect(() =>
      enc(
        tableUnchecked([
          ['d', { t: 'datetime', kind: 'offset', raw: 'not-a-date' }],
        ]),
      ),
    ).toThrowError(/datetime/);
    expect(() => enc(wrap({ t: 'float', v: 1.5 }))).not.toThrowError();
  });

  it('enforces depth on nested arrays and inline tables', () => {
    const deep: Value = {
      t: 'array',
      v: [{ t: 'array', v: [{ t: 'array', v: [] }] }],
    };
    // arrays at root are a table-root error, so nest them
    const wrapped = tableUnchecked([['a', deep]]);
    expect(() => tomlEncodeText(wrapped, { depthLimit: 2 })).toThrowError(/depth/);
    expect(() => tomlEncodeText(wrapped)).not.toThrowError();
    const deepTable = tableUnchecked([
      ['a', tableUnchecked([['b', tableUnchecked([['c', { t: 'int', v: 1n }]])]])],
    ]);
    expect(() => tomlEncodeText(deepTable, { depthLimit: 2 })).toThrowError(/depth/);
  });

  it('encodes empty containers, nested inline tables and mixed arrays', () => {
    const doc = tableUnchecked([
      ['e', { t: 'array', v: [] }],
      ['m', { t: 'array', v: [tableUnchecked([]), { t: 'int', v: 1n }] }],
      ['n', tableUnchecked([['i', tableUnchecked([['j', { t: 'int', v: 2n }]])]])],
      ['t', tableUnchecked([])],
    ]);
    const out = enc(doc);
    expect(out).toContain('e = []');
    expect(out).toContain('m = [{}, 1]');
    expect(out).toContain('[n.i]\nj = 2');
    expect(out).toContain('[t]');
  });

  it('roundtrips the datetime raw text verbatim', () => {
    const doc = tableUnchecked([
      ['d', { t: 'datetime', kind: 'localdt', raw: '1979-05-27t07:32:00' }],
    ]);
    expect(enc(doc)).toContain('d = 1979-05-27t07:32:00');
  });
});

describe('toml parser failure offsets', () => {
  const cases: Array<[string, RegExp]> = [
    ['[a\nx = 1\n', /'\]'/],
    ['[[a]\nx = 1\n', /'\]]'/],
    ['"a = 1\n', /newline in basic string/],
    ['a. = 1\n', /invalid key/],
    ['a = "x" extra\n', /end of line/],
    ["a = '''\nx\n", /unterminated/],
    ['a = """\nx', /unterminated/],
    ['a = "\\U0011FFFF"', /invalid scalar/],
    ['a = "\\U00"', /truncated unicode/],
    ['a = 1.\n', /expected digit/u],
    ['a = 1e\n', /digit in exponent/],
    ['a = 0b2\n', /expected digit/u],
    ['a = +0x10\n', /signs are not allowed/],
    ['a = -0b11\n', /signs are not allowed/],
    ['a = 007\n', /leading zero/],
    ['a = { x = 1\n', /inline table/],
    ['a = [1,\n', /unterminated/],
    ['[a] x = 1\n', /end of line/],
  ];
  for (const [doc, re] of cases) {
    it(`fails on ${JSON.stringify(doc)}`, () => {
      expect(() => tomlDecode(enc(doc))).toThrowError(re);
    });
  }

  it('parses CRLF documents and comments everywhere', () => {
    const doc = tomlDecode(
      enc('# lead\r\na = 1 # trail\r\n[b] # c\r\nc = [\r\n 1, # x\r\n 2\r\n] # y\r\n'),
    );
    expect(tableGet(doc, 'a')).toEqual({ t: 'int', v: 1n });
    const b = tableGet(doc, 'b');
    expect(b).not.toBeUndefined();
  });

  it('rejects table/value key collisions', () => {
    expect(() => tomlDecode(enc('a = 1\n[a]\nb = 2\n'))).toThrowError(
      /share a key/,
    );
  });

  it('rejects control chars in literal and multiline strings', () => {
    expect(() => tomlDecode(enc("a = '\u0001'"))).toThrowError(/control/);
    expect(() => tomlDecode(enc('a = """\u0001"""'))).toThrowError(/control/);
    expect(() => tomlDecode(enc("a = '''\u0001'''"))).toThrowError(/control/);
    expect(() => tomlDecode(enc('a = "\u0001"'))).toThrowError(/control/);
  });
});

describe('coverage completion battery', () => {
  it('json: slash escape, invalid low surrogate, exponent digit, encode depth', () => {
    expect(jsonDecode(enc('"a\\/b"'))).toEqual({ t: 'str', v: 'a/b' });
    try {
      jsonDecode(enc('"\\ud83d\\u0041"'));
      expect.unreachable('should throw');
    } catch (e) {
      expect((e as SerdeError).code).toBe('SERDE_JSON_SYNTAX');
      expect((e as SerdeError).offset).toBe(13);
    }
    expect(() => jsonDecode(enc('1e+'))).toThrowError(/exponent/);
    expect(() => jsonDecode(enc('1ex'))).toThrowError(/exponent/);
    const deep: Value = {
      t: 'array',
      v: [{ t: 'array', v: [{ t: 'array', v: [{ t: 'int', v: 1n }] }] }],
    };
    expect(() => jsonEncode(deep, { depthLimit: 2 })).toThrowError(/depth/);
  });

  it('msgpack: int/uint size families and int64-max encode', () => {
    const rt = (v: Value): Value => msgpackDecode(msgpackEncode(v));
    // decode classifies by value: u64 encodings below i64::MAX come back Int
    expect(rt({ t: 'uint', v: 255n })).toEqual({ t: 'int', v: 255n });
    expect(rt({ t: 'uint', v: 65535n })).toEqual({ t: 'int', v: 65535n });
    expect(rt({ t: 'uint', v: 4294967295n })).toEqual({ t: 'int', v: 4294967295n });
    expect(rt({ t: 'uint', v: 9223372036854775808n })).toEqual({
      t: 'uint',
      v: 9223372036854775808n,
    });
    expect(rt({ t: 'int', v: 9223372036854775807n })).toEqual({
      t: 'int',
      v: 9223372036854775807n,
    });
    expect(rt({ t: 'uint', v: 18446744073709551615n })).toEqual({
      t: 'uint',
      v: 18446744073709551615n,
    });
    expect(rt({ t: 'int', v: -9223372036854775808n })).toEqual({
      t: 'int',
      v: -9223372036854775808n,
    });
  });

  it('msgpack: offset validation and utf8 in str', () => {
    expect(parseOffsetDatetime('1970-01-01T00:00:00+99:00')).toBeNull();
    expect(parseOffsetDatetime('1970-01-01T00:00:00+0x00')).toBeNull();
    // zone -00:01 means local is behind UTC: UTC = local - (-60) = local + 60
    expect(parseOffsetDatetime('1970-01-01T00:00:00-00:01')).toEqual([60, 0]);
    expect(parseOffsetDatetime('1970-01-01T00:00:00.123456789123Z')).toEqual([0, 123456789]);
    const badStr = new Uint8Array([0xa2, 0xf4, 0x90, 0x80]);
    expect(() => msgpackDecode(badStr)).toThrowError(/UTF-8/);
    expect(
      msgpackDecode(new Uint8Array([0xa4, 0xf0, 0x9f, 0x98, 0x80])).t,
    ).toBe('str'); // U+1F600 valid 4-byte
  });

  it('toml: header redefinition matrix', () => {
    // implicit promotion: [a.b] then [a] is allowed once
    const d1 = tomlDecode(enc('[a.b]\nx = 1\n[a]\ny = 2\n'));
    expect(tableGet(tableGet(d1, 'a') as Value, 'y')).toEqual({ t: 'int', v: 2n });
    // [[a]] after [a] is a duplicate
    expect(() => tomlDecode(enc('[a]\n[[a]]\n'))).toThrowError();
    // dotted then [[a]] is a duplicate
    expect(() => tomlDecode(enc('a.b = 1\n[[a]]\n'))).toThrowError();
    // leaf collision: table exists where a value would go
    expect(() => tomlDecode(enc('[a.b]\nx = 1\n[a.b.c]\ny = 2\n[a.b.c]\nz = 3\n'))).toThrowError();
    // dotted key extending a header-defined table
    expect(() => tomlDecode(enc('[a]\n[a.b]\nx = 1\n[c]\nd.e = 2\n[c.d]\ny = 3\n'))).toThrowError();
    // keyvals directly under [[a]] are fine; dotted keys into the element
    // are a pinned v1 restriction (fail-closed)
    const d2 = tomlDecode(enc('[[a]]\nx = 1\ny = 2\n'));
    const arr = tableGet(d2, 'a');
    expect(arr !== null && arr.t === 'array' && arr.v.length).toBe(1);
    expect(() => tomlDecode(enc('[[a]]\nx = 1\ny.z = 2\n'))).toThrowError(
      /array-of-tables/,
    );
    // table under AoT element via header
    const d3 = tomlDecode(enc('[[a]]\nx = 1\n[a.b]\ny = 2\n'));
    const arr3 = tableGet(d3, 'a');
    expect(arr3 !== null && arr3.t === 'array').toBe(true);
  });

  it('toml: numeric and value-parse branches', () => {
    expect(() => tomlDecode(enc('a = 1_'))).toThrowError();
    expect(() => tomlDecode(enc('a = 0x_1'))).toThrowError();
    expect(() => tomlDecode(enc('a = "\u0000"'))).not.toBeNull; // raw NUL is control -> throws
    expect(() => tomlDecode(enc('a = "\u0000"'))).toThrowError(/control/);
    expect(() => tomlDecode(enc("a = '''x\u0001'''"))).toThrowError(/control/);
    const inf = tomlDecode(enc('a = +inf\nb = -nan\n'));
    const av = tableGet(inf, 'a');
    expect(av !== null && av.t === 'float' && av.v).toBe(Number.POSITIVE_INFINITY);
  });

  it('toml: datetime scan edge branches', () => {
    // dash-shaped token that is not 10 chars falls through to the number path
    expect(() => tomlDecode(enc('a = 19-12-3\n'))).toThrowError(/end of line|expected/u);
    // date followed by junk
    expect(() => tomlDecode(enc('a = 1979-05-27x\n'))).toThrowError(/end of line/);
    // date + space + non-time stays a date, then trailing junk errors
    expect(() => tomlDecode(enc('a = 1979-05-27 x\n'))).toThrowError(/end of line|expected/u);
    // frac without digits after date-time
    expect(() => tomlDecode(enc('a = 1979-05-27T07:32:00.Z\n'))).toThrowError();
    // zone-like suffix on a bare date is junk
    expect(() => tomlDecode(enc('a = 1979-05-27+07:00\n'))).toThrowError();
  });

  it('toml: serializer misc branches', () => {
    const encv = (v: Value): string => tomlEncodeText(tableUnchecked([['k', v]]));
    expect(encv({ t: 'float', v: Number.POSITIVE_INFINITY })).toContain('inf');
    expect(encv({ t: 'float', v: Number.NEGATIVE_INFINITY })).toContain('-inf');
    expect(encv({ t: 'float', v: Number.NaN })).toContain('nan');
    expect(encv({ t: 'datetime', kind: 'date', raw: '1979-05-27' })).toContain(
      '1979-05-27',
    );
    // key quoting branches: empty key, 0x7F, non-bare
    const keys = tableUnchecked([
      ['', { t: 'int', v: 1n }],
      ['a\u007fb', { t: 'int', v: 2n }],
      ['a.b', { t: 'int', v: 3n }],
    ]);
    const out = tomlEncodeText(keys);
    expect(out).toContain('"" = 1');
    expect(out).toContain('"a\\u007fb" = 2');
    expect(out).toContain('"a.b" = 3');
    // is_aot false for mixed arrays (inline), true for table arrays (AoT)
    const mixed = tableUnchecked([
      ['m', { t: 'array', v: [tableUnchecked([]), { t: 'int', v: 1n }] }],
      ['t', { t: 'array', v: [tableUnchecked([['x', { t: 'int', v: 1n }]])] }],
    ]);
    const out2 = tomlEncodeText(mixed);
    expect(out2).toContain('m = [{}, 1]');
    expect(out2).toContain('[[t]]');
  });
});

describe('size families and defensive depth', () => {
  it('msgpack encodes all str/bin/array/map size families', () => {
    const rt = (v: Value): Value => msgpackDecode(msgpackEncode(v));
    expect(rt({ t: 'str', v: 'x'.repeat(100) }).t).toBe('str'); // str8
    expect(rt({ t: 'str', v: 'x'.repeat(300) }).t).toBe('str'); // str16
    expect(rt({ t: 'str', v: 'x'.repeat(65537) }).t).toBe('str'); // str32
    expect(rt({ t: 'bytes', v: new Uint8Array(255) }).t).toBe('bytes'); // bin8
    expect(rt({ t: 'bytes', v: new Uint8Array(300) }).t).toBe('bytes'); // bin16
    expect(rt({ t: 'bytes', v: new Uint8Array(65537) }).t).toBe('bytes'); // bin32
    const a32: Value = { t: 'array', v: Array(65537).fill(null) };
    expect((rt(a32) as { t: string; v: unknown[] }).v.length).toBe(65537);
    const m32 = tableUnchecked(
      Array.from({ length: 65537 }, (_, j) => [`k${j}`, { t: 'int', v: 1n } as Value]),
    );
    expect((rt(m32) as { t: string; v: unknown[] }).v.length).toBe(65537);
  });

  it('msgpack decode depth limit fires at 129 nested arrays', () => {
    const opens = new Uint8Array(130);
    opens.fill(0x91);
    const withPayload = new Uint8Array(130);
    withPayload.fill(0x91);
    withPayload[129] = 0x01; // innermost int payload
    expect(() => msgpackDecode(opens, { depthLimit: 128 })).toThrowError();
    expect(() =>
      msgpackDecode(withPayload, { depthLimit: 128 }),
    ).toThrowError(/depth/);
    expect(msgpackDecode(withPayload, { depthLimit: 129 }) !== null).toBe(true);
  });

  it('msgpack rejects out-of-range nanoseconds in ts64 and ts96', () => {
    const badTs64 = new Uint8Array([0xd7, 0xff, 0b00000100, 0, 0, 0, 0, 0, 0, 0]);
    // (10^9) << 34 has bit pattern with ns = 1e9 > 999999999
    const bits = (1000000000n << 34n);
    for (let j = 0; j < 8; j++) {
      badTs64[2 + j] = Number((bits >> BigInt(8 * (7 - j))) & 0xffn);
    }
    expect(() => msgpackDecode(badTs64)).toThrowError(/nanoseconds/);
    const badTs96 = new Uint8Array([0xc7, 12, 0xff, 0x3b, 0x9a, 0xca, 0, 0, 0, 0, 0, 0, 0, 0, 0]);
    expect(() => msgpackDecode(badTs96)).toThrowError(/nanoseconds/);
  });

  it('msgpack parseOffsetDatetime null battery', () => {
    expect(parseOffsetDatetime('1970-01-01T00:00:00Z ')).toBeNull();
    expect(parseOffsetDatetime('0000-01-01T00:00:00Z')).not.toBeNull();
    expect(parseOffsetDatetime('1970-01-0xT00:00:00Z')).toBeNull();
    expect(parseOffsetDatetime('1970-01-01T00:00:00')).toBeNull();
    expect(parseOffsetDatetime('1970-01-01T00:00:00.Z')).toBeNull();
    expect(parseOffsetDatetime('1970-01-01T00:00:00+00')).toBeNull();
    expect(parseOffsetDatetime('1970-01-01T00:00:00+00:0x')).toBeNull();
  });

  it('json encode honors depth for tables', () => {
    const deep: Value = tableUnchecked([
      ['a', tableUnchecked([['b', tableUnchecked([['c', { t: 'int', v: 1n }]])]])],
    ]);
    expect(() => jsonEncode(deep, { depthLimit: 2 })).toThrowError(/depth/);
    expect(jsonEncode(deep)).not.toBeNull();
  });

  it('toml escape battery', () => {
    const d = tomlDecode(enc('a = "\\b\\t\\n\\f\\r\\"\\\\é"\n'));
    const a = tableGet(d, 'a');
    expect(a !== null && a.t === 'str' && a.v).toBe('\b\t\n\f\r"\\é');
    expect(() => tomlDecode(enc('a = "\\uZZZZ"'))).toThrowError(/unicode/);
    expect(() => tomlDecode(enc("a = 'x"))).toThrowError(/unterminated/);
    expect(() => tomlDecode(enc('a = """x'))).toThrowError(/unterminated/);
    const q = tomlDecode(enc('a = """"""""\n')); // content: "" (two quotes)
    const qv = tableGet(q, 'a');
    expect(qv !== null && qv.t === 'str' && qv.v).toBe('""');
    expect(() => tomlDecode(enc('a = 1e_'))).toThrowError();
    expect(() => tomlDecode(enc('a = [1 2]'))).toThrowError();
    expect(() => tomlDecode(enc('a = { x = }'))).toThrowError();
    expect(() => tomlDecode(enc('[]\n'))).toThrowError();
    expect(() => tomlDecode(enc('[[a]\n'))).toThrowError();
    expect(() => tomlDecode(enc('a = "\\""'))).not.toBeNull;
  });

  it('toml reject reserved hash keys and dotted under aot', () => {
    expect(() => tomlDecode(enc('["#x"]\ny = 1\n'))).toThrowError(/reserved/);
    expect(() => tomlDecode(enc("['#x']\ny = 1\n"))).toThrowError(/reserved/);
    expect(() => tomlDecode(enc('[[a]]\nx.y = 1\n'))).toThrowError(/array-of-tables/);
    expect(tomlDecode(enc('["tag"]\ny = 1\n'))).not.toBeNull();
  });
});

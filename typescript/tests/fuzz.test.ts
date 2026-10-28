/** Deterministic property/mutation tests: hammer every decoder with
 * truncated and byte-flipped inputs; each must return a value or throw a
 * SerdeError with a stable code — never crash differently (S4). */
import { describe, expect, it } from 'vitest';
import { SerdeError } from '../src/error.js';
import {
  jsonDecode,
  jsonEncode,
  msgpackDecode,
  msgpackEncode,
  tomlDecode,
  tomlEncode,
  type Value,
} from '../src/index.js';
import { tableUnchecked } from '../src/value.js';

/** xorshift32 — fully deterministic, no Math.random. */
function makeRng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s ^= s << 13;
    s >>>= 0;
    s ^= s >>> 17;
    s ^= s << 5;
    s >>>= 0;
    return s;
  };
}

const SAMPLES: Array<{ format: 'json' | 'toml' | 'msgpack'; bytes: Uint8Array }> = [
  {
    format: 'json',
    bytes: new TextEncoder().encode(
      '{"a":[1,2.5,"x",true,null],"b":{"c":[1,2,3]},"\\u00e9":-0.5}',
    ),
  },
  {
    format: 'toml',
    bytes: new TextEncoder().encode(
      'a = [1, 2.5, "x", true]\n[b]\nc = 1979-05-27T07:32:00Z\nd = 0x2A\n',
    ),
  },
  {
    format: 'msgpack',
    bytes: msgpackEncode(
      tableUnchecked([
        ['a', { t: 'array', v: [{ t: 'int', v: 1n }, { t: 'float', v: 2.5 }, { t: 'str', v: 'x' }] }],
        ['b', { t: 'datetime', kind: 'offset', raw: '2024-01-01T00:00:00Z' }],
      ]),
    ),
  },
];

function expectSerdeFailure(e: unknown, where: string): void {
  expect(e, where).toBeInstanceOf(SerdeError);
  const err = e as SerdeError;
  expect(err.code.startsWith('SERDE_'), `${where}: ${err.code}`).toBe(true);
}

describe('decoder mutation property', () => {
  for (const { format, bytes } of SAMPLES) {
    const decode = (b: Uint8Array): Value =>
      format === 'json'
        ? jsonDecode(b)
        : format === 'toml'
          ? tomlDecode(b)
          : msgpackDecode(b);

    it(`${format}: every truncation fails closed`, () => {
      for (let cut = 0; cut < bytes.length; cut++) {
        const truncated = bytes.slice(0, cut);
        try {
          decode(truncated);
        } catch (e) {
          expectSerdeFailure(e, `${format} truncation at ${cut}`);
        }
      }
    });

    it(`${format}: every byte flip fails closed`, () => {
      const rng = makeRng(0x5eed ^ bytes.length);
      for (let iter = 0; iter < 1200; iter++) {
        const mutated = bytes.slice();
        const pos = rng() % bytes.length;
        mutated[pos] = (mutated[pos] ^ (1 + (rng() % 255))) & 0xff;
        try {
          decode(mutated);
        } catch (e) {
          expectSerdeFailure(e, `${format} flip at ${pos} (iter ${iter})`);
        }
      }
    });

    it(`${format}: random garbage fails closed`, () => {
      const rng = makeRng(0xbeef ^ bytes.length);
      for (let iter = 0; iter < 1500; iter++) {
        const len = 1 + (rng() % 24);
        const garbage = new Uint8Array(len);
        for (let j = 0; j < len; j++) {
          garbage[j] = rng() & 0xff;
        }
        try {
          decode(garbage);
        } catch (e) {
          expectSerdeFailure(e, `${format} garbage iter ${iter}`);
        }
      }
    });
  }

  it('encoders roundtrip the sample values', () => {
    for (const { format, bytes } of SAMPLES) {
      if (format === 'msgpack') {
        const v = msgpackDecode(bytes);
        expect(msgpackDecode(msgpackEncode(v))).toEqual(v);
      } else if (format === 'json') {
        const v = jsonDecode(bytes);
        expect(jsonDecode(jsonEncode(v))).toEqual(v);
      } else {
        const v = tomlDecode(bytes);
        expect(tomlDecode(tomlEncode(v))).toEqual(v);
      }
    }
  });
});

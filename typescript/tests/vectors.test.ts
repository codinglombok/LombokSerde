/** Shared vector runner: every case in vectors/lombokserde-vectors-v1.json
 * must pass bit-identically (mirrors rust/tests/vectors.rs). */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  jsonDecode,
  jsonEncode,
  jsonEncodeText,
  msgpackDecode,
  msgpackEncode,
  tomlDecode,
  tomlEncode,
  tomlEncodeText,
  DEFAULT_DEPTH_LIMIT,
  type Value,
} from '../src/index.js';
import { hexDecode, hexEncode, utf8Decode, utf8Encode, valueEq, vveParse } from './vve.js';

const VECTORS_PATH = path.join(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  '..',
  'vectors',
  'lombokserde-vectors-v1.json',
);

interface Case {
  id: string;
  format: 'json' | 'toml' | 'msgpack';
  op: 'decode' | 'encode';
  input?: string;
  input_hex?: string;
  value?: Value;
  options?: { depth: number };
  expect: {
    value?: Value;
    encoding?: string;
    error?: { code: string; offset: number | null };
  };
}

/** Convert one vector case (a decoded table Value) into a Case object.
 * `expect.value` is kept as the raw decoded Value for vveParse. */
function caseToJs(v: Value): Case {
  if (v === null || v.t !== 'table') {
    throw new Error('case must be a table');
  }
  const field = (k: string): Value | undefined =>
    v.v.find(([kk]) => kk === k)?.[1];
  const str = (x: Value | undefined): string | undefined =>
    x !== undefined && x.t === 'str' ? x.v : undefined;
  const id = str(field('id'));
  const format = str(field('format')) as Case['format'];
  const op = str(field('op')) as Case['op'];
  if (id === undefined || format === undefined || op === undefined) {
    throw new Error('case missing id/format/op');
  }
  let options: { depth: number } | undefined;
  const optsVal = field('options');
  if (optsVal !== undefined && optsVal.t === 'table') {
    const d = optsVal.v.find(([kk]) => kk === 'depth')?.[1];
    if (d !== undefined && d.t === 'int') {
      options = { depth: Number(d.v) };
    }
  }
  let expect: Case['expect'] = {};
  const expVal = field('expect');
  if (expVal === undefined || expVal.t !== 'table') {
    throw new Error(`case ${id} missing expect`);
  }
  const ev = expVal.v.find(([kk]) => kk === 'value')?.[1];
  const enc = str(expVal.v.find(([kk]) => kk === 'encoding')?.[1]);
  const errV = expVal.v.find(([kk]) => kk === 'error')?.[1];
  if (ev !== undefined) {
    expect.value = ev;
  }
  if (enc !== undefined) {
    expect.encoding = enc;
  }
  if (errV !== undefined && errV.t === 'table') {
    const code = str(errV.v.find(([kk]) => kk === 'code')?.[1]) as string;
    const offV = errV.v.find(([kk]) => kk === 'offset')?.[1];
    const offset =
      offV === undefined || offV === null || offV.t !== 'int'
        ? null
        : Number(offV.v);
    expect.error = { code, offset };
  }
  const c: Case = { id, format, op, expect };
  const input = str(field('input'));
  if (input !== undefined) {
    c.input = input;
  }
  const inputHex = str(field('input_hex'));
  if (inputHex !== undefined) {
    c.input_hex = inputHex;
  }
  const val = field('value');
  if (val !== undefined) {
    c.value = val;
  }
  if (options !== undefined) {
    c.options = options;
  }
  return c;
}

function loadCases(): Case[] {
  const raw = readFileSync(VECTORS_PATH);
  // dogfood: the vector file is parsed with this port's own JSON decoder
  const doc = jsonDecode(raw) as Value;
  if (doc === null || doc.t !== 'table') {
    throw new Error('vector file must be a table');
  }
  const cases = doc.v.find(([k]) => k === 'cases');
  if (!cases || cases[1].t !== 'array') {
    throw new Error('vector file has no cases array');
  }
  return (cases[1].v as Value[]).map(caseToJs);
}

function runCase(c: Case): { value?: Value; encoding?: string } {
  const depth = c.options?.depth ?? DEFAULT_DEPTH_LIMIT;
  if (c.op === 'decode') {
    const input =
      c.input !== undefined
        ? utf8Encode(c.input)
        : hexDecode(c.input_hex as string);
    if (c.format === 'json') {
      const v = jsonDecode(input, { depthLimit: depth });
      return { value: v, encoding: jsonEncodeText(v, { depthLimit: depth }) };
    }
    if (c.format === 'toml') {
      const v = tomlDecode(input, { depthLimit: depth });
      return { value: v, encoding: tomlEncodeText(v, { depthLimit: depth }) };
    }
    const v = msgpackDecode(input, { depthLimit: depth });
    return {
      value: v,
      encoding: hexEncode(msgpackEncode(v, { depthLimit: depth })),
    };
  }
  const v = vveParse(c.value as Value);
  if (c.format === 'json') {
    const enc = jsonEncode(v, { depthLimit: depth });
    return {
      value: jsonDecode(enc, { depthLimit: depth }),
      encoding: utf8Decode(enc),
    };
  }
  if (c.format === 'toml') {
    const enc = tomlEncode(v, { depthLimit: depth });
    return {
      value: tomlDecode(enc, { depthLimit: depth }),
      encoding: utf8Decode(enc),
    };
  }
  const enc = msgpackEncode(v, { depthLimit: depth });
  return { value: msgpackDecode(enc, { depthLimit: depth }), encoding: hexEncode(enc) };
}

describe('shared cross-language vectors', () => {
  const cases = loadCases();

  it('contains at least 100 cases', () => {
    expect(cases.length).toBeGreaterThanOrEqual(100);
  });

  for (const c of cases) {
    it(`case ${c.id}`, () => {
      const exp = c.expect;
      if (exp.error !== undefined) {
        let failed = false;
        try {
          runCase(c);
        } catch (e) {
          failed = true;
          const err = e as { code: string; offset: number | null };
          expect(err.code, `${c.id} code`).toBe(exp.error.code);
          expect(err.offset, `${c.id} offset`).toBe(exp.error.offset);
        }
        expect(failed, `${c.id}: expected an error`).toBe(true);
        return;
      }
      const got = runCase(c);
      if (exp.value !== undefined) {
        const want = vveParse(exp.value);
        if (!valueEq(got.value as Value, want)) {
          const repr = (x: unknown): string =>
            JSON.stringify(x, (_, y: unknown) =>
              typeof y === 'bigint' ? y.toString() : y,
            );
          throw new Error(
            `${c.id}: value mismatch\n  got:  ${repr(got.value)}\n  want: ${repr(want)}`,
          );
        }
      }
      if (exp.encoding !== undefined) {
        expect(got.encoding, `${c.id} encoding`).toBe(exp.encoding);
      }
    });
  }
});

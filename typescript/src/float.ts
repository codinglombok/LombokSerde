/**
 * Canonical float rendering, identical in every port (SPEC section 4).
 *
 * Digits are the shortest decimal that roundtrips to the same binary64,
 * obtained here from Number.prototype.toExponential() (the ECMAScript
 * shortest-roundtrip formatter), re-rendered with pinned rules.
 */

/** Render a finite binary64 per the pinned presentation rules. */
export function renderFloat(f: number): string {
  if (f === 0) {
    return Object.is(f, -0) ? '-0.0' : '0.0';
  }
  const sign = f < 0 || Object.is(f, -0) ? '-' : '';
  const [digits, exp] = shortestDigits(Math.abs(f));
  const n = digits.length;
  if (exp >= 21 || exp <= -7) {
    const mant = n > 1 ? `${digits[0]}.${digits.slice(1)}` : digits;
    const esign = exp >= 0 ? '+' : '-';
    return `${sign}${mant}e${esign}${Math.abs(exp)}`;
  }
  if (exp >= n - 1) {
    return `${sign}${digits}${'0'.repeat(exp - (n - 1))}.0`;
  }
  if (exp >= 0) {
    return `${sign}${digits.slice(0, exp + 1)}.${digits.slice(exp + 1)}`;
  }
  return `${sign}0.${'0'.repeat(-exp - 1)}${digits}`;
}

/** Shortest-roundtrip digits + decimal exponent of the first digit. */
export function shortestDigits(abs: number): [string, number] {
  // e.g. "1.5e+300", "1e+0", "5e-324"
  const s = abs.toExponential();
  const m = /^(\d)(?:\.(\d+))?e([+-]\d+)$/.exec(s);
  if (m === null) {
    // defensive: the ECMAScript spec pins this grammar
    /* v8 ignore next */
    throw new Error(`unexpected toExponential output: ${s}`);
  }
  const digits = (m[1] + (m[2] ?? '')).replace(/0+$/, '');
  const exp = parseInt(m[3], 10);
  return [digits, exp];
}

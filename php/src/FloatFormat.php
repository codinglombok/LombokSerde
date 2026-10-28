<?php

declare(strict_types=1);

namespace CodingLombok\LombokSerde;

/**
 * Renders a finite binary64 per the pinned presentation rules (SPEC
 * section 4): shortest-roundtrip digits obtained from the platform
 * formatter (json_encode with serialize_precision=-1, a correctly-rounded
 * shortest formatter), re-rendered with fixed rules:
 *   - integral floats keep one fractional digit: 1 -> "1.0", -0.0 -> "-0.0"
 *   - exponential form iff the decimal exponent is >= 21 or <= -7
 *   - exponent always signed, no zero padding: "1e+21", "1.5e-7"
 */
final class FloatFormat
{
    public static function render(float $f): string
    {
        if ($f == 0.0) {
            return \str_starts_with(\var_export($f, true), '-') ? '-0.0' : '0.0';
        }
        $sign = '';
        if ($f < 0) {
            $sign = '-';
        }
        [$digits, $exp] = self::shortestDigits(\abs($f));
        $n = \strlen($digits);
        if ($exp >= 21 || $exp <= -7) {
            $mant = $n > 1 ? $digits[0] . '.' . \substr($digits, 1) : $digits;
            $esign = $exp < 0 ? '-' : '+';
            $ae = \abs($exp);

            return "{$sign}{$mant}e{$esign}{$ae}";
        }
        if ($exp >= $n - 1) {
            return $sign . $digits . \str_repeat('0', $exp - ($n - 1)) . '.0';
        }
        if ($exp >= 0) {
            return $sign . \substr($digits, 0, $exp + 1) . '.' . \substr($digits, $exp + 1);
        }

        return $sign . '0.' . \str_repeat('0', -$exp - 1) . $digits;
    }

    /**
     * Returns the shortest-roundtrip digits of |$f| plus the decimal
     * exponent of the first digit (value = 0.digits * 10^(exp+1)).
     *
     * @return array{0:string,1:int}
     */
    public static function shortestDigits(float $f): array
    {
        // finite by contract; json_encode yields forms like "1.5", "0.001",
        // "1.0e-6", "5.0e-324"
        $s = \json_encode($f);
        if ($s === false) {
            return ['0', 0];
        }
        if (!\preg_match('/^(\d+)(?:\.(\d+))?(?:e([+-]?\d+))?$/i', $s, $m)) {
            return ['0', 0];
        }
        $intPart = $m[1];
        $fracPart = $m[2] ?? '';
        $e = isset($m[3]) ? (int) $m[3] : 0;
        if ($intPart === '0' && $fracPart !== '') {
            $z = 0;
            while ($z < \strlen($fracPart) && $fracPart[$z] === '0') {
                $z++;
            }
            $exp = $e - $z - 1;
            $digits = \rtrim(\substr($fracPart, $z), '0');
        } else {
            $exp = $e + \strlen($intPart) - 1;
            $digits = \rtrim($intPart . $fracPart, '0');
        }
        if ($digits === '' || $digits === false) {
            return ['0', 0];
        }

        return [$digits, $exp];
    }
}

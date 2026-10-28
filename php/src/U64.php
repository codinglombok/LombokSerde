<?php

declare(strict_types=1);

namespace CodingLombok\LombokSerde;

/**
 * Pure-PHP unsigned-64 helpers: PHP ints are 64-bit signed, so uint values
 * above PHP_INT_MAX (2^63 - 1) travel as canonical decimal strings. These
 * helpers do exact string arithmetic only for the u64 range (8 bytes), so
 * the port stays dependency-free and deterministic.
 */
final class U64
{
    /** Exact decimal value of a big-endian unsigned integer (1..8 bytes). */
    public static function fromBytes(string $be): string
    {
        $n = '0';
        $len = \strlen($be);
        for ($i = 0; $i < $len; $i++) {
            $n = self::mulAddSmall($n, 256, \ord($be[$i]));
        }

        return $n;
    }

    /** Big-endian 8-byte encoding of a decimal string (0 .. 2^64-1). */
    public static function toBytes8(string $dec): string
    {
        $out = "\0\0\0\0\0\0\0\0";
        for ($i = 7; $i >= 0; $i--) {
            [$dec, $r] = self::divModSmall($dec, 256);
            $out[$i] = \chr($r);
        }

        return $out;
    }

    /** Three-way compare of two canonical decimal strings. */
    public static function cmp(string $a, string $b): int
    {
        $a = self::trim($a);
        $b = self::trim($b);
        $la = \strlen($a);
        $lb = \strlen($b);
        if ($la !== $lb) {
            return $la < $lb ? -1 : 1;
        }

        return $a <=> $b;
    }

    /** True when $dec (decimal string) is strictly above $bound. */
    public static function gt(string $dec, string $bound): bool
    {
        return self::cmp($dec, $bound) > 0;
    }

    /** Exact ($a - $b) for canonical decimal strings with $a >= $b >= 0. */
    public static function decSub(string $a, string $b): string
    {
        $a = self::trim($a);
        $b = self::trim($b);
        $out = '';
        $borrow = 0;
        $i = \strlen($a) - 1;
        $j = \strlen($b) - 1;
        while ($i >= 0 || $j >= 0) {
            $x = ($i >= 0 ? (int) $a[$i] : 0) - $borrow - ($j >= 0 ? (int) $b[$j] : 0);
            if ($x < 0) {
                $x += 10;
                $borrow = 1;
            } else {
                $borrow = 0;
            }
            $out .= \chr(48 + $x);
            $i--;
            $j--;
        }

        return self::trim(\strrev($out));
    }

    /** Exact ($a + $b) for canonical decimal strings (both >= 0). */
    public static function decAdd(string $a, string $b): string
    {
        $a = self::trim($a);
        $b = self::trim($b);
        $out = '';
        $carry = 0;
        $i = \strlen($a) - 1;
        $j = \strlen($b) - 1;
        while ($i >= 0 || $j >= 0 || $carry > 0) {
            $x = ($i >= 0 ? (int) $a[$i] : 0) + ($j >= 0 ? (int) $b[$j] : 0) + $carry;
            $out .= \chr(48 + ($x % 10));
            $carry = \intdiv($x, 10);
            $i--;
            $j--;
        }

        return self::trim(\strrev($out));
    }

    /** Exact ($dec * $m) for canonical decimal strings and small $m. */
    public static function mulInt(string $dec, int $m): string
    {
        $dec = self::trim($dec);
        $out = '';
        $carry = 0;
        for ($i = \strlen($dec) - 1; $i >= 0; $i--) {
            $x = ((int) $dec[$i]) * $m + $carry;
            $out .= \chr(48 + ($x % 10));
            $carry = \intdiv($x, 10);
        }
        while ($carry > 0) {
            $out .= \chr(48 + ($carry % 10));
            $carry = \intdiv($carry, 10);
        }

        return self::trim(\strrev($out));
    }

    /**
     * Big-endian 8-byte two's-complement encoding of a signed i64 given as
     * a PHP int (used for the MessagePack timestamp96 / int64 carriers).
     */
    public static function i64ToBytes8(int $n): string
    {
        if ($n >= 0) {
            return self::toBytes8((string) $n);
        }
        // magnitude as a decimal string (no int negation: -PHP_INT_MIN
        // overflows the positive int range)
        $mag = \substr((string) $n, 1);

        return self::toBytes8(self::decSub('18446744073709551616', $mag));
    }

    public static function trim(string $dec): string
    {
        $t = \ltrim($dec, '0');

        return $t === '' ? '0' : $t;
    }

    /** Returns ($dec * $mul + $add) as a canonical decimal string. */
    private static function mulAddSmall(string $dec, int $mul, int $add): string
    {
        $dec = self::trim($dec);
        $out = '';
        $carry = $add;
        for ($i = \strlen($dec) - 1; $i >= 0; $i--) {
            $x = ((int) $dec[$i]) * $mul + $carry;
            $out .= \chr(48 + ($x % 10));
            $carry = \intdiv($x, 10);
        }
        while ($carry > 0) {
            $out .= \chr(48 + ($carry % 10));
            $carry = \intdiv($carry, 10);
        }

        return \strrev($out);
    }

    /** Returns [quotient, remainder] of $dec / $d for small $d. */
    private static function divModSmall(string $dec, int $d): array
    {
        $dec = self::trim($dec);
        $q = '';
        $r = 0;
        for ($i = 0, $n = \strlen($dec); $i < $n; $i++) {
            $x = $r * 10 + (int) $dec[$i];
            $q .= \chr(48 + \intdiv($x, $d));
            $r = $x % $d;
        }
        $q = self::trim($q);

        return [$q, $r];
    }
}

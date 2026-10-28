<?php

declare(strict_types=1);

namespace CodingLombok\LombokSerde;

/**
 * MessagePack codec — canonical, byte-precise (see SPEC).
 *
 * Encoding pins: minimal-length integer/str/bin/array/map families; floats
 * always float64; timestamps use timestamp32/64/96 per the spec's compact
 * forms; ext types other than -1 are rejected (fail-closed).
 */
final class Msgpack
{
    public static function decode(string $data, ?MsgPackOptions $opts = null): Value
    {
        $limit = $opts !== null && $opts->depthLimit !== 0
            ? $opts->depthLimit
            : Json::DEFAULT_DEPTH_LIMIT;
        $p = new MpParser($data, $limit);
        $v = $p->readValue(1);
        if ($p->i !== \strlen($data)) {
            throw new SerdeError(
                SerdeErrorCode::MP_TRAILING,
                'trailing bytes after the top-level value',
                $p->i,
            );
        }

        return $v;
    }

    public static function encode(Value $v, ?MsgPackOptions $opts = null): string
    {
        $limit = $opts !== null && $opts->depthLimit !== 0
            ? $opts->depthLimit
            : Json::DEFAULT_DEPTH_LIMIT;
        $out = '';
        self::mpWrite($out, $v, 1, $limit);

        return $out;
    }

    /** @internal */
    public static function mpWrite(string &$out, Value $v, int $depth, int $limit): void
    {
        switch ($v->kind) {
            case Value::KIND_NULL:
                $out .= "\xC0";

                return;
            case Value::KIND_BOOL:
                $out .= $v->bool ? "\xC3" : "\xC2";

                return;
            case Value::KIND_INT:
                self::mpWriteInt($out, $v->int);

                return;
            case Value::KIND_UINT:
                $s = $v->uintStr;
                if (U64::cmp($s, '128') < 0) {
                    $out .= \chr((int) $s);
                } elseif (U64::cmp($s, '256') < 0) {
                    $out .= "\xCC" . \chr((int) $s);
                } elseif (U64::cmp($s, '65536') < 0) {
                    $out .= "\xCD" . self::be16((int) $s);
                } elseif (U64::cmp($s, '4294967296') < 0) {
                    $out .= "\xCE" . self::be32FromDec($s);
                } else {
                    $out .= "\xCF" . self::be64($s);
                }

                return;
            case Value::KIND_FLOAT:
                $out .= "\xCB" . self::float64bits($v->float);

                return;
            case Value::KIND_STR:
                $sb = $v->str;
                $n = \strlen($sb);
                if ($n <= 31) {
                    $out .= \chr(0xA0 | $n) . $sb;
                } elseif ($n <= 0xFF) {
                    $out .= "\xD9" . \chr($n) . $sb;
                } elseif ($n <= 0xFFFF) {
                    $out .= "\xDA" . self::be16($n) . $sb;
                } else {
                    $out .= "\xDB" . self::be32($n) . $sb;
                }

                return;
            case Value::KIND_BYTES:
                $n = \strlen($v->bytes);
                if ($n <= 0xFF) {
                    $out .= "\xC4" . \chr($n) . $v->bytes;
                } elseif ($n <= 0xFFFF) {
                    $out .= "\xC5" . self::be16($n) . $v->bytes;
                } else {
                    $out .= "\xC6" . self::be32($n) . $v->bytes;
                }

                return;
            case Value::KIND_ARRAY:
                if ($depth > $limit) {
                    throw new SerdeError(SerdeErrorCode::MP_DEPTH, 'depth limit exceeded');
                }
                $n = \count($v->array);
                if ($n <= 15) {
                    $out .= \chr(0x90 | $n);
                } elseif ($n <= 0xFFFF) {
                    $out .= "\xDC" . self::be16($n);
                } else {
                    $out .= "\xDD" . self::be32($n);
                }
                foreach ($v->array as $x) {
                    self::mpWrite($out, $x, $depth + 1, $limit);
                }

                return;
            case Value::KIND_TABLE:
                if ($depth > $limit) {
                    throw new SerdeError(SerdeErrorCode::MP_DEPTH, 'depth limit exceeded');
                }
                $n = \count($v->table);
                if ($n <= 15) {
                    $out .= \chr(0x80 | $n);
                } elseif ($n <= 0xFFFF) {
                    $out .= "\xDE" . self::be16($n);
                } else {
                    $out .= "\xDF" . self::be32($n);
                }
                foreach ($v->table as $e) {
                    self::mpWrite($out, Value::str($e->key), $depth, $limit);
                    self::mpWrite($out, $e->value, $depth + 1, $limit);
                }

                return;
            case Value::KIND_DATETIME:
                self::mpWriteDatetime($out, $v->datetime);

                return;
            default:
                throw new SerdeError(SerdeErrorCode::MP_UNEXPECTED, 'unsupported value kind: ' . $v->kind);
        }
    }

    /** @internal */
    public static function mpWriteInt(string &$out, int $n): void
    {
        if ($n >= 0 && $n <= 0x7F) {
            $out .= \chr($n);

            return;
        }
        if ($n > 0) {
            if ($n <= 0xFF) {
                $out .= "\xCC" . \chr($n);
            } elseif ($n <= 0xFFFF) {
                $out .= "\xCD" . self::be16($n);
            } elseif ($n <= 0xFFFFFFFF) {
                $out .= "\xCE" . self::be32($n);
            } else {
                $out .= "\xCF" . self::be64((string) $n);
            }

            return;
        }
        if ($n >= -32) {
            $out .= \chr(0xE0 | ($n + 32));

            return;
        }
        if ($n >= -128) {
            $out .= "\xD0" . \chr($n & 0xFF);

            return;
        }
        if ($n >= -32768) {
            $out .= "\xD1" . self::be16($n & 0xFFFF);

            return;
        }
        if ($n >= -2147483648) {
            $out .= "\xD2" . self::be32($n & 0xFFFFFFFF);

            return;
        }
        $out .= "\xD3" . self::be64i($n);
    }

    private static function mpWriteDatetime(string &$out, Datetime $dt): void
    {
        if ($dt->kind !== 'offset') {
            throw new SerdeError(
                SerdeErrorCode::MP_DATETIME,
                'only Offset datetimes map to MessagePack timestamps',
            );
        }
        $parsed = Calendar::parseOffsetDatetime($dt->raw);
        if ($parsed === null) {
            throw new SerdeError(
                SerdeErrorCode::MP_DATETIME,
                'datetime raw text is not a valid RFC 3339 offset datetime',
            );
        }
        ['sec' => $sec, 'ns' => $ns] = $parsed;
        if ($ns === 0 && $sec >= 0 && $sec <= 0xFFFFFFFF) {
            $out .= "\xD6\xFF" . self::be32($sec);
        } elseif ($sec >= 0 && $sec <= (1 << 34) - 1) {
            // bits = ns * 2^34 + sec (string math: the product overflows
            // PHP's 64-bit signed int)
            $bits = U64::decAdd(U64::mulInt((string) $ns, 1 << 34), (string) $sec);
            $out .= "\xD7\xFF" . self::be64($bits);
        } else {
            $out .= "\xC7\x0C\xFF" . self::be32($ns) . self::be64i($sec);
        }
    }

    // --- binary helpers -----------------------------------------------------

    /** @internal big-endian uint16 of a PHP int (0..65535). */
    public static function be16(int $n): string
    {
        return \pack('n', $n & 0xFFFF);
    }

    /** @internal big-endian uint32 of a PHP int (0..4294967295). */
    public static function be32(int $n): string
    {
        return \pack('N', $n & 0xFFFFFFFF);
    }

    /** @internal big-endian uint32 of a decimal string. */
    public static function be32FromDec(string $dec): string
    {
        return \substr(U64::toBytes8(U64::trim($dec)), 4, 4);
    }

    /** @internal big-endian uint64 of a decimal string. */
    public static function be64(string $dec): string
    {
        return U64::toBytes8(U64::trim($dec));
    }

    /** @internal big-endian uint64 of a signed i64 (two's complement). */
    public static function be64i(int $n): string
    {
        return U64::i64ToBytes8($n);
    }

    /** @internal canonical float64 big-endian bytes (quiet NaN pinned). */
    public static function float64bits(float $f): string
    {
        if (\is_nan($f)) {
            // SPEC: NaN always encodes as the canonical quiet NaN
            return "\x7F\xF8\x00\x00\x00\x00\x00\x00";
        }
        $bin = \pack('E', $f);

        return $bin;
    }
}

/** Options for the MessagePack codec. */
final class MsgPackOptions
{
    public function __construct(
        public readonly int $depthLimit = Json::DEFAULT_DEPTH_LIMIT,
    ) {
    }
}

/** @internal MessagePack parser over a byte string. */
final class MpParser
{
    public int $i = 0;

    public function __construct(
        private readonly string $b,
        private readonly int $limit,
    ) {
    }

    private function need(int $n): void
    {
        if ($this->i + $n > \strlen($this->b)) {
            throw new SerdeError(
                SerdeErrorCode::MP_TRUNCATED,
                'unexpected end of input',
                \strlen($this->b),
            );
        }
    }

    private function take(int $n): string
    {
        $this->need($n);
        $s = \substr($this->b, $this->i, $n);
        $this->i += $n;

        return $s;
    }

    public function readValue(int $depth): Value
    {
        $raw = $this->take(1);
        $m = \ord($raw);
        if ($m <= 0x7F) {
            return Value::int($m);
        }
        if ($m >= 0xE0) {
            return Value::int($m - 256); // int8 semantics
        }
        if ($m >= 0x80 && $m <= 0x8F) {
            return $this->readMap($m & 0x0F, $depth);
        }
        if ($m >= 0x90 && $m <= 0x9F) {
            return $this->readArray($m & 0x0F, $depth);
        }
        if ($m >= 0xA0 && $m <= 0xBF) {
            return Value::str($this->readStr($m & 0x1F));
        }
        switch ($m) {
            case 0xC0:
                return Value::null();
            case 0xC1:
                throw new SerdeError(SerdeErrorCode::MP_UNEXPECTED, 'reserved type code 0xc1', $this->i - 1);
            case 0xC2:
                return Value::bool(false);
            case 0xC3:
                return Value::bool(true);
            case 0xC4:
            case 0xC5:
            case 0xC6:
                $n = $this->readLen($m - 0xC4, 1);

                return Value::bytes($this->take($n));
            case 0xC7:
            case 0xC8:
            case 0xC9:
                $n = $this->readLen($m - 0xC7, 1);

                return $this->readExt($n);
            case 0xCA:
                $bs = $this->take(4);
                $f = \unpack('G', $bs)[1];

                return Value::float((float) $f);
            case 0xCB:
                $bs = $this->take(8);
                $f = \unpack('E', $bs)[1];

                return Value::float((float) $f);
            case 0xCC:
            case 0xCD:
            case 0xCE:
            case 0xCF:
                $n = 1 << ($m - 0xCC);
                $bs = $this->take($n);
                $padded = \str_pad($bs, 8, "\0", \STR_PAD_LEFT);

                return self::intOrUint($padded);
            case 0xD0:
            case 0xD1:
            case 0xD2:
            case 0xD3:
                $n = 1 << ($m - 0xD0);
                $bs = $this->take($n);
                $v = self::beToI64(\str_pad($bs, 8, "\0", \STR_PAD_LEFT));
                if ((\ord($bs[0]) & 0x80) !== 0) {
                    // sign-extend from the actual width
                    $v -= 1 << (8 * $n);
                }

                return Value::int($v);
            case 0xD4:
            case 0xD5:
            case 0xD6:
            case 0xD7:
            case 0xD8:
                $n = 1 << ($m - 0xD4);

                return $this->readExt($n);
            case 0xD9:
            case 0xDA:
            case 0xDB:
                $n = $this->readLen($m - 0xD9, 1);

                return Value::str($this->readStr($n));
            case 0xDC:
            case 0xDD:
                $n = $this->readLen($m - 0xDB, 2);

                return $this->readArray($n, $depth);
            case 0xDE:
            case 0xDF:
                $n = $this->readLen($m - 0xDD, 2);

                return $this->readMap($n, $depth);
        }
        throw new SerdeError(SerdeErrorCode::MP_UNEXPECTED, 'invalid type code', $this->i - 1);
    }

    private function readLen(int $sizeClass, int $minBytes): int
    {
        if ($sizeClass === 0) {
            $bs = $this->take(1);
            $n = \ord($bs);
        } elseif ($sizeClass === 1) {
            $bs = $this->take(2);
            $n = (\ord($bs[0]) << 8) | \ord($bs[1]);
        } else {
            $bs = $this->take(4);
            $n = ((\ord($bs[0]) << 24) | (\ord($bs[1]) << 16) | (\ord($bs[2]) << 8) | \ord($bs[3]));
            // PHP ints are 64-bit; keep the value unsigned
            $n = (int) \sprintf('%u', $n);
        }
        if ($n < $minBytes) {
            throw new SerdeError(
                SerdeErrorCode::MP_UNEXPECTED,
                'length field below the minimum for this type',
                $this->i,
            );
        }

        return $n;
    }

    private static function intOrUint(string $be8): Value
    {
        $dec = U64::fromBytes($be8);
        if (U64::cmp($dec, '9223372036854775807') <= 0) {
            return Value::int((int) $dec);
        }

        return Value::uint($dec);
    }

    /** Unsigned big-endian 8 bytes to a signed i64 (two's complement). */
    private static function beToI64(string $be8): int
    {
        return self::decToI64(U64::fromBytes($be8));
    }

    private function readStr(int $n): string
    {
        $start = $this->i;
        $bs = $this->take($n);
        if (!self::isValidUtf8($bs)) {
            throw new SerdeError(SerdeErrorCode::MP_UTF8, 'invalid UTF-8 in string', $start);
        }

        return $bs;
    }

    /** @internal */
    public static function isValidUtf8(string $s): bool
    {
        return Json::utf8FirstBadOffset($s) === -1;
    }

    private function readArray(int $n, int $depth): Value
    {
        if ($depth > $this->limit) {
            throw new SerdeError(SerdeErrorCode::MP_DEPTH, 'depth limit exceeded', $this->i);
        }
        $items = [];
        for ($j = 0; $j < $n; $j++) {
            $items[] = $this->readValue($depth + 1);
        }

        return Value::array($items);
    }

    private function readMap(int $n, int $depth): Value
    {
        if ($depth > $this->limit) {
            throw new SerdeError(SerdeErrorCode::MP_DEPTH, 'depth limit exceeded', $this->i);
        }
        $pairs = [];
        for ($j = 0; $j < $n; $j++) {
            $k = $this->readValue($depth + 1);
            if ($k->kind !== Value::KIND_STR) {
                throw new SerdeError(SerdeErrorCode::MP_UNEXPECTED, 'map key is not a string', $this->i);
            }
            $v = $this->readValue($depth + 1);
            $pairs[] = new TableEntry($k->str, $v);
        }
        try {
            return Value::table($pairs);
        } catch (SerdeError $e) {
            if ($e->code() === SerdeErrorCode::TABLE_DUPLICATE) {
                throw new SerdeError(SerdeErrorCode::MP_DUPLICATE, 'duplicate map key', $this->i);
            }
            throw $e;
        }
    }

    private function readExt(int $n): Value
    {
        $tb = $this->take(1);
        $etype = \ord($tb) >= 0x80 ? \ord($tb) - 256 : \ord($tb);
        if ($etype !== -1) {
            throw new SerdeError(SerdeErrorCode::MP_EXT, 'unsupported extension type', $this->i - 1);
        }
        switch ($n) {
            case 4:
                $bs = $this->take(4);
                $sec = \unpack('N', $bs)[1];

                return Calendar::datetimeFromTimestamp($sec, 0);
            case 8:
                $bs = $this->take(8);
                $bits = U64::fromBytes($bs);
                // ns = bits >> 34; sec = bits & (2^34 - 1)
                [$ns, $sec] = self::divModBig($bits, 1 << 34);
                if (U64::cmp($ns, '999999999') > 0) {
                    throw new SerdeError(SerdeErrorCode::MP_UNEXPECTED, 'nanoseconds out of range', $this->i - 8);
                }

                return Calendar::datetimeFromTimestamp((int) $sec, (int) $ns);
            case 12:
                $bs = $this->take(12);
                $ns = \unpack('N', \substr($bs, 0, 4))[1];
                $secDec = U64::fromBytes(\substr($bs, 4, 8));
                if ($ns > 999_999_999) {
                    throw new SerdeError(SerdeErrorCode::MP_UNEXPECTED, 'nanoseconds out of range', $this->i - 12);
                }

                return Calendar::datetimeFromTimestamp(self::decToI64($secDec), $ns);
        }
        throw new SerdeError(SerdeErrorCode::MP_EXT, 'unsupported timestamp payload length', $this->i - 1);
    }

    /**
     * Long division of a decimal string by a small (int-range) divisor.
     *
     * @return array{0:string,1:int} [quotient, remainder]
     */
    private static function divModBig(string $dec, int $d): array
    {
        $dec = U64::trim($dec);
        $q = '';
        $r = 0;
        for ($i = 0, $n = \strlen($dec); $i < $n; $i++) {
            $x = $r * 10 + (int) $dec[$i];
            $q .= \chr(48 + \intdiv($x, $d));
            $r = $x % $d;
        }

        return [U64::trim($q), $r];
    }

    /** Signed i64 two's-complement value of a u64 decimal string. */
    private static function decToI64(string $dec): int
    {
        if (U64::cmp($dec, '9223372036854775807') <= 0) {
            return (int) $dec;
        }
        $mag = U64::decSub('18446744073709551616', $dec);
        if ($mag === '9223372036854775808') {
            return \PHP_INT_MIN; // magnitude 2^63 exceeds the positive range
        }

        return -((int) $mag);
    }
}

/**
 * Calendar math (identical integer arithmetic in every port) and the RFC
 * 3339 offset-datetime parser used by the MessagePack timestamp mapping.
 */
final class Calendar
{
    public static function datetimeFromTimestamp(int $sec, int $ns): Value
    {
        return Value::datetime('offset', self::formatTimestamp($sec, $ns));
    }

    /** Days since 1970-01-01 (Howard Hinnant's algorithm). */
    public static function daysFromCivil(int $y, int $m, int $d): int
    {
        $yy = $m <= 2 ? $y - 1 : $y;
        $era = \intdiv($yy, 400);
        if ($yy < 0 && $yy % 400 !== 0) {
            $era = \intdiv($yy - 399, 400);
        }
        $yoe = $yy - $era * 400;
        $mp = $m <= 2 ? $m + 9 : $m - 3;
        $doy = \intdiv(153 * $mp + 2, 5) + $d - 1;
        $doe = $yoe * 365 + \intdiv($yoe, 4) - \intdiv($yoe, 100) + $doy;

        return $era * 146097 + $doe - 719468;
    }

    /** Civil date for days since 1970-01-01. @return array{int,int,int} */
    public static function civilFromDays(int $z): array
    {
        $zz = $z + 719468;
        $era = \intdiv($zz, 146097);
        if ($zz < 0 && $zz % 146097 !== 0) {
            $era = \intdiv($zz - 146096, 146097);
        }
        $doe = $zz - $era * 146097;
        $yoe = \intdiv($doe - \intdiv($doe, 1460) + \intdiv($doe, 36524) - \intdiv($doe, 146096), 365);
        $y = $yoe + $era * 400;
        $doy = $doe - (365 * $yoe + \intdiv($yoe, 4) - \intdiv($yoe, 100));
        $mp = \intdiv(5 * $doy + 2, 153);
        $d = $doy - \intdiv(153 * $mp + 2, 5) + 1;
        $m = $mp >= 10 ? $mp - 9 : $mp + 3;
        if ($m <= 2) {
            $y++;
        }

        return [$y, $m, $d];
    }

    /**
     * Parses an RFC 3339 offset datetime.
     *
     * @return array{sec:int,ns:int}|null
     */
    public static function parseOffsetDatetime(string $raw): ?array
    {
        $b = $raw;
        $n = \strlen($b);
        $digits = static function (int $from, int $to) use ($b, $n): ?int {
            if ($from < 0 || $to > $n) {
                return null;
            }
            $v = 0;
            for ($j = $from; $j < $to; $j++) {
                $c = $b[$j];
                if ($c < '0' || $c > '9') {
                    return null;
                }
                $v = $v * 10 + (int) $c;
            }

            return $v;
        };
        if ($n < 20) {
            return null;
        }
        $sep = \ord($b[10]);
        if (!($b[4] === '-' && $b[7] === '-'
            && ($sep === \ord('T') || $sep === \ord('t') || $sep === 0x20)
            && $b[13] === ':' && $b[16] === ':')
        ) {
            return null;
        }
        $y = $digits(0, 4);
        $mo = $digits(5, 7);
        $d = $digits(8, 10);
        $h = $digits(11, 13);
        $mi = $digits(14, 16);
        $sv = $digits(17, 19);
        if ($y === null || $mo === null || $d === null || $h === null || $mi === null || $sv === null) {
            return null;
        }
        $i = 19;
        $ns = 0;
        if ($i < $n && $b[$i] === '.') {
            $i++;
            $start = $i;
            while ($i < $n && $b[$i] >= '0' && $b[$i] <= '9') {
                $i++;
            }
            if ($i === $start) {
                return null;
            }
            $scale = 100000000;
            for ($j = $start; $j < $i && $scale > 0; $j++) {
                $ns += ((int) $b[$j]) * $scale;
                $scale = \intdiv($scale, 10);
            }
        }
        if ($sv === 60) {
            return null; // leap seconds are not representable
        }
        if (!($mo >= 1 && $mo <= 12 && $d >= 1 && $d <= 31 && $h <= 23 && $mi <= 59)) {
            return null;
        }
        if ($i < $n && ($b[$i] === 'Z' || $b[$i] === 'z')) {
            if ($i + 1 !== $n) {
                return null;
            }
            $sec = self::daysFromCivil($y, $mo, $d) * 86400 + $h * 3600 + $mi * 60 + $sv;
        } elseif ($i + 5 < $n && ($b[$i] === '+' || $b[$i] === '-') && $b[$i + 3] === ':') {
            if ($i + 6 !== $n) {
                return null;
            }
            $oh = $digits($i + 1, $i + 3);
            $om = $digits($i + 4, $i + 6);
            if ($oh === null || $om === null || $oh > 23 || $om > 59) {
                return null;
            }
            $off = $oh * 3600 + $om * 60;
            $base = self::daysFromCivil($y, $mo, $d) * 86400 + $h * 3600 + $mi * 60 + $sv;
            $sec = $b[$i] === '+' ? $base - $off : $base + $off;
        } else {
            return null;
        }

        return ['sec' => $sec, 'ns' => $ns];
    }

    /** Renders epoch seconds + nanoseconds as canonical `...Z`. */
    public static function formatTimestamp(int $sec, int $ns): string
    {
        $days = \intdiv($sec, 86400);
        $rem = $sec % 86400;
        if ($rem < 0) {
            $rem += 86400;
            $days--;
        }
        [$y, $mo, $d] = self::civilFromDays($days);
        $h = \intdiv($rem, 3600);
        $mi = \intdiv($rem % 3600, 60);
        $s = $rem % 60;
        $frac = '';
        if ($ns !== 0) {
            $frac = '.' . \rtrim(\str_pad((string) $ns, 9, '0', \STR_PAD_LEFT), '0');
        }

        return self::pad4($y) . '-' . self::pad2($mo) . '-' . self::pad2($d)
            . 'T' . self::pad2($h) . ':' . self::pad2($mi) . ':' . self::pad2($s) . $frac . 'Z';
    }

    private static function pad2(int $v): string
    {
        return $v < 10 ? '0' . $v : (string) $v;
    }

    private static function pad4(int $v): string
    {
        $neg = $v < 0;
        $s = (string) \abs($v);
        $s = \str_pad($s, 4, '0', \STR_PAD_LEFT);

        return $neg ? '-' . $s : $s;
    }
}

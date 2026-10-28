<?php

declare(strict_types=1);

namespace CodingLombok\LombokSerde;

/**
 * TOML v1.0 codec — canonical, byte-precise (see SPEC).
 */
final class Toml
{
    public static function decode(string $data, ?TomlOptions $opts = null): Value
    {
        $limit = $opts !== null && $opts->depthLimit !== 0
            ? $opts->depthLimit
            : Json::DEFAULT_DEPTH_LIMIT;
        $bad = Json::utf8FirstBadOffset($data);
        if ($bad !== -1) {
            throw new SerdeError(SerdeErrorCode::TOML_UTF8, 'invalid UTF-8', $bad);
        }
        $p = new TomlParser($data, $limit);

        return $p->parse();
    }

    /** Encodes a table value as canonical TOML. The root must be a table. */
    public static function encode(Value $v, ?TomlOptions $opts = null): string
    {
        $limit = $opts !== null && $opts->depthLimit !== 0
            ? $opts->depthLimit
            : Json::DEFAULT_DEPTH_LIMIT;
        if ($v->kind !== Value::KIND_TABLE) {
            throw new SerdeError(SerdeErrorCode::TOML_ROOT, 'TOML documents encode from a table root');
        }
        $out = '';
        self::tomlEmitTable($v, [], $out, 1, $limit);

        return $out;
    }

    // --- serializer -----------------------------------------------------------

    public static function isAot(Value $v): bool
    {
        if ($v->kind !== Value::KIND_ARRAY || \count($v->array) === 0) {
            return false;
        }
        foreach ($v->array as $x) {
            if ($x->kind !== Value::KIND_TABLE) {
                return false;
            }
        }

        return true;
    }

    /** @param list<string> $path */
    private static function tomlEmitTable(Value $tbl, array $path, string &$out, int $depth, int $limit): void
    {
        if ($depth > $limit) {
            throw new SerdeError(SerdeErrorCode::TOML_DEPTH, 'depth limit exceeded');
        }
        $scalars = [];
        $subtables = [];
        $aots = [];
        foreach ($tbl->table as $e) {
            if ($e->value->kind === Value::KIND_TABLE) {
                $subtables[] = $e;
            } elseif (self::isAot($e->value)) {
                $aots[] = $e;
            } else {
                $scalars[] = $e;
            }
        }
        $prefix = '';
        foreach ($path as $j => $seg) {
            if ($j > 0) {
                $prefix .= '.';
            }
            $prefix .= self::tomlKey($seg);
        }
        foreach ($scalars as $e) {
            $out .= self::tomlKey($e->key) . ' = ' . self::tomlInline($e->value, $depth, $limit) . "\n";
        }
        foreach ($subtables as $e) {
            $header = $prefix !== '' ? '[' . $prefix . '.' . self::tomlKey($e->key) . ']'
                : '[' . self::tomlKey($e->key) . ']';
            $out .= $header . "\n";
            $sub = [...$path, $e->key];
            self::tomlEmitTable($e->value, $sub, $out, $depth + 1, $limit);
        }
        foreach ($aots as $e) {
            foreach ($e->value->array as $el) {
                $header = $prefix !== '' ? '[[' . $prefix . '.' . self::tomlKey($e->key) . ']]'
                    : '[[' . self::tomlKey($e->key) . ']]';
                $out .= $header . "\n";
                $sub = [...$path, $e->key];
                self::tomlEmitTable($el, $sub, $out, $depth + 1, $limit);
            }
        }
    }

    public static function tomlKey(string $k): string
    {
        $bare = $k !== '';
        for ($i = 0, $n = \strlen($k); $i < $n; $i++) {
            if (!self::isBareKeyByte(\ord($k[$i]))) {
                $bare = false;
                break;
            }
        }
        if ($bare) {
            return $k;
        }

        return self::tomlQuote($k);
    }

    public static function tomlQuote(string $s): string
    {
        $out = '"';
        $n = \strlen($s);
        for ($i = 0; $i < $n; $i++) {
            $c = $s[$i];
            switch ($c) {
                case '"':
                    $out .= '\\"';
                    break;
                case '\\':
                    $out .= '\\\\';
                    break;
                case "\x08":
                    $out .= '\b';
                    break;
                case "\t":
                    $out .= '\t';
                    break;
                case "\n":
                    $out .= '\n';
                    break;
                case "\x0C":
                    $out .= '\f';
                    break;
                case "\r":
                    $out .= '\r';
                    break;
                default:
                    $o = \ord($c);
                    if ($o < 0x20 || $o === 0x7F) {
                        $out .= Json::formatU4($o);
                    } else {
                        $out .= $c;
                    }
            }
        }
        $out .= '"';

        return $out;
    }

    public static function tomlInline(Value $v, int $depth, int $limit): string
    {
        switch ($v->kind) {
            case Value::KIND_NULL:
                throw new SerdeError(SerdeErrorCode::TOML_SYNTAX, 'null is not a TOML value');
            case Value::KIND_BOOL:
                return $v->bool ? 'true' : 'false';
            case Value::KIND_INT:
                return (string) $v->int;
            case Value::KIND_UINT:
                if (U64::gt($v->uintStr, '9223372036854775807')) {
                    throw new SerdeError(SerdeErrorCode::TOML_SYNTAX, 'unsigned value out of TOML 64-bit signed range');
                }

                return $v->uintStr;
            case Value::KIND_FLOAT:
                if (\is_nan($v->float)) {
                    return 'nan';
                }
                if (\is_infinite($v->float)) {
                    return $v->float > 0 ? 'inf' : '-inf';
                }

                return FloatFormat::render($v->float);
            case Value::KIND_STR:
                return self::tomlQuote($v->str);
            case Value::KIND_DATETIME:
                if (!DatetimeCheck::ok($v->datetime->raw, $v->datetime->kind)) {
                    throw new SerdeError(SerdeErrorCode::TOML_DATETIME, 'invalid datetime raw text');
                }

                return $v->datetime->raw;
            case Value::KIND_BYTES:
                throw new SerdeError(SerdeErrorCode::TOML_BYTES, 'Bytes values cannot be encoded as TOML');
            case Value::KIND_ARRAY:
                if ($depth > $limit) {
                    throw new SerdeError(SerdeErrorCode::TOML_DEPTH, 'depth limit exceeded');
                }
                $parts = [];
                foreach ($v->array as $x) {
                    $parts[] = self::tomlInline($x, $depth + 1, $limit);
                }

                return '[' . \implode(', ', $parts) . ']';
            case Value::KIND_TABLE:
                if ($depth > $limit) {
                    throw new SerdeError(SerdeErrorCode::TOML_DEPTH, 'depth limit exceeded');
                }
                if (\count($v->table) === 0) {
                    return '{}';
                }
                $parts = [];
                foreach ($v->table as $e) {
                    $s = self::tomlInline($e->value, $depth + 1, $limit);
                    $parts[] = self::tomlKey($e->key) . ' = ' . $s;
                }

                return '{ ' . \implode(', ', $parts) . ' }';
            default:
                throw new SerdeError(SerdeErrorCode::TOML_SYNTAX, 'unsupported value');
        }
    }

    /** @internal */
    public static function isBareKeyByte(int $c): bool
    {
        return ($c >= 0x61 && $c <= 0x7A) || ($c >= 0x41 && $c <= 0x5A)
            || ($c >= 0x30 && $c <= 0x39) || $c === 0x5F || $c === 0x2D;
    }
}

/** Options for the TOML codec. */
final class TomlOptions
{
    public function __construct(
        public readonly int $depthLimit = Json::DEFAULT_DEPTH_LIMIT,
    ) {
    }
}

/** @internal datetime shape validation (mirrors Go datetimeOK). */
final class DatetimeCheck
{
    public static function ok(string $text, string $kind): bool
    {
        $b = $text;
        $n = \strlen($b);
        $seg = static function (int $from, int $to) use ($b, $n): ?int {
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
        switch ($kind) {
            case 'date':
                if ($n !== 10 || $b[4] !== '-' || $b[7] !== '-') {
                    return false;
                }
                $mo = $seg(5, 7);
                $d = $seg(8, 10);
                $y = $seg(0, 4);

                return $y !== null && $mo !== null && $d !== null
                    && $mo >= 1 && $mo <= 12 && $d >= 1 && $d <= 31;
            case 'time':
                if ($n < 8 || $b[2] !== ':' || $b[5] !== ':') {
                    return false;
                }
                $h = $seg(0, 2);
                $mi = $seg(3, 5);
                $se = $seg(6, 8);
                if ($h === null || $mi === null || $se === null || $h > 23 || $mi > 59 || $se > 60) {
                    return false;
                }
                if ($n === 8) {
                    return true;
                }
                if ($n <= 9 || $b[8] !== '.') {
                    return false;
                }
                for ($j = 9; $j < $n; $j++) {
                    if ($b[$j] < '0' || $b[$j] > '9') {
                        return false;
                    }
                }

                return true;
            case 'localdt':
            case 'offset':
                $minLen = $kind === 'offset' ? 20 : 19;
                if ($n < $minLen) {
                    return false;
                }
                $sep = \ord($b[10]);
                if (!($b[4] === '-' && $b[7] === '-'
                    && ($sep === \ord('T') || $sep === \ord('t') || $sep === 0x20)
                    && $b[13] === ':' && $b[16] === ':')
                ) {
                    return false;
                }
                $mo = $seg(5, 7);
                $d = $seg(8, 10);
                $h = $seg(11, 13);
                $mi = $seg(14, 16);
                $se = $seg(17, 19);
                if ($mo === null || $d === null || $h === null || $mi === null || $se === null) {
                    return false;
                }
                if (!($mo >= 1 && $mo <= 12 && $d >= 1 && $d <= 31 && $h <= 23 && $mi <= 59 && $se <= 60)) {
                    return false;
                }
                $i = 19;
                if ($i < $n && $b[$i] === '.') {
                    $i++;
                    $start = $i;
                    while ($i < $n && $b[$i] >= '0' && $b[$i] <= '9') {
                        $i++;
                    }
                    if ($i === $start) {
                        return false;
                    }
                }
                if ($kind === 'localdt') {
                    return $i === $n;
                }
                if ($i === $n) {
                    return false;
                }
                if ($b[$i] === 'Z' || $b[$i] === 'z') {
                    return $i + 1 === $n;
                }
                if ($i + 6 !== $n || ($b[$i] !== '+' && $b[$i] !== '-') || $b[$i + 3] !== ':') {
                    return false;
                }
                $zh = $seg($i + 1, $i + 3);
                $zm = $seg($i + 4, $i + 6);

                return $zh !== null && $zm !== null && $zh <= 23 && $zm <= 59;
        }

        return false;
    }
}

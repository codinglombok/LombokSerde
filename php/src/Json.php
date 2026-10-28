<?php

declare(strict_types=1);

namespace CodingLombok\LombokSerde;

/**
 * JSON codec (RFC 8259) — canonical, byte-precise (see SPEC).
 */
final class Json
{
    /** Default maximum container nesting for every format and port. */
    public const DEFAULT_DEPTH_LIMIT = 128;

    public static function decode(string $data, ?JsonOptions $opts = null): Value
    {
        $limit = $opts !== null && $opts->depthLimit !== 0
            ? $opts->depthLimit
            : self::DEFAULT_DEPTH_LIMIT;
        $bad = self::utf8FirstBadOffset($data);
        if ($bad !== -1) {
            throw new SerdeError(SerdeErrorCode::JSON_UTF8, 'invalid UTF-8', $bad);
        }
        $p = new JsonParser($data, $limit);
        $v = $p->parseValue(1);
        $p->skipWs();
        if ($p->i !== \strlen($data)) {
            throw new SerdeError(
                SerdeErrorCode::JSON_TRAILING,
                'trailing characters after the top-level value',
                $p->i,
            );
        }

        return $v;
    }

    /** Encodes a value as canonical compact JSON. */
    public static function encode(Value $v, ?JsonOptions $opts = null): string
    {
        $limit = $opts !== null && $opts->depthLimit !== 0
            ? $opts->depthLimit
            : self::DEFAULT_DEPTH_LIMIT;
        $out = '';
        self::jsonWrite($out, $v, 1, $limit);

        return $out;
    }

    /** @internal */
    public static function utf8FirstBadOffset(string $b): int
    {
        $n = \strlen($b);
        $i = 0;
        while ($i < $n) {
            $c = \ord($b[$i]);
            if ($c < 0x80) {
                $i++;
                continue;
            }
            if ($c >= 0xC2 && $c <= 0xDF) {
                $ln = 2;
                $lo = 0x80;
                $hi = 0xBF;
            } elseif ($c === 0xE0) {
                $ln = 3;
                $lo = 0xA0;
                $hi = 0xBF;
            } elseif ($c >= 0xE1 && $c <= 0xEC) {
                $ln = 3;
                $lo = 0x80;
                $hi = 0xBF;
            } elseif ($c === 0xED) {
                $ln = 3;
                $lo = 0x80;
                $hi = 0x9F;
            } elseif ($c >= 0xEE && $c <= 0xEF) {
                $ln = 3;
                $lo = 0x80;
                $hi = 0xBF;
            } elseif ($c === 0xF0) {
                $ln = 4;
                $lo = 0x90;
                $hi = 0xBF;
            } elseif ($c >= 0xF1 && $c <= 0xF3) {
                $ln = 4;
                $lo = 0x80;
                $hi = 0xBF;
            } elseif ($c === 0xF4) {
                $ln = 4;
                $lo = 0x80;
                $hi = 0x8F;
            } else {
                return $i;
            }
            if ($i + $ln > $n) {
                return $i;
            }
            for ($j = 1; $j < $ln; $j++) {
                $cc = \ord($b[$i + $j]);
                $l2 = $j === 1 ? $lo : 0x80;
                $h2 = $j === 1 ? $hi : 0xBF;
                if ($cc < $l2 || $cc > $h2) {
                    return $i;
                }
            }
            $i += $ln;
        }

        return -1;
    }

    /** @internal */
    public static function jsonWrite(string &$out, Value $v, int $depth, int $limit): void
    {
        switch ($v->kind) {
            case Value::KIND_NULL:
                $out .= 'null';

                return;
            case Value::KIND_BOOL:
                $out .= $v->bool ? 'true' : 'false';

                return;
            case Value::KIND_INT:
                $out .= (string) $v->int;

                return;
            case Value::KIND_UINT:
                $out .= $v->uintStr;

                return;
            case Value::KIND_FLOAT:
                if (\is_nan($v->float) || \is_infinite($v->float)) {
                    throw new SerdeError(
                        SerdeErrorCode::JSON_FLOAT_NANINF,
                        'non-finite float is not valid JSON',
                    );
                }
                $out .= FloatFormat::render($v->float);

                return;
            case Value::KIND_STR:
                self::jsonQuote($out, $v->str);

                return;
            case Value::KIND_BYTES:
                throw new SerdeError(SerdeErrorCode::JSON_BYTES, 'Bytes values cannot be encoded as JSON');
            case Value::KIND_DATETIME:
                throw new SerdeError(SerdeErrorCode::JSON_DATETIME, 'Datetime values cannot be encoded as JSON');
            case Value::KIND_ARRAY:
                if ($depth > $limit) {
                    throw new SerdeError(SerdeErrorCode::JSON_DEPTH, 'depth limit exceeded');
                }
                $out .= '[';
                $j = 0;
                foreach ($v->array as $x) {
                    if ($j++ > 0) {
                        $out .= ',';
                    }
                    self::jsonWrite($out, $x, $depth + 1, $limit);
                }
                $out .= ']';

                return;
            case Value::KIND_TABLE:
                if ($depth > $limit) {
                    throw new SerdeError(SerdeErrorCode::JSON_DEPTH, 'depth limit exceeded');
                }
                $out .= '{';
                $j = 0;
                foreach ($v->table as $e) {
                    if ($j++ > 0) {
                        $out .= ',';
                    }
                    self::jsonQuote($out, $e->key);
                    $out .= ':';
                    self::jsonWrite($out, $e->value, $depth + 1, $limit);
                }
                $out .= '}';

                return;
            default:
                throw new SerdeError(SerdeErrorCode::JSON_SYNTAX, 'unsupported value kind: ' . $v->kind);
        }
    }

    /** @internal */
    public static function jsonQuote(string &$out, string $s): void
    {
        $out .= '"';
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
                    if ($o < 0x20) {
                        $out .= self::formatU4($o);
                    } else {
                        $out .= $c;
                    }
            }
        }
        $out .= '"';
    }

    /** @internal */
    public static function formatU4(int $o): string
    {
        return '\\u' . \str_pad(\dechex($o), 4, '0', \STR_PAD_LEFT);
    }
}

/** Options for the JSON codec. */
final class JsonOptions
{
    public function __construct(
        public readonly int $depthLimit = Json::DEFAULT_DEPTH_LIMIT,
    ) {
    }
}

/** @internal Recursive-descent JSON parser over a byte string. */
final class JsonParser
{
    public int $i = 0;

    public function __construct(
        private readonly string $b,
        private readonly int $limit,
    ) {
    }

    public function skipWs(): void
    {
        $n = \strlen($this->b);
        while ($this->i < $n) {
            $c = \ord($this->b[$this->i]);
            if ($c === 0x20 || $c === 0x09 || $c === 0x0A || $c === 0x0D) {
                $this->i++;
                continue;
            }
            break;
        }
    }

    private function fail(string $detail): SerdeError
    {
        return new SerdeError(SerdeErrorCode::JSON_SYNTAX, $detail, $this->i);
    }

    public function parseValue(int $depth): Value
    {
        $this->skipWs();
        $n = \strlen($this->b);
        if ($this->i >= $n) {
            throw $this->fail('unexpected end of input');
        }
        $c = \ord($this->b[$this->i]);
        if ($c === 0x7B) {
            if ($depth > $this->limit) {
                throw new SerdeError(SerdeErrorCode::JSON_DEPTH, 'depth limit exceeded', $this->i);
            }

            return $this->parseObject($depth);
        }
        if ($c === 0x5B) {
            if ($depth > $this->limit) {
                throw new SerdeError(SerdeErrorCode::JSON_DEPTH, 'depth limit exceeded', $this->i);
            }

            return $this->parseArray($depth);
        }
        if ($c === 0x22) {
            return Value::str($this->parseString());
        }
        if ($c === 0x74) {
            $this->expect('true');

            return Value::bool(true);
        }
        if ($c === 0x66) {
            $this->expect('false');

            return Value::bool(false);
        }
        if ($c === 0x6E) {
            $this->expect('null');

            return Value::null();
        }
        if ($c === 0x2D || ($c >= 0x30 && $c <= 0x39)) {
            return $this->parseNumber();
        }
        throw $this->fail('unexpected character');
    }

    private function expect(string $word): void
    {
        $n = \strlen($this->b);
        if (\strlen($this->b) - $this->i < \strlen($word)) {
            throw $this->fail('invalid literal');
        }
        for ($j = 0, $w = \strlen($word); $j < $w; $j++) {
            if ($this->b[$this->i + $j] !== $word[$j]) {
                throw $this->fail('invalid literal');
            }
        }
        $this->i += $w;
    }

    private function parseObject(int $depth): Value
    {
        $this->i++; // {
        $pairs = [];
        $this->skipWs();
        if ($this->i < \strlen($this->b) && \ord($this->b[$this->i]) === 0x7D) {
            $this->i++;

            return Value::tableUnchecked($pairs);
        }
        for (;;) {
            $this->skipWs();
            if ($this->i >= \strlen($this->b) || \ord($this->b[$this->i]) !== 0x22) {
                throw $this->fail('expected object key');
            }
            $k = $this->parseString();
            $this->skipWs();
            if ($this->i >= \strlen($this->b) || \ord($this->b[$this->i]) !== 0x3A) {
                throw $this->fail("expected ':'");
            }
            $this->i++;
            $v = $this->parseValue($depth + 1);
            $pairs[] = new TableEntry($k, $v);
            $this->skipWs();
            if ($this->i >= \strlen($this->b)) {
                throw $this->fail('unterminated object');
            }
            $c = \ord($this->b[$this->i]);
            if ($c === 0x2C) {
                $this->i++;
                continue;
            }
            if ($c === 0x7D) {
                $this->i++;
                try {
                    return Value::table($pairs);
                } catch (SerdeError $e) {
                    if ($e->code() === SerdeErrorCode::TABLE_DUPLICATE) {
                        throw new SerdeError(SerdeErrorCode::JSON_SYNTAX, 'duplicate object key', $this->i);
                    }
                    throw $e;
                }
            }
            throw $this->fail("expected ',' or '}'");
        }
    }

    private function parseArray(int $depth): Value
    {
        $this->i++; // [
        $items = [];
        $this->skipWs();
        if ($this->i < \strlen($this->b) && \ord($this->b[$this->i]) === 0x5D) {
            $this->i++;

            return Value::array($items);
        }
        for (;;) {
            $items[] = $this->parseValue($depth + 1);
            $this->skipWs();
            if ($this->i >= \strlen($this->b)) {
                throw $this->fail('unterminated array');
            }
            $c = \ord($this->b[$this->i]);
            if ($c === 0x2C) {
                $this->i++;
                continue;
            }
            if ($c === 0x5D) {
                $this->i++;

                return Value::array($items);
            }
            throw $this->fail("expected ',' or ']'");
        }
    }

    private function parseString(): string
    {
        $this->i++; // opening quote
        $out = '';
        $n = \strlen($this->b);
        for (;;) {
            if ($this->i >= $n) {
                throw $this->fail('unterminated string');
            }
            $c = \ord($this->b[$this->i]);
            if ($c === 0x22) {
                $this->i++;

                return $out;
            }
            if ($c === 0x5C) {
                $this->i++;
                if ($this->i >= $n) {
                    throw $this->fail('unterminated escape');
                }
                $e = $this->b[$this->i];
                switch ($e) {
                    case '"':
                        $out .= '"';
                        $this->i++;
                        break;
                    case '\\':
                        $out .= '\\';
                        $this->i++;
                        break;
                    case '/':
                        $out .= '/';
                        $this->i++;
                        break;
                    case 'b':
                        $out .= "\x08";
                        $this->i++;
                        break;
                    case 'f':
                        $out .= "\x0C";
                        $this->i++;
                        break;
                    case 'n':
                        $out .= "\n";
                        $this->i++;
                        break;
                    case 'r':
                        $out .= "\r";
                        $this->i++;
                        break;
                    case 't':
                        $out .= "\t";
                        $this->i++;
                        break;
                    case 'u':
                        $cp = $this->parseHex4();
                        if ($cp >= 0xD800 && $cp <= 0xDBFF) {
                            if ($this->i + 1 < $n
                                && $this->b[$this->i] === '\\'
                                && $this->b[$this->i + 1] === 'u'
                            ) {
                                $this->i++; // land on the 'u' of the low escape
                                $lo = $this->parseHex4();
                                if ($lo >= 0xDC00 && $lo <= 0xDFFF) {
                                    $cc = 0x10000 + (($cp - 0xD800) << 10) + ($lo - 0xDC00);
                                    $out .= self::codePointToUtf8($cc);
                                } else {
                                    throw $this->fail('invalid low surrogate');
                                }
                            } else {
                                throw $this->fail('lone high surrogate');
                            }
                        } elseif ($cp >= 0xDC00 && $cp <= 0xDFFF) {
                            throw $this->fail('lone low surrogate');
                        } else {
                            $out .= self::codePointToUtf8($cp);
                        }
                        break;
                    default:
                        throw $this->fail('invalid escape');
                }
                continue;
            }
            if ($c < 0x20) {
                throw $this->fail('raw control character in string');
            }
            // consume one UTF-8 code point (input is pre-validated)
            if ($c < 0x80) {
                $out .= $this->b[$this->i];
                $this->i++;
            } elseif ($c < 0xE0) {
                $out .= \substr($this->b, $this->i, 2);
                $this->i += 2;
            } elseif ($c < 0xF0) {
                $out .= \substr($this->b, $this->i, 3);
                $this->i += 3;
            } else {
                $out .= \substr($this->b, $this->i, 4);
                $this->i += 4;
            }
        }
    }

    /** @internal UTF-8 encode a scalar code point (mirrors Go rune append). */
    public static function codePointToUtf8(int $cp): string
    {
        return \mb_chr($cp, 'UTF-8');
    }

    private function parseHex4(): int
    {
        if ($this->i >= \strlen($this->b) || $this->b[$this->i] !== 'u') {
            throw $this->fail('expected \\u');
        }
        if ($this->i + 4 >= \strlen($this->b)) {
            throw $this->fail('truncated \\u escape');
        }
        $h = \substr($this->b, $this->i + 1, 4);
        $cp = 0;
        for ($j = 0; $j < 4; $j++) {
            $ch = $h[$j];
            if ($ch >= '0' && $ch <= '9') {
                $d = (int) $ch;
            } elseif ($ch >= 'a' && $ch <= 'f') {
                $d = \ord($ch) - 87;
            } elseif ($ch >= 'A' && $ch <= 'F') {
                $d = \ord($ch) - 55;
            } else {
                throw $this->fail('invalid \\u escape');
            }
            $cp = $cp * 16 + $d;
        }
        $this->i += 5;

        return $cp;
    }

    private function parseNumber(): Value
    {
        $start = $this->i;
        $b = $this->b;
        $n = \strlen($b);
        if ($b[$this->i] === '-') {
            $this->i++;
            if ($this->i >= $n) {
                throw $this->fail('unexpected end of input');
            }
        }
        if ($b[$this->i] === '0') {
            $this->i++;
        } elseif ($b[$this->i] >= '1' && $b[$this->i] <= '9') {
            while ($this->i < $n && $b[$this->i] >= '0' && $b[$this->i] <= '9') {
                $this->i++;
            }
        } else {
            throw $this->fail('invalid number');
        }
        $isFloat = false;
        if ($this->i < $n && $b[$this->i] === '.') {
            $isFloat = true;
            $this->i++;
            if ($this->i >= $n || $b[$this->i] < '0' || $b[$this->i] > '9') {
                throw $this->fail("expected digit after '.'");
            }
            while ($this->i < $n && $b[$this->i] >= '0' && $b[$this->i] <= '9') {
                $this->i++;
            }
        }
        if ($this->i < $n && ($b[$this->i] === 'e' || $b[$this->i] === 'E')) {
            $isFloat = true;
            $this->i++;
            if ($this->i < $n && ($b[$this->i] === '+' || $b[$this->i] === '-')) {
                $this->i++;
            }
            if ($this->i >= $n || $b[$this->i] < '0' || $b[$this->i] > '9') {
                throw $this->fail('expected digit in exponent');
            }
            while ($this->i < $n && $b[$this->i] >= '0' && $b[$this->i] <= '9') {
                $this->i++;
            }
        }
        $text = \substr($b, $start, $this->i - $start);
        if (!$isFloat) {
            $parsed = self::parseInt64($text);
            if ($parsed !== null) {
                return Value::int($parsed);
            }
            if ($text[0] !== '-'
                && U64::cmp($text, '18446744073709551615') <= 0
            ) {
                return Value::uint($text);
            }
            throw new SerdeError(
                SerdeErrorCode::JSON_INT_RANGE,
                'integer out of 64-bit range',
                $start,
            );
        }

        return Value::float((float) $text);
    }

    /** Parses an i64 literal; returns null when out of range. */
    public static function parseInt64(string $text): ?int
    {
        $neg = $text !== '' && $text[0] === '-';
        $digits = $neg ? \substr($text, 1) : $text;
        if ($digits === '' || !\preg_match('/^\d+$/', $digits)) {
            return null;
        }
        $digits = U64::trim($digits);
        $posLimit = '9223372036854775807';     // 2^63 - 1
        $negLimit = '9223372036854775808';     // 2^63
        $limit = $neg ? $negLimit : $posLimit;
        if (U64::cmp($digits, $limit) > 0) {
            return null;
        }

        return (int) ($neg ? '-' . $digits : $digits);
    }
}

<?php

declare(strict_types=1);

namespace CodingLombok\LombokSerde;

/**
 * @internal TOML document parser: builds a tree of tomlNode tables, then
 * lowers it to a Value (mirrors the Go reference implementation).
 */
final class TomlParser
{
    public int $i = 0;

    /** @var array<string, TomlNode> */
    public array $root = [];

    /** @var list<string> */
    public array $cur = [];

    public function __construct(
        private readonly string $b,
        private readonly int $limit,
    ) {
        $this->root['[]'] = TomlNode::explicit();
    }

    public function fail(string $detail): SerdeError
    {
        return new SerdeError(SerdeErrorCode::TOML_SYNTAX, $detail, $this->i);
    }

    public function dup(): SerdeError
    {
        return new SerdeError(SerdeErrorCode::TOML_DUPLICATE, 'duplicate key or table definition', $this->i);
    }

    public function peek(): ?int
    {
        return $this->i < \strlen($this->b) ? \ord($this->b[$this->i]) : null;
    }

    public function skipInlineWs(): void
    {
        for (;;) {
            $c = $this->peek();
            if ($c === null || ($c !== 0x20 && $c !== 0x09)) {
                return;
            }
            $this->i++;
        }
    }

    public function skipComment(): void
    {
        if ($this->peek() === 0x23) {
            for (;;) {
                $c = $this->peek();
                if ($c === null || $c === 0x0A || $c === 0x0D) {
                    return;
                }
                $this->i++;
            }
        }
    }

    public function expectLineEnd(): void
    {
        $this->skipInlineWs();
        $this->skipComment();
        $c = $this->peek();
        if ($c === null) {
            return;
        }
        if ($c === 0x0A) {
            $this->i++;

            return;
        }
        if ($c === 0x0D) {
            $this->i++;
            if ($this->peek() === 0x0A) {
                $this->i++;
            }

            return;
        }
        throw $this->fail('expected end of line');
    }

    public function parse(): Value
    {
        for (;;) {
            $this->skipInlineWs();
            $c = $this->peek();
            if ($c === null) {
                break;
            }
            if ($c === 0x0A) {
                $this->i++;
                continue;
            }
            if ($c === 0x0D) {
                $this->i++;
                if ($this->peek() === 0x0A) {
                    $this->i++;
                }
                continue;
            }
            if ($c === 0x23) {
                $this->skipComment();
                continue;
            }
            if ($c === 0x5B) {
                if ($this->i + 1 < \strlen($this->b) && $this->b[$this->i + 1] === '[') {
                    $this->parseAotHeader();
                } else {
                    $this->parseTableHeader();
                }
            } else {
                $this->parseKeyval();
            }
            $this->expectLineEnd();
        }

        return $this->toValue([], 1);
    }

    private function parseTableHeader(): void
    {
        $start = $this->i;
        $this->i++; // [
        $path = $this->parseKeyPath();
        $this->skipInlineWs();
        if ($this->peek() !== 0x5D) {
            throw $this->fail("expected ']'");
        }
        $this->i++;
        if (\count($path) + 1 > $this->limit) {
            throw new SerdeError(SerdeErrorCode::TOML_DEPTH, 'depth limit exceeded', $start);
        }
        $this->defineTable($path);
        $this->cur = $path;
    }

    private function parseAotHeader(): void
    {
        $start = $this->i;
        $this->i += 2; // [[
        $path = $this->parseKeyPath();
        $this->skipInlineWs();
        $c = $this->peek();
        if ($c !== 0x5D || $this->i + 1 >= \strlen($this->b) || $this->b[$this->i + 1] !== ']') {
            throw $this->fail("expected ']]'");
        }
        $this->i += 2;
        if (\count($path) + 1 > $this->limit) {
            throw new SerdeError(SerdeErrorCode::TOML_DEPTH, 'depth limit exceeded', $start);
        }
        $this->defineAot($path);
        $this->cur = $path;
    }

    /** @param list<string> $path @return list<string> */
    public function resolve(array $path): array
    {
        $out = [];
        foreach ($path as $seg) {
            $node = $this->root[self::encodePath($out)] ?? null;
            if ($node !== null && $node->state === 'aot') {
                $out[] = '#' . (\count($node->elems) - 1);
            }
            $out[] = $seg;
        }

        return $out;
    }

    /** @param list<string> $path */
    private function defineTable(array $path): void
    {
        $concrete = $this->resolve($path);
        for ($j = 1; $j <= \count($concrete); $j++) {
            if (self::isPseudo($concrete[$j - 1])) {
                continue;
            }
            $sp = self::encodePath(\array_slice($concrete, 0, $j));
            $node = $this->root[$sp] ?? null;
            if ($node === null) {
                $this->root[$sp] = TomlNode::implicit();
            } elseif ($node->state === 'dotted') {
                throw new SerdeError(SerdeErrorCode::TOML_DUPLICATE, 'dotted-key table redefined by header', $this->i);
            }
        }
        $ck = self::encodePath($concrete);
        $node = $this->root[$ck] ?? null;
        if ($node === null) {
            $this->root[$ck] = TomlNode::explicit();

            return;
        }
        if ($node->state === 'implicit') {
            $node->state = 'explicit';

            return;
        }
        throw $this->dup();
    }

    /** @param list<string> $path */
    private function defineAot(array $path): void
    {
        $concrete = $this->resolve($path);
        for ($j = 1; $j <= \count($concrete); $j++) {
            if (self::isPseudo($concrete[$j - 1])) {
                continue;
            }
            $sp = self::encodePath(\array_slice($concrete, 0, $j));
            $node = $this->root[$sp] ?? null;
            if ($node === null) {
                $this->root[$sp] = TomlNode::implicit();
            } elseif ($node->state === 'dotted') {
                throw new SerdeError(SerdeErrorCode::TOML_DUPLICATE, 'dotted-key table redefined by header', $this->i);
            }
        }
        $ck = self::encodePath($concrete);
        $node = $this->root[$ck] ?? null;
        if ($node === null) {
            throw $this->dup();
        }
        if ($node->state === 'aot') {
            $node->elems[] = TomlNode::explicit();
        } elseif ($node->state === 'implicit') {
            $node->state = 'aot';
            $node->elems = [TomlNode::explicit()];
        } else {
            throw $this->dup();
        }
    }

    /** @return list<string> */
    private function parseKeyPath(): array
    {
        $keys = [];
        $this->skipInlineWs();
        for (;;) {
            $keys[] = $this->parseSingleKey();
            $this->skipInlineWs();
            if ($this->peek() === 0x2E) {
                $this->i++;
                $this->skipInlineWs();
                continue;
            }
            break;
        }

        return $keys;
    }

    private function parseSingleKey(): string
    {
        $c = $this->peek();
        if ($c === null) {
            throw $this->fail('expected key');
        }
        if ($c === 0x22) {
            $k = $this->parseBasicString();
            $this->checkReservedKey($k);

            return $k;
        }
        if ($c === 0x27) {
            $k = $this->parseLiteralString();
            $this->checkReservedKey($k);

            return $k;
        }
        $s = $this->i;
        for (;;) {
            $c = $this->peek();
            if ($c === null || !Toml::isBareKeyByte($c)) {
                break;
            }
            $this->i++;
        }
        if ($this->i === $s) {
            throw $this->fail('invalid key');
        }

        return \substr($this->b, $s, $this->i - $s);
    }

    private function checkReservedKey(string $key): void
    {
        if ($key !== '' && $key[0] === '#') {
            throw new SerdeError(SerdeErrorCode::TOML_SYNTAX, "keys starting with '#' are reserved", $this->i);
        }
    }

    private function parseKeyval(): void
    {
        $keys = $this->parseKeyPath();
        $this->skipInlineWs();
        if ($this->peek() !== 0x3D) {
            throw $this->fail("expected '='");
        }
        $this->i++;
        $this->skipInlineWs();
        $v = $this->parseValue(\count($this->cur) + \count($keys) + 1);
        $base = $this->resolve($this->cur);
        $inter = \array_slice($keys, 0, -1);
        if (\count($inter) > 0) {
            $bn = $this->root[self::encodePath($base)] ?? null;
            if ($bn !== null && $bn->state === 'aot') {
                throw new SerdeError(
                    SerdeErrorCode::TOML_SYNTAX,
                    'dotted keys cannot extend array-of-tables elements',
                    $this->i,
                );
            }
        }
        // walk intermediates
        $cur = $base;
        foreach ($inter as $seg) {
            $cur[] = $seg;
            $sp = self::encodePath($cur);
            $node = $this->root[$sp] ?? null;
            if ($node === null) {
                $this->root[$sp] = TomlNode::dotted();
            } elseif ($node->state === 'explicit') {
                throw new SerdeError(SerdeErrorCode::TOML_DUPLICATE, 'dotted key extends a header-defined table', $this->i);
            } elseif ($node->state === 'aot') {
                throw new SerdeError(SerdeErrorCode::TOML_SYNTAX, 'dotted keys cannot extend array-of-tables elements', $this->i);
            }
        }
        $parentPath = [...$base, ...$inter];
        $last = $keys[\count($keys) - 1];
        $leaf = self::encodePath([...$parentPath, $last]);
        if (isset($this->root[$leaf])) {
            throw $this->dup();
        }
        $pk = self::encodePath($parentPath);
        $node = $this->root[$pk] ?? null;
        if ($node === null) {
            $node = TomlNode::dotted();
            $this->root[$pk] = $node;
        }
        if ($node->state === 'aot') {
            // keyvals directly under [[a]] write into the most recent element
            $elem = $node->elems[\count($node->elems) - 1];
            if (isset($elem->pairs[$last])) {
                throw $this->dup();
            }
            $elem->pairs[$last] = $v;

            return;
        }
        if (isset($node->pairs[$last])) {
            throw $this->dup();
        }
        $node->pairs[$last] = $v;
    }

    public function parseValue(int $depth): Value
    {
        if ($depth > $this->limit) {
            throw new SerdeError(SerdeErrorCode::TOML_DEPTH, 'depth limit exceeded', $this->i);
        }
        $c = $this->peek();
        if ($c === null) {
            throw $this->fail('expected value');
        }
        if ($c === 0x22) {
            if ($this->startsWithStr('"""')) {
                return Value::str($this->parseMlBasic());
            }

            return Value::str($this->parseBasicString());
        }
        if ($c === 0x27) {
            if ($this->startsWithStr("'''")) {
                return Value::str($this->parseMlLiteral());
            }

            return Value::str($this->parseLiteralString());
        }
        if ($c === 0x5B) {
            return $this->parseArray($depth);
        }
        if ($c === 0x7B) {
            return $this->parseInlineTable($depth);
        }
        if ($this->startsWithStr('true')) {
            $this->i += 4;

            return Value::bool(true);
        }
        if ($this->startsWithStr('false')) {
            $this->i += 5;

            return Value::bool(false);
        }

        return $this->parseNumberOrDatetime();
    }

    private function startsWithStr(string $prefix): bool
    {
        return \substr($this->b, $this->i, \strlen($prefix)) === $prefix;
    }

    private function parseArray(int $depth): Value
    {
        $this->i++; // [
        $items = [];
        for (;;) {
            $this->skipArrayWs();
            $c = $this->peek();
            if ($c === null) {
                throw $this->fail('unterminated array');
            }
            if ($c === 0x5D) {
                $this->i++;

                return Value::array($items);
            }
            $items[] = $this->parseValue($depth + 1);
            $this->skipArrayWs();
            $c = $this->peek();
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

    private function skipArrayWs(): void
    {
        for (;;) {
            $c = $this->peek();
            if ($c === null) {
                return;
            }
            if ($c === 0x20 || $c === 0x09 || $c === 0x0A || $c === 0x0D) {
                $this->i++;
                continue;
            }
            if ($c === 0x23) {
                for (;;) {
                    $c2 = $this->peek();
                    if ($c2 === null || $c2 === 0x0A || $c2 === 0x0D) {
                        break;
                    }
                    $this->i++;
                }
                continue;
            }
            break;
        }
    }

    private function parseInlineTable(int $depth): Value
    {
        $this->i++; // {
        $pairs = [];
        $this->skipInlineWs();
        if ($this->peek() === 0x7D) {
            $this->i++;

            return Value::tableUnchecked($pairs);
        }
        for (;;) {
            $this->skipInlineWs();
            $keys = $this->parseKeyPath();
            $this->skipInlineWs();
            if ($this->peek() !== 0x3D) {
                throw $this->fail("expected '='");
            }
            $this->i++;
            $this->skipInlineWs();
            $v = $this->parseValue($depth + 1);
            if (\count($keys) > 1) {
                $v = self::nestDotted(\array_slice($keys, 1), $v);
            }
            $pairs[] = new TableEntry($keys[0], $v);
            $this->skipInlineWs();
            $c = $this->peek();
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
                        throw new SerdeError(SerdeErrorCode::TOML_SYNTAX, 'duplicate key in inline table', $this->i - 1);
                    }
                    throw $e;
                }
            }
            throw $this->fail("expected ',' or '}' in inline table");
        }
    }

    /** @param list<string> $keys */
    private static function nestDotted(array $keys, Value $v): Value
    {
        for ($j = \count($keys) - 1; $j >= 0; $j--) {
            $v = Value::tableUnchecked([new TableEntry($keys[$j], $v)]);
        }

        return $v;
    }

    private function parseBasicString(): string
    {
        $this->i++; // "
        $out = '';
        for (;;) {
            $c = $this->peek();
            if ($c === null) {
                throw $this->fail('unterminated string');
            }
            if ($c === 0x22) {
                $this->i++;

                return $out;
            }
            if ($c === 0x0A || $c === 0x0D) {
                throw $this->fail('newline in basic string');
            }
            if ($c === 0x5C) {
                $this->i++;
                $out = $this->parseEscapeInto($out);
                continue;
            }
            if ($c < 0x20 && $c !== 0x09) {
                throw $this->fail('raw control character in string');
            }
            $out .= $this->takeUtf8();
        }
    }

    /** Consumes one UTF-8 code point from the (pre-validated) input. */
    private function takeUtf8(): string
    {
        $c = \ord($this->b[$this->i]);
        $size = $c < 0x80 ? 1 : ($c < 0xE0 ? 2 : ($c < 0xF0 ? 3 : 4));
        $s = \substr($this->b, $this->i, $size);
        $this->i += $size;

        return $s;
    }

    private function parseEscapeInto(string $out): string
    {
        $e = $this->peek();
        if ($e === null) {
            throw $this->fail('unterminated escape');
        }
        switch ($e) {
            case 0x62: // b
                $out .= "\x08";
                $this->i++;

                return $out;
            case 0x74: // t
                $out .= "\t";
                $this->i++;

                return $out;
            case 0x6E: // n
                $out .= "\n";
                $this->i++;

                return $out;
            case 0x66: // f
                $out .= "\x0C";
                $this->i++;

                return $out;
            case 0x72: // r
                $out .= "\r";
                $this->i++;

                return $out;
            case 0x22: // "
                $out .= '"';
                $this->i++;

                return $out;
            case 0x5C: // \
                $out .= '\\';
                $this->i++;

                return $out;
            case 0x75: // u
            case 0x55: // U
                $width = $e === 0x75 ? 4 : 8;
                $this->i++;
                if ($this->i + $width > \strlen($this->b)) {
                    throw $this->fail('truncated unicode escape');
                }
                $h = \substr($this->b, $this->i, $width);
                $cp = 0;
                for ($j = 0; $j < $width; $j++) {
                    $ch = $h[$j];
                    if ($ch >= '0' && $ch <= '9') {
                        $d = (int) $ch;
                    } elseif ($ch >= 'a' && $ch <= 'f') {
                        $d = \ord($ch) - 87;
                    } elseif ($ch >= 'A' && $ch <= 'F') {
                        $d = \ord($ch) - 55;
                    } else {
                        throw $this->fail('invalid unicode escape');
                    }
                    $cp = $cp * 16 + $d;
                }
                if ($cp > 0x10FFFF) {
                    throw $this->fail('invalid scalar value');
                }
                $out .= JsonParser::codePointToUtf8($cp);
                $this->i += $width;

                return $out;
            case 0x0A:
            case 0x0D:
            case 0x20:
            case 0x09:
                // possible line-ending backslash (multiline strings only)
                $j = $this->i;
                $sawNl = false;
                $n = \strlen($this->b);
                while ($j < $n) {
                    $c = $this->b[$j];
                    if ($c === ' ' || $c === "\t" || $c === "\r" || $c === "\n") {
                        if ($c === "\n" || $c === "\r") {
                            $sawNl = true;
                        }
                        $j++;
                        continue;
                    }
                    break;
                }
                if ($sawNl) {
                    $this->i = $j;

                    return $out;
                }
                throw $this->fail('invalid escape');
            default:
                throw $this->fail('invalid escape');
        }
    }

    private function parseLiteralString(): string
    {
        $this->i++; // '
        $s = $this->i;
        for (;;) {
            $c = $this->peek();
            if ($c === null) {
                throw $this->fail('unterminated string');
            }
            if ($c === 0x27) {
                $r = \substr($this->b, $s, $this->i - $s);
                $this->i++;

                return $r;
            }
            if (($c < 0x20 && $c !== 0x09) || $c === 0x7F) {
                throw $this->fail('raw control character in literal string');
            }
            $this->i++;
        }
    }

    private function parseMlBasic(): string
    {
        $this->i += 3;
        if ($this->peek() === 0x0A) {
            $this->i++;
        } elseif ($this->startsWithStr("\r\n")) {
            $this->i += 2;
        }
        $out = '';
        for (;;) {
            if ($this->i >= \strlen($this->b)) {
                throw $this->fail('unterminated multiline string');
            }
            if ($this->startsWithStr('"""')) {
                $this->i += 3;
                $extra = 0;
                for (;;) {
                    $c = $this->peek();
                    if ($c === null || $c !== 0x22 || $extra >= 2) {
                        break;
                    }
                    $out .= '"';
                    $this->i++;
                    $extra++;
                }

                return $out;
            }
            $c = \ord($this->b[$this->i]);
            if ($c === 0x5C) {
                $this->i++;
                $out = $this->parseEscapeInto($out);
                continue;
            }
            if ($c < 0x20 && $c !== 0x09 && $c !== 0x0A && $c !== 0x0D) {
                throw $this->fail('raw control character in multiline string');
            }
            $out .= $this->takeUtf8();
        }
    }

    private function parseMlLiteral(): string
    {
        $this->i += 3;
        if ($this->peek() === 0x0A) {
            $this->i++;
        } elseif ($this->startsWithStr("\r\n")) {
            $this->i += 2;
        }
        $s = $this->i;
        for (;;) {
            if ($this->i >= \strlen($this->b)) {
                throw $this->fail('unterminated multiline string');
            }
            if ($this->startsWithStr("'''")) {
                $r = \substr($this->b, $s, $this->i - $s);
                $this->i += 3;

                return $r;
            }
            $c = \ord($this->b[$this->i]);
            if ($c < 0x20 && $c !== 0x09 && $c !== 0x0A && $c !== 0x0D) {
                throw $this->fail('raw control character in multiline string');
            }
            $this->i++;
        }
    }

    private function parseNumberOrDatetime(): Value
    {
        $start = $this->i;
        $scan = $this->scanDatetime();
        if ($scan !== null) {
            [$kind, $end] = $scan;
            $raw = \substr($this->b, $start, $end - $start);
            $this->i = $end;

            return Value::datetime($kind, $raw);
        }
        $b = $this->b;
        $n = \strlen($b);
        $sign = 1;
        $signSeen = false;
        if ($b[$this->i] === '+' || $b[$this->i] === '-') {
            if ($b[$this->i] === '-') {
                $sign = -1;
            }
            $signSeen = true;
            $this->i++;
        }
        if ($this->startsWithStr('inf')) {
            $this->i += 3;

            return Value::float($sign < 0 ? -\INF : \INF);
        }
        if ($this->startsWithStr('nan')) {
            $this->i += 3;

            // SPEC: the canonical quiet NaN, not a runtime NaN payload
            return Value::float(\unpack('E', "\x7F\xF8\x00\x00\x00\x00\x00\x00")[1]);
        }
        $digitsStart = $this->i;
        $this->readDigits(10);
        $base = 10;
        if ($this->i - $digitsStart === 1 && $b[$digitsStart] === '0') {
            $c = $this->peek();
            if ($c === \ord('x')) {
                $base = 16;
            } elseif ($c === \ord('o')) {
                $base = 8;
            } elseif ($c === \ord('b')) {
                $base = 2;
            }
        }
        if ($base !== 10) {
            if ($signSeen) {
                throw $this->fail('signs are not allowed on hex/oct/bin integers');
            }
            $this->i++;
            $this->readDigits($base);
            $text = \str_replace('_', '', \substr($b, $digitsStart + 2, $this->i - $digitsStart - 2));
            $parsed = self::parseInt64Base($text, $base);
            if ($parsed === null) {
                throw new SerdeError(SerdeErrorCode::TOML_SYNTAX, 'integer out of 64-bit range', $start);
            }

            return Value::int($sign * $parsed);
        }
        $isFloat = false;
        if ($this->peek() === 0x2E) {
            $isFloat = true;
            $this->i++;
            $this->readDigits(10);
        }
        $c = $this->peek();
        if ($c === \ord('e') || $c === \ord('E')) {
            $isFloat = true;
            $this->i++;
            $c2 = $this->peek();
            if ($c2 === 0x2B || $c2 === 0x2D) {
                $this->i++;
            }
            $c3 = $this->peek();
            if ($c3 === null || $c3 < 0x30 || $c3 > 0x39) {
                throw $this->fail('expected digit in exponent');
            }
            $this->readDigits(10);
        }
        $text = \str_replace('_', '', \substr($b, $digitsStart, $this->i - $digitsStart));
        if (!$isFloat) {
            if (\strlen($text) > 1 && $text[0] === '0') {
                throw $this->fail('leading zero in integer');
            }
            $mag = self::parseUint64($text);
            if ($mag === null) {
                throw new SerdeError(SerdeErrorCode::TOML_SYNTAX, 'integer out of 64-bit range', $start);
            }
            if (($sign > 0 && U64::cmp($mag, '9223372036854775807') > 0)
                || ($sign < 0 && U64::cmp($mag, '9223372036854775808') > 0)
            ) {
                throw new SerdeError(SerdeErrorCode::TOML_SYNTAX, 'integer out of 64-bit range', $start);
            }
            if ($sign < 0) {
                if ($mag === '9223372036854775808') {
                    return Value::int(\PHP_INT_MIN);
                }

                return Value::int(-((int) $mag));
            }

            return Value::int((int) $mag);
        }
        // Rust semantics: overflow rounds to +/-Inf, underflow to +/-0.
        // PHP's (float) cast is a correctly-rounded strtod with the same
        // outcomes, so the value is taken as-is.

        return Value::float((float) $text);
    }

    private function readDigits(int $base): void
    {
        $count = 0;
        $n = \strlen($this->b);
        while ($this->i < $n) {
            $c = \ord($this->b[$this->i]);
            if (self::isDigitBase($c, $base)) {
                $count++;
                $this->i++;
                continue;
            }
            if ($c === 0x5F) {
                if ($count === 0) {
                    throw $this->fail('leading underscore');
                }
                if ($this->i + 1 >= $n || !self::isDigitBase(\ord($this->b[$this->i + 1]), $base)) {
                    throw $this->fail('trailing underscore');
                }
                $this->i++;
                continue;
            }
            break;
        }
        if ($count === 0) {
            throw $this->fail('expected digit');
        }
    }

    private static function isDigitBase(int $c, int $base): bool
    {
        switch ($base) {
            case 10:
                return $c >= 0x30 && $c <= 0x39;
            case 16:
                return ($c >= 0x30 && $c <= 0x39) || ($c >= 0x61 && $c <= 0x66) || ($c >= 0x41 && $c <= 0x46);
            case 8:
                return $c >= 0x30 && $c <= 0x37;
            default:
                return $c === 0x30 || $c === 0x31;
        }
    }

    /** @return array{0:string,1:int}|null */
    private function scanDatetime(): ?array
    {
        $i = $this->i;
        $n = \strlen($this->b);
        $j = $i;
        while ($j < $n) {
            $c = $this->b[$j];
            if (($c >= '0' && $c <= '9') || $c === '-' || $c === ':') {
                $j++;
                continue;
            }
            break;
        }
        $seg = \substr($this->b, $i, $j - $i);
        $hasDash = \str_contains($seg, '-');
        $hasColon = \str_contains($seg, ':');
        if (!$hasDash && !$hasColon) {
            return null;
        }
        if ($hasDash && !$hasColon) {
            if ($j - $i !== 10) {
                return null;
            }
            if ($j < $n) {
                $c = $this->b[$j];
                if ($c === 'T' || $c === 't' || $c === ' ') {
                    $m = $j + 1;
                    $k = $m;
                    while ($k < $n) {
                        $c2 = $this->b[$k];
                        if (($c2 >= '0' && $c2 <= '9') || $c2 === ':') {
                            $k++;
                            continue;
                        }
                        break;
                    }
                    $tseg = \substr($this->b, $m, $k - $m);
                    if (!\str_contains($tseg, ':')) {
                        return $this->validateDatetime($i, $j, 'date');
                    }
                    $fz = $this->scanFracZone($k);
                    if ($fz === null) {
                        return null;
                    }
                    $kind = $fz[1] ? 'offset' : 'localdt';

                    return $this->validateDatetime($i, $fz[0], $kind);
                }
            }

            return $this->validateDatetime($i, $j, 'date');
        }
        if ($hasColon && !$hasDash) {
            $k = $j;
            if ($k < $n && $this->b[$k] === '.') {
                $k++;
                if ($k < $n && $this->b[$k] >= '0' && $this->b[$k] <= '9') {
                    while ($k < $n && $this->b[$k] >= '0' && $this->b[$k] <= '9') {
                        $k++;
                    }
                } else {
                    return null;
                }
            }

            return $this->validateDatetime($i, $k, 'time');
        }

        return null;
    }

    /** @return array{0:int,1:bool}|null [end, hadZone] */
    private function scanFracZone(int $k): ?array
    {
        $n = \strlen($this->b);
        $end = $k;
        if ($end < $n && $this->b[$end] === '.') {
            $end++;
            if ($end < $n && $this->b[$end] >= '0' && $this->b[$end] <= '9') {
                while ($end < $n && $this->b[$end] >= '0' && $this->b[$end] <= '9') {
                    $end++;
                }
            } else {
                return null;
            }
        }
        if ($end < $n && ($this->b[$end] === 'Z' || $this->b[$end] === 'z')) {
            return [$end + 1, true];
        }
        if ($end + 6 <= $n && ($this->b[$end] === '+' || $this->b[$end] === '-') && $this->b[$end + 3] === ':') {
            return [$end + 6, true];
        }

        return [$end, false];
    }

    /** @return array{0:string,1:int}|null */
    private function validateDatetime(int $s, int $end, string $kind): ?array
    {
        $text = \substr($this->b, $s, $end - $s);
        if (DatetimeCheck::ok($text, $kind)) {
            return [$kind, $end];
        }
        // the token has datetime shape but is invalid: fail at its start
        throw new SerdeError(SerdeErrorCode::TOML_SYNTAX, 'invalid datetime', $s);
    }

    // --- tree -> Value --------------------------------------------------------

    /** @param list<string> $path */
    public function toValue(array $path, int $depth): Value
    {
        $node = $this->root[self::encodePath($path)] ?? null;
        if ($node === null) {
            throw $this->fail('missing table');
        }
        if ($node->state === 'aot') {
            $elems = [];
            foreach ($node->elems as $idx => $el) {
                $base = [...$path, '#' . $idx];
                $elems[] = $this->collectFrom($el->pairs, $base, $depth);
            }

            return Value::array($elems);
        }

        return $this->collect($path, $depth);
    }

    /** @param list<string> $path */
    private function collect(array $path, int $depth): Value
    {
        $node = $this->root[self::encodePath($path)] ?? null;
        if ($node === null) {
            throw $this->fail('missing table');
        }

        return $this->collectFrom($node->pairs, $path, $depth);
    }

    /** @param array<string,Value> $pairs @param list<string> $basePath */
    private function collectFrom(array $pairs, array $basePath, int $depth): Value
    {
        $out = [];
        foreach ($pairs as $k => $v) {
            $out[] = new TableEntry($k, $v);
        }
        foreach (\array_keys($this->root) as $key) {
            $segs = self::decodePath($key);
            if (\count($segs) !== \count($basePath) + 1 || !self::pathHasPrefix($segs, $basePath)) {
                continue;
            }
            $k = $segs[\count($segs) - 1];
            if (self::isPseudo($k)) {
                continue;
            }
            foreach ($out as $existing) {
                if ($existing->key === $k) {
                    throw new SerdeError(SerdeErrorCode::TOML_DUPLICATE, 'table and value share a key', $this->i);
                }
            }
            $out[] = new TableEntry($k, $this->toValue($segs, $depth + 1));
        }

        return Value::tableUnchecked($out);
    }

    /** @param list<string> $segs @param list<string> $base */
    private static function pathHasPrefix(array $segs, array $base): bool
    {
        foreach ($base as $j => $seg) {
            if ($segs[$j] !== $seg) {
                return false;
            }
        }

        return true;
    }

    // --- path helpers -----------------------------------------------------------

    /** @param list<string> $p */
    public static function encodePath(array $p): string
    {
        // JSON encoding is injective: [] (root) and [""] (empty key) differ.
        $out = '[';
        foreach ($p as $j => $seg) {
            if ($j > 0) {
                $out .= ',';
            }
            $out .= '"';
            for ($i = 0, $n = \strlen($seg); $i < $n; $i++) {
                $ch = $seg[$i];
                if ($ch === '"') {
                    $out .= '\\"';
                } elseif ($ch === '\\') {
                    $out .= '\\\\';
                } else {
                    $out .= $ch;
                }
            }
            $out .= '"';
        }
        $out .= ']';

        return $out;
    }

    /** @return list<string> */
    public static function decodePath(string $k): array
    {
        $body = \substr($k, 1, \strlen($k) - 2);
        if ($body === false || $body === '') {
            return [];
        }
        $segs = [];
        $cur = '';
        $j = 0;
        $len = \strlen($body);
        while ($j < $len) {
            if ($body[$j] === ',') {
                $segs[] = $cur;
                $cur = '';
                $j++;
                continue;
            }
            if ($body[$j] === '"' && $j + 1 < $len) {
                // a quoted segment starts; unescape until the closing quote
                $j++;
                while ($j < $len && $body[$j] !== '"') {
                    if ($body[$j] === '\\' && $j + 1 < $len) {
                        $j++;
                    }
                    $cur .= $body[$j];
                    $j++;
                }
                $j++; // closing quote
                continue;
            }
            $cur .= $body[$j];
            $j++;
        }
        $segs[] = $cur;

        return $segs;
    }

    public static function isPseudo(string $seg): bool
    {
        return $seg !== '' && $seg[0] === '#';
    }

    /** Base-10 integer text -> value, or null when out of range. */
    public static function parseUint64(string $text): ?string
    {
        $text = U64::trim($text);
        if (U64::cmp($text, '18446744073709551615') > 0) {
            return null;
        }

        return $text;
    }

    /** @return int|null */
    public static function parseInt64Base(string $text, int $base): ?int
    {
        $n = 0;
        $limit = \intdiv((1 << 62) - 1, $base);
        for ($j = 0, $len = \strlen($text); $j < $len; $j++) {
            $c = $text[$j];
            if ($c >= '0' && $c <= '9') {
                $d = \ord($c) - 48;
            } elseif ($c >= 'a' && $c <= 'f') {
                $d = \ord($c) - 87;
            } elseif ($c >= 'A' && $c <= 'F') {
                $d = \ord($c) - 55;
            } else {
                return null;
            }
            if ($d >= $base) {
                return null;
            }
            if ($n > $limit) {
                return null;
            }
            $n = $n * $base + $d;
        }

        return $n;
    }
}

/** @internal TOML tree node. */
final class TomlNode
{
    /** @var array<string, Value> */
    public array $pairs = [];

    /** @var list<TomlNode> */
    public array $elems = [];

    public function __construct(
        public string $state = 'implicit', // implicit | explicit | dotted | aot
    ) {
    }

    public static function implicit(): self
    {
        return new self('implicit');
    }

    public static function explicit(): self
    {
        return new self('explicit');
    }

    public static function dotted(): self
    {
        return new self('dotted');
    }
}

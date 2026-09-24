<?php

declare(strict_types=1);

namespace LombokSerde\Toml;

use LombokSerde\DateTimeValue;
use LombokSerde\SerdeError;
use LombokSerde\SerdeErrorCode;

class TomlParser
{
    private string $input;
    private int $pos = 0;

    public function __construct(string $input)
    {
        $this->input = $input;
    }

    public static function parse(string $input): array
    {
        $p = new self($input);
        return $p->doParse();
    }

    private function doParse(): array
    {
        $root = [];
        $currentPath = [];

        while (true) {
            $this->skipWsNewlines();
            if ($this->pos >= strlen($this->input)) break;

            $ch = $this->input[$this->pos];
            if ($ch === '#') { $this->skipComment(); continue; }

            if ($ch === '[') {
                $this->pos++;
                $isArray = $this->pos < strlen($this->input) && $this->input[$this->pos] === '[';
                if ($isArray) $this->pos++;
                $this->skipWs();
                $keys = $this->parseKey();
                $this->skipWs();
                if ($isArray) { $this->expect(']'); $this->expect(']'); }
                else { $this->expect(']'); }
                $this->skipWs();
                if ($this->pos < strlen($this->input) && $this->input[$this->pos] === '#') {
                    $this->skipComment();
                }

                if ($isArray) {
                    $this->ensureArrayOfTables($root, $keys);
                } else {
                    $this->ensureTable($root, $keys);
                }
                $currentPath = $keys;
                continue;
            }

            $keys = $this->parseKey();
            $this->skipWs();
            $this->expect('=');
            $this->skipWs();
            $value = $this->parseValue();
            $this->skipWs();
            if ($this->pos < strlen($this->input) && $this->input[$this->pos] === '#') {
                $this->skipComment();
            }
            $this->insertValue($root, $currentPath, $keys, $value);
        }

        return $root;
    }

    private function parseKey(): array
    {
        $keys = [$this->parseSimpleKey()];
        while (true) {
            $this->skipWs();
            if ($this->pos < strlen($this->input) && $this->input[$this->pos] === '.') {
                $this->pos++;
                $this->skipWs();
                $keys[] = $this->parseSimpleKey();
            } else break;
        }
        return $keys;
    }

    private function parseSimpleKey(): string
    {
        if ($this->pos >= strlen($this->input)) throw $this->eof();
        $ch = $this->input[$this->pos];
        if ($ch === '"') return $this->parseBasicString();
        if ($ch === "'") return $this->parseLiteralString();
        return $this->parseBareKey();
    }

    private function parseBareKey(): string
    {
        $start = $this->pos;
        while ($this->pos < strlen($this->input) && $this->isBareKeyChar($this->input[$this->pos])) {
            $this->pos++;
        }
        if ($this->pos === $start) throw $this->syntaxErr('empty bare key');
        return substr($this->input, $start, $this->pos - $start);
    }

    private function isBareKeyChar(string $ch): bool
    {
        return ctype_alnum($ch) || $ch === '_' || $ch === '-';
    }

    private function parseBasicString(): string
    {
        $this->expect('"');
        if ($this->pos + 1 < strlen($this->input)
            && $this->input[$this->pos] === '"'
            && $this->input[$this->pos + 1] === '"') {
            $this->pos += 2;
            return $this->parseMultilineBasicString();
        }
        $s = '';
        while (true) {
            if ($this->pos >= strlen($this->input)) throw $this->eof();
            $ch = $this->input[$this->pos++];
            if ($ch === '"') return $s;
            if ($ch === '\\') { $s .= $this->parseEscape(); continue; }
            $s .= $ch;
        }
    }

    private function parseMultilineBasicString(): string
    {
        if ($this->pos < strlen($this->input) && $this->input[$this->pos] === "\n") $this->pos++;
        elseif ($this->pos < strlen($this->input) && $this->input[$this->pos] === "\r") {
            $this->pos++;
            if ($this->pos < strlen($this->input) && $this->input[$this->pos] === "\n") $this->pos++;
        }
        $s = '';
        while (true) {
            if ($this->pos >= strlen($this->input)) throw $this->eof();
            $ch = $this->input[$this->pos++];
            if ($ch === '"' && substr($this->input, $this->pos, 2) === '""') {
                $this->pos += 2;
                return $s;
            }
            if ($ch === '\\') {
                $next = $this->pos < strlen($this->input) ? $this->input[$this->pos] : '';
                if ($next === "\n" || $next === "\r") {
                    $this->skipWsNewlines();
                    continue;
                }
                $s .= $this->parseEscape();
                continue;
            }
            $s .= $ch;
        }
    }

    private function parseLiteralString(): string
    {
        $this->expect("'");
        if ($this->pos + 1 < strlen($this->input)
            && $this->input[$this->pos] === "'"
            && $this->input[$this->pos + 1] === "'") {
            $this->pos += 2;
            return $this->parseMultilineLiteralString();
        }
        $start = $this->pos;
        while ($this->pos < strlen($this->input) && $this->input[$this->pos] !== "'") $this->pos++;
        $s = substr($this->input, $start, $this->pos - $start);
        $this->expect("'");
        return $s;
    }

    private function parseMultilineLiteralString(): string
    {
        if ($this->pos < strlen($this->input) && $this->input[$this->pos] === "\n") $this->pos++;
        elseif ($this->pos < strlen($this->input) && $this->input[$this->pos] === "\r") {
            $this->pos++;
            if ($this->pos < strlen($this->input) && $this->input[$this->pos] === "\n") $this->pos++;
        }
        $s = '';
        while (true) {
            if ($this->pos >= strlen($this->input)) throw $this->eof();
            $ch = $this->input[$this->pos++];
            if ($ch === "'" && substr($this->input, $this->pos, 2) === "''") {
                $this->pos += 2;
                return $s;
            }
            $s .= $ch;
        }
    }

    private function parseEscape(): string
    {
        if ($this->pos >= strlen($this->input)) throw $this->eof();
        $ch = $this->input[$this->pos++];
        return match ($ch) {
            'b' => "\x08",
            't' => "\t",
            'n' => "\n",
            'f' => "\x0C",
            'r' => "\r",
            '"' => '"',
            '\\' => '\\',
            'u' => $this->parseUnicodeEscape(4),
            'U' => $this->parseUnicodeEscape(8),
            default => throw $this->syntaxErr('invalid escape'),
        };
    }

    private function parseUnicodeEscape(int $digits): string
    {
        $hex = substr($this->input, $this->pos, $digits);
        $this->pos += $digits;
        $cp = hexdec($hex);
        return mb_chr((int)$cp, 'UTF-8');
    }

    private function parseValue(): mixed
    {
        if ($this->pos >= strlen($this->input)) throw $this->eof();
        $ch = $this->input[$this->pos];

        if ($ch === '"') return $this->parseBasicString();
        if ($ch === "'") return $this->parseLiteralString();
        if ($ch === 't') { $this->expectStr('true'); return true; }
        if ($ch === 'f') { $this->expectStr('false'); return false; }
        if ($ch === '[') return $this->parseArray();
        if ($ch === '{') return $this->parseInlineTable();
        if ($ch === 'i') { $this->expectStr('inf'); return INF; }
        if ($ch === 'n' && substr($this->input, $this->pos, 3) === 'nan') { $this->pos += 3; return NAN; }
        if ($ch === '-' || $ch === '+' || ctype_digit($ch)) return $this->parseNumberOrDate();
        throw $this->syntaxErr('expected value');
    }

    private function parseArray(): array
    {
        $this->expect('[');
        $arr = [];
        while (true) {
            $this->skipWsNewlinesComments();
            if ($this->pos < strlen($this->input) && $this->input[$this->pos] === ']') {
                $this->pos++;
                return $arr;
            }
            $arr[] = $this->parseValue();
            $this->skipWsNewlinesComments();
            if ($this->pos < strlen($this->input) && $this->input[$this->pos] === ',') $this->pos++;
        }
    }

    private function parseInlineTable(): array
    {
        $this->expect('{');
        $map = [];
        $this->skipWs();
        if ($this->pos < strlen($this->input) && $this->input[$this->pos] === '}') {
            $this->pos++;
            return $map;
        }
        while (true) {
            $this->skipWs();
            $keys = $this->parseKey();
            $this->skipWs();
            $this->expect('=');
            $this->skipWs();
            $value = $this->parseValue();
            $this->insertIntoMap($map, $keys, $value);
            $this->skipWs();
            if ($this->pos < strlen($this->input) && $this->input[$this->pos] === ',') { $this->pos++; }
            else break;
        }
        $this->skipWs();
        $this->expect('}');
        return $map;
    }

    private function parseNumberOrDate(): mixed
    {
        $start = $this->pos;
        $sign = $this->input[$this->pos];
        if ($sign === '+' || $sign === '-') $this->pos++;

        if (substr($this->input, $this->pos, 3) === 'inf') {
            $this->pos += 3;
            return $sign === '-' ? -INF : INF;
        }
        if (substr($this->input, $this->pos, 3) === 'nan') {
            $this->pos += 3;
            return NAN;
        }

        while ($this->pos < strlen($this->input)) {
            $c = $this->input[$this->pos];
            if (preg_match('/[0-9a-fA-F_.:+\-TtZxXoObB]/', $c)) $this->pos++;
            else break;
        }

        $raw = substr($this->input, $start, $this->pos - $start);
        $clean = str_replace('_', '', $raw);

        if ($this->looksLikeDatetime($clean)) {
            return $this->parseDatetime($clean);
        }

        $noSign = ($sign === '+' || $sign === '-') ? substr($clean, 1) : $clean;
        $mult = $sign === '-' ? -1 : 1;

        if (str_starts_with($noSign, '0x') || str_starts_with($noSign, '0X')) {
            return intval($noSign, 16) * $mult;
        }
        if (str_starts_with($noSign, '0o') || str_starts_with($noSign, '0O')) {
            return intval(substr($noSign, 2), 8) * $mult;
        }
        if (str_starts_with($noSign, '0b') || str_starts_with($noSign, '0B')) {
            return intval(substr($noSign, 2), 2) * $mult;
        }

        if (str_contains($clean, '.') || str_contains($clean, 'e') || str_contains($clean, 'E')) {
            return (float)$clean;
        }
        return (int)$clean;
    }

    // --- Table navigation ---

    private function ensureTable(array &$root, array $keys): void
    {
        $current = &$root;
        foreach ($keys as $key) {
            if (!array_key_exists($key, $current)) {
                $current[$key] = [];
            }
            $val = &$current[$key];
            if (is_array($val) && !empty($val) && array_is_list($val)) {
                $current = &$val[count($val) - 1];
            } elseif (is_array($val)) {
                $current = &$val;
            } else {
                throw new SerdeError(SerdeErrorCode::DuplicateKey, 'duplicate key');
            }
        }
    }

    private function ensureArrayOfTables(array &$root, array $keys): void
    {
        $current = &$root;
        for ($i = 0; $i < count($keys) - 1; $i++) {
            $key = $keys[$i];
            if (!array_key_exists($key, $current)) {
                $current[$key] = [];
            }
            $val = &$current[$key];
            if (is_array($val) && !empty($val) && array_is_list($val)) {
                $current = &$val[count($val) - 1];
            } elseif (is_array($val)) {
                $current = &$val;
            } else {
                throw new SerdeError(SerdeErrorCode::DuplicateKey, 'duplicate key');
            }
        }
        $lastKey = $keys[count($keys) - 1];
        if (!array_key_exists($lastKey, $current)) {
            $current[$lastKey] = [[]];
        } else {
            $val = &$current[$lastKey];
            if (is_array($val) && array_is_list($val)) {
                $val[] = [];
            } else {
                throw new SerdeError(SerdeErrorCode::DuplicateKey, 'duplicate key');
            }
        }
    }

    private function insertValue(array &$root, array $tablePath, array $keys, mixed $value): void
    {
        $current = &$root;
        foreach ($tablePath as $key) {
            $val = &$current[$key];
            if (is_array($val) && !empty($val) && array_is_list($val)) {
                $current = &$val[count($val) - 1];
            } else {
                $current = &$val;
            }
        }
        $this->insertIntoMap($current, $keys, $value);
    }

    private function insertIntoMap(array &$map, array $keys, mixed $value): void
    {
        if (count($keys) === 1) {
            if (array_key_exists($keys[0], $map)) {
                throw new SerdeError(SerdeErrorCode::DuplicateKey, 'duplicate key');
            }
            $map[$keys[0]] = $value;
        } else {
            if (!array_key_exists($keys[0], $map)) {
                $map[$keys[0]] = [];
            }
            $sub = &$map[$keys[0]];
            if (is_array($sub) && !array_is_list($sub)) {
                $this->insertIntoMap($sub, array_slice($keys, 1), $value);
            } else {
                throw new SerdeError(SerdeErrorCode::DuplicateKey, 'duplicate key');
            }
        }
    }

    // --- Helpers ---

    private function expect(string $ch): void
    {
        if ($this->pos >= strlen($this->input) || $this->input[$this->pos] !== $ch) {
            throw $this->syntaxErr("expected '{$ch}'");
        }
        $this->pos++;
    }

    private function expectStr(string $s): void
    {
        if (substr($this->input, $this->pos, strlen($s)) !== $s) {
            throw $this->syntaxErr("expected '{$s}'");
        }
        $this->pos += strlen($s);
    }

    private function skipWs(): void
    {
        while ($this->pos < strlen($this->input) && ($this->input[$this->pos] === ' ' || $this->input[$this->pos] === "\t")) {
            $this->pos++;
        }
    }

    private function skipWsNewlines(): void
    {
        while ($this->pos < strlen($this->input) && str_contains(" \t\r\n", $this->input[$this->pos])) {
            $this->pos++;
        }
    }

    private function skipWsNewlinesComments(): void
    {
        while (true) {
            $this->skipWsNewlines();
            if ($this->pos < strlen($this->input) && $this->input[$this->pos] === '#') {
                $this->skipComment();
            } else break;
        }
    }

    private function skipComment(): void
    {
        while ($this->pos < strlen($this->input) && $this->input[$this->pos] !== "\n") $this->pos++;
        if ($this->pos < strlen($this->input)) $this->pos++;
    }

    private function looksLikeDatetime(string $s): bool
    {
        if (strlen($s) >= 10 && $s[4] === '-' && $s[7] === '-' && ctype_digit($s[0])) return true;
        if (strlen($s) >= 5 && $s[2] === ':' && ctype_digit($s[0])) return true;
        return false;
    }

    private function parseDatetime(string $s): DateTimeValue
    {
        if ((str_contains($s, 'T') || str_contains($s, 't')) && strlen($s) > 10) {
            $rest = substr($s, 10);
            if (str_contains($rest, 'Z') || str_contains($rest, '+') || strrpos($rest, '-') > 0) {
                return new DateTimeValue('offset', $s);
            }
            return new DateTimeValue('local-datetime', $s);
        }
        if (strlen($s) === 10 && $s[4] === '-') {
            return new DateTimeValue('local-date', $s);
        }
        if (str_contains($s, ':') && !str_contains($s, '-')) {
            return new DateTimeValue('local-time', $s);
        }
        return new DateTimeValue('local-datetime', $s);
    }

    private function syntaxErr(string $msg): SerdeError
    {
        return new SerdeError(SerdeErrorCode::SyntaxError, $msg);
    }

    private function eof(): SerdeError
    {
        return new SerdeError(SerdeErrorCode::UnexpectedEof, 'unexpected end of input');
    }
}

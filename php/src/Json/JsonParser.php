<?php

declare(strict_types=1);

namespace LombokSerde\Json;

use LombokSerde\SerdeError;
use LombokSerde\SerdeErrorCode;

class JsonParser
{
    private string $input;
    private int $pos = 0;
    private int $maxDepth;

    public function __construct(string $input, int $maxDepth = 128)
    {
        $this->input = $input;
        $this->maxDepth = $maxDepth;
    }

    public static function parse(string $input, int $maxDepth = 128): mixed
    {
        $p = new self($input, $maxDepth);
        $val = $p->parseValue(0);
        $p->skipWs();
        if ($p->pos < strlen($p->input)) {
            throw new SerdeError(SerdeErrorCode::SyntaxError, 'trailing data');
        }
        return $val;
    }

    private function parseValue(int $depth): mixed
    {
        if ($depth > $this->maxDepth) {
            throw new SerdeError(SerdeErrorCode::DepthExceeded, 'max depth exceeded');
        }
        $this->skipWs();
        if ($this->pos >= strlen($this->input)) {
            throw $this->eof();
        }
        $ch = $this->input[$this->pos];
        return match (true) {
            $ch === '"' => $this->parseString(),
            $ch === '{' => $this->parseObject($depth),
            $ch === '[' => $this->parseArray($depth),
            $ch === 't' => $this->expectLiteral('true', true),
            $ch === 'f' => $this->expectLiteral('false', false),
            $ch === 'n' => $this->expectLiteral('null', null),
            $ch === '-' || ctype_digit($ch) => $this->parseNumber(),
            default => throw new SerdeError(SerdeErrorCode::SyntaxError, "unexpected character '{$ch}'"),
        };
    }

    private function parseObject(int $depth): array
    {
        $this->pos++; // skip '{'
        $obj = [];
        $this->skipWs();
        if ($this->pos < strlen($this->input) && $this->input[$this->pos] === '}') {
            $this->pos++;
            return $obj;
        }
        while (true) {
            $this->skipWs();
            if ($this->pos >= strlen($this->input) || $this->input[$this->pos] !== '"') {
                throw new SerdeError(SerdeErrorCode::SyntaxError, 'expected string key');
            }
            $key = $this->parseString();
            if (array_key_exists($key, $obj)) {
                throw new SerdeError(SerdeErrorCode::DuplicateKey, "duplicate key: {$key}");
            }
            $this->skipWs();
            if ($this->pos >= strlen($this->input) || $this->input[$this->pos] !== ':') {
                throw new SerdeError(SerdeErrorCode::SyntaxError, "expected ':'");
            }
            $this->pos++;
            $val = $this->parseValue($depth + 1);
            $obj[$key] = $val;
            $this->skipWs();
            if ($this->pos >= strlen($this->input)) {
                throw $this->eof();
            }
            if ($this->input[$this->pos] === '}') {
                $this->pos++;
                return $obj;
            }
            if ($this->input[$this->pos] !== ',') {
                throw new SerdeError(SerdeErrorCode::SyntaxError, "expected ',' or '}'");
            }
            $this->pos++;
        }
    }

    private function parseArray(int $depth): array
    {
        $this->pos++; // skip '['
        $arr = [];
        $this->skipWs();
        if ($this->pos < strlen($this->input) && $this->input[$this->pos] === ']') {
            $this->pos++;
            return $arr;
        }
        while (true) {
            $arr[] = $this->parseValue($depth + 1);
            $this->skipWs();
            if ($this->pos >= strlen($this->input)) {
                throw $this->eof();
            }
            if ($this->input[$this->pos] === ']') {
                $this->pos++;
                return $arr;
            }
            if ($this->input[$this->pos] !== ',') {
                throw new SerdeError(SerdeErrorCode::SyntaxError, "expected ',' or ']'");
            }
            $this->pos++;
        }
    }

    private function parseString(): string
    {
        $this->pos++; // skip '"'
        $parts = [];
        $start = $this->pos;
        $len = strlen($this->input);
        while (true) {
            if ($this->pos >= $len) {
                throw $this->eof();
            }
            $ch = $this->input[$this->pos];
            if ($ch === '"') {
                $parts[] = substr($this->input, $start, $this->pos - $start);
                $this->pos++;
                return implode('', $parts);
            }
            if ($ch === '\\') {
                $parts[] = substr($this->input, $start, $this->pos - $start);
                $this->pos++;
                $parts[] = $this->parseEscape();
                $start = $this->pos;
            } else {
                $this->pos++;
            }
        }
    }

    private function parseEscape(): string
    {
        if ($this->pos >= strlen($this->input)) {
            throw $this->eof();
        }
        $ch = $this->input[$this->pos++];
        return match ($ch) {
            '"' => '"',
            '\\' => '\\',
            '/' => '/',
            'b' => "\x08",
            'f' => "\x0C",
            'n' => "\n",
            'r' => "\r",
            't' => "\t",
            'u' => $this->parseUnicodeEscape(),
            default => throw new SerdeError(SerdeErrorCode::SyntaxError, "invalid escape '\\{$ch}'"),
        };
    }

    private function parseUnicodeEscape(): string
    {
        $cp = $this->parseHex4();
        // Surrogate pair
        if ($cp >= 0xD800 && $cp <= 0xDBFF) {
            if ($this->pos + 1 < strlen($this->input)
                && $this->input[$this->pos] === '\\'
                && $this->input[$this->pos + 1] === 'u') {
                $this->pos += 2;
                $lo = $this->parseHex4();
                if ($lo >= 0xDC00 && $lo <= 0xDFFF) {
                    $cp = 0x10000 + (($cp - 0xD800) << 10) + ($lo - 0xDC00);
                } else {
                    throw new SerdeError(SerdeErrorCode::InvalidUnicode, 'invalid surrogate pair');
                }
            } else {
                throw new SerdeError(SerdeErrorCode::InvalidUnicode, 'lone high surrogate');
            }
        } elseif ($cp >= 0xDC00 && $cp <= 0xDFFF) {
            throw new SerdeError(SerdeErrorCode::InvalidUnicode, 'lone low surrogate');
        }
        return mb_chr($cp, 'UTF-8');
    }

    private function parseHex4(): int
    {
        if ($this->pos + 4 > strlen($this->input)) {
            throw $this->eof();
        }
        $hex = substr($this->input, $this->pos, 4);
        $this->pos += 4;
        $val = hexdec($hex);
        if ($val === false) {
            throw new SerdeError(SerdeErrorCode::InvalidUnicode, "invalid hex: {$hex}");
        }
        return (int)$val;
    }

    private function parseNumber(): int|float
    {
        $start = $this->pos;
        $len = strlen($this->input);
        if ($this->input[$this->pos] === '-') {
            $this->pos++;
        }
        if ($this->pos >= $len) {
            throw $this->eof();
        }
        if ($this->input[$this->pos] === '0') {
            $this->pos++;
        } elseif (ctype_digit($this->input[$this->pos])) {
            while ($this->pos < $len && ctype_digit($this->input[$this->pos])) {
                $this->pos++;
            }
        } else {
            throw new SerdeError(SerdeErrorCode::SyntaxError, 'invalid number');
        }

        $isFloat = false;
        if ($this->pos < $len && $this->input[$this->pos] === '.') {
            $isFloat = true;
            $this->pos++;
            if ($this->pos >= $len || !ctype_digit($this->input[$this->pos])) {
                throw new SerdeError(SerdeErrorCode::SyntaxError, "expected digit after '.'");
            }
            while ($this->pos < $len && ctype_digit($this->input[$this->pos])) {
                $this->pos++;
            }
        }
        if ($this->pos < $len && ($this->input[$this->pos] === 'e' || $this->input[$this->pos] === 'E')) {
            $isFloat = true;
            $this->pos++;
            if ($this->pos < $len && ($this->input[$this->pos] === '+' || $this->input[$this->pos] === '-')) {
                $this->pos++;
            }
            if ($this->pos >= $len || !ctype_digit($this->input[$this->pos])) {
                throw new SerdeError(SerdeErrorCode::SyntaxError, 'expected digit in exponent');
            }
            while ($this->pos < $len && ctype_digit($this->input[$this->pos])) {
                $this->pos++;
            }
        }

        $raw = substr($this->input, $start, $this->pos - $start);
        if ($isFloat) {
            return (float)$raw;
        }
        return (int)$raw;
    }

    private function expectLiteral(string $literal, mixed $value): mixed
    {
        if (substr($this->input, $this->pos, strlen($literal)) !== $literal) {
            throw new SerdeError(SerdeErrorCode::SyntaxError, "expected '{$literal}'");
        }
        $this->pos += strlen($literal);
        return $value;
    }

    private function skipWs(): void
    {
        $len = strlen($this->input);
        while ($this->pos < $len && str_contains(" \t\r\n", $this->input[$this->pos])) {
            $this->pos++;
        }
    }

    private function eof(): SerdeError
    {
        return new SerdeError(SerdeErrorCode::UnexpectedEof, 'unexpected end of input');
    }
}

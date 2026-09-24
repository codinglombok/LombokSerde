<?php

declare(strict_types=1);

namespace LombokSerde\Json;

use LombokSerde\DateTimeValue;

class JsonSerializer
{
    public static function toString(mixed $value): string
    {
        return self::writeValue($value);
    }

    public static function toStringPretty(mixed $value, string $indent = '  '): string
    {
        return self::writePretty($value, $indent, 0);
    }

    private static function writeValue(mixed $value): string
    {
        if ($value === null) return 'null';
        if (is_bool($value)) return $value ? 'true' : 'false';
        if (is_int($value)) return (string)$value;
        if (is_float($value)) {
            if (is_nan($value) || is_infinite($value)) return 'null';
            return json_encode($value, JSON_PRESERVE_ZERO_FRACTION);
        }
        if (is_string($value)) return self::writeString($value);
        if ($value instanceof DateTimeValue) return self::writeString($value->value);
        if (is_array($value)) {
            if (array_is_list($value)) {
                // Array
                $items = array_map(fn($v) => self::writeValue($v), $value);
                return '[' . implode(',', $items) . ']';
            }
            // Map
            $pairs = [];
            foreach ($value as $k => $v) {
                $pairs[] = self::writeString((string)$k) . ':' . self::writeValue($v);
            }
            return '{' . implode(',', $pairs) . '}';
        }
        return self::writeString((string)$value);
    }

    private static function writePretty(mixed $value, string $indent, int $depth): string
    {
        if ($value === null) return 'null';
        if (is_bool($value)) return $value ? 'true' : 'false';
        if (is_int($value)) return (string)$value;
        if (is_float($value)) {
            if (is_nan($value) || is_infinite($value)) return 'null';
            return json_encode($value, JSON_PRESERVE_ZERO_FRACTION);
        }
        if (is_string($value)) return self::writeString($value);
        if ($value instanceof DateTimeValue) return self::writeString($value->value);
        if (is_array($value)) {
            if (array_is_list($value)) {
                if (empty($value)) return '[]';
                $inner = str_repeat($indent, $depth + 1);
                $outer = str_repeat($indent, $depth);
                $items = array_map(fn($v) => $inner . self::writePretty($v, $indent, $depth + 1), $value);
                return "[\n" . implode(",\n", $items) . "\n{$outer}]";
            }
            if (empty($value)) return '{}';
            $inner = str_repeat($indent, $depth + 1);
            $outer = str_repeat($indent, $depth);
            $pairs = [];
            foreach ($value as $k => $v) {
                $pairs[] = $inner . self::writeString((string)$k) . ': ' . self::writePretty($v, $indent, $depth + 1);
            }
            return "{\n" . implode(",\n", $pairs) . "\n{$outer}}";
        }
        return self::writeString((string)$value);
    }

    private static function writeString(string $s): string
    {
        $out = '"';
        $len = mb_strlen($s, 'UTF-8');
        for ($i = 0; $i < $len; $i++) {
            $ch = mb_substr($s, $i, 1, 'UTF-8');
            $out .= match ($ch) {
                '"' => '\\"',
                '\\' => '\\\\',
                "\x08" => '\\b',
                "\x0C" => '\\f',
                "\n" => '\\n',
                "\r" => '\\r',
                "\t" => '\\t',
                default => ord($ch) < 0x20 ? sprintf('\\u%04X', ord($ch)) : $ch,
            };
        }
        return $out . '"';
    }
}

<?php

declare(strict_types=1);

namespace LombokSerde\Toml;

use LombokSerde\DateTimeValue;

class TomlSerializer
{
    public static function stringify(array $value): string
    {
        return self::writeTable($value, []);
    }

    private static function writeTable(array $map, array $path): string
    {
        $out = '';
        // Simple key-value pairs first
        foreach ($map as $key => $value) {
            if (!self::isTableOrArrayOfTables($value)) {
                $out .= self::writeKey((string)$key) . ' = ' . self::writeValue($value) . "\n";
            }
        }
        // Sub-tables
        foreach ($map as $key => $value) {
            if (is_array($value) && !array_is_list($value) && !self::isInlineTable($value)) {
                $newPath = [...$path, (string)$key];
                $out .= "\n[" . implode('.', array_map([self::class, 'writeKey'], $newPath)) . "]\n";
                $out .= self::writeTable($value, $newPath);
            } elseif (is_array($value) && array_is_list($value) && self::isArrayOfTables($value)) {
                $newPath = [...$path, (string)$key];
                foreach ($value as $item) {
                    if (is_array($item) && !array_is_list($item)) {
                        $out .= "\n[[" . implode('.', array_map([self::class, 'writeKey'], $newPath)) . "]]\n";
                        $out .= self::writeTable($item, $newPath);
                    }
                }
            }
        }
        return $out;
    }

    private static function isTableOrArrayOfTables(mixed $value): bool
    {
        if (is_array($value) && !array_is_list($value) && !self::isInlineTable($value)) return true;
        if (is_array($value) && array_is_list($value) && self::isArrayOfTables($value)) return true;
        return false;
    }

    private static function isInlineTable(array $map): bool
    {
        if (count($map) > 4) return false;
        foreach ($map as $v) {
            if (!($v === null || is_bool($v) || is_int($v) || is_float($v)
                || is_string($v) || $v instanceof DateTimeValue)) {
                return false;
            }
        }
        return true;
    }

    private static function isArrayOfTables(array $arr): bool
    {
        if (empty($arr)) return false;
        foreach ($arr as $v) {
            if (!is_array($v) || array_is_list($v)) return false;
        }
        return true;
    }

    public static function writeKey(string $key): string
    {
        if (self::isBareKey($key)) return $key;
        return self::writeBasicString($key);
    }

    private static function isBareKey(string $key): bool
    {
        return strlen($key) > 0 && preg_match('/^[A-Za-z0-9_-]+$/', $key) === 1;
    }

    private static function writeValue(mixed $value): string
    {
        if ($value === null) return '"null"';
        if (is_bool($value)) return $value ? 'true' : 'false';
        if (is_int($value)) return (string)$value;
        if (is_float($value)) {
            if (is_nan($value)) return 'nan';
            if (is_infinite($value)) return $value < 0 ? '-inf' : 'inf';
            $s = (string)$value;
            if (!str_contains($s, '.') && !str_contains($s, 'e') && !str_contains($s, 'E')) {
                return $s . '.0';
            }
            return $s;
        }
        if (is_string($value)) return self::writeBasicString($value);
        if ($value instanceof DateTimeValue) return $value->value;
        if (is_array($value)) {
            if (array_is_list($value)) {
                return '[' . implode(', ', array_map([self::class, 'writeValue'], $value)) . ']';
            }
            // Inline table
            $pairs = [];
            foreach ($value as $k => $v) {
                $pairs[] = self::writeKey((string)$k) . ' = ' . self::writeValue($v);
            }
            return '{' . implode(', ', $pairs) . '}';
        }
        return self::writeBasicString((string)$value);
    }

    private static function writeBasicString(string $s): string
    {
        $out = '"';
        $len = mb_strlen($s, 'UTF-8');
        for ($i = 0; $i < $len; $i++) {
            $ch = mb_substr($s, $i, 1, 'UTF-8');
            $out .= match ($ch) {
                '"' => '\\"',
                '\\' => '\\\\',
                "\x08" => '\\b',
                "\t" => '\\t',
                "\n" => '\\n',
                "\x0C" => '\\f',
                "\r" => '\\r',
                default => ord($ch) < 0x20 ? sprintf('\\u%04X', ord($ch)) : $ch,
            };
        }
        return $out . '"';
    }
}

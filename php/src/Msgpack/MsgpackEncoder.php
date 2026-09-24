<?php

declare(strict_types=1);

namespace LombokSerde\Msgpack;

use LombokSerde\DateTimeValue;

class MsgpackEncoder
{
    public static function encode(mixed $value): string
    {
        $buf = '';
        self::encodeValue($value, $buf);
        return $buf;
    }

    private static function encodeValue(mixed $value, string &$buf): void
    {
        if ($value === null) { $buf .= chr(0xC0); return; }
        if (is_bool($value)) { $buf .= chr($value ? 0xC3 : 0xC2); return; }
        if (is_int($value)) { self::encodeInteger($value, $buf); return; }
        if (is_float($value)) { self::encodeFloat64($value, $buf); return; }
        if (is_string($value)) { self::encodeString($value, $buf); return; }
        if ($value instanceof DateTimeValue) { self::encodeString($value->value, $buf); return; }
        if (is_array($value)) {
            if (array_is_list($value)) {
                self::encodeArray($value, $buf);
            } else {
                self::encodeMap($value, $buf);
            }
            return;
        }
        self::encodeString((string)$value, $buf);
    }

    private static function encodeInteger(int $n, string &$buf): void
    {
        if ($n >= 0) {
            if ($n <= 127) {
                $buf .= chr($n);
            } elseif ($n <= 0xFF) {
                $buf .= chr(0xCC) . chr($n);
            } elseif ($n <= 0xFFFF) {
                $buf .= chr(0xCD) . pack('n', $n);
            } elseif ($n <= 0xFFFFFFFF) {
                $buf .= chr(0xCE) . pack('N', $n);
            } else {
                $buf .= chr(0xCF) . pack('J', $n);
            }
        } else {
            if ($n >= -32) {
                $buf .= chr($n & 0xFF);
            } elseif ($n >= -128) {
                $buf .= chr(0xD0) . chr($n & 0xFF);
            } elseif ($n >= -32768) {
                $buf .= chr(0xD1) . pack('n', $n & 0xFFFF);
            } elseif ($n >= -2147483648) {
                $buf .= chr(0xD2) . pack('N', $n & 0xFFFFFFFF);
            } else {
                $buf .= chr(0xD3) . pack('J', $n);
            }
        }
    }

    private static function encodeFloat64(float $f, string &$buf): void
    {
        $buf .= chr(0xCB) . pack('E', $f);
    }

    private static function encodeString(string $s, string &$buf): void
    {
        $len = strlen($s);
        if ($len <= 31) {
            $buf .= chr(0xA0 | $len);
        } elseif ($len <= 0xFF) {
            $buf .= chr(0xD9) . chr($len);
        } elseif ($len <= 0xFFFF) {
            $buf .= chr(0xDA) . pack('n', $len);
        } else {
            $buf .= chr(0xDB) . pack('N', $len);
        }
        $buf .= $s;
    }

    private static function encodeArray(array $arr, string &$buf): void
    {
        $len = count($arr);
        if ($len <= 15) {
            $buf .= chr(0x90 | $len);
        } elseif ($len <= 0xFFFF) {
            $buf .= chr(0xDC) . pack('n', $len);
        } else {
            $buf .= chr(0xDD) . pack('N', $len);
        }
        foreach ($arr as $v) {
            self::encodeValue($v, $buf);
        }
    }

    private static function encodeMap(array $map, string &$buf): void
    {
        $len = count($map);
        if ($len <= 15) {
            $buf .= chr(0x80 | $len);
        } elseif ($len <= 0xFFFF) {
            $buf .= chr(0xDE) . pack('n', $len);
        } else {
            $buf .= chr(0xDF) . pack('N', $len);
        }
        foreach ($map as $k => $v) {
            self::encodeString((string)$k, $buf);
            self::encodeValue($v, $buf);
        }
    }
}

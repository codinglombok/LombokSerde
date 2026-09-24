<?php

declare(strict_types=1);

namespace LombokSerde\Msgpack;

use LombokSerde\SerdeError;
use LombokSerde\SerdeErrorCode;

class MsgpackDecoder
{
    private string $data;
    private int $pos = 0;
    private int $len;

    public function __construct(string $data)
    {
        $this->data = $data;
        $this->len = strlen($data);
    }

    public static function decode(string $data): mixed
    {
        $d = new self($data);
        return $d->decodeValue();
    }

    public function decodeValue(): mixed
    {
        $byte = $this->readU8();

        // Positive fixint
        if ($byte <= 0x7F) return $byte;
        // Negative fixint
        if ($byte >= 0xE0) return $byte - 256;
        // Fixmap
        if ($byte >= 0x80 && $byte <= 0x8F) return $this->decodeMap($byte & 0x0F);
        // Fixarray
        if ($byte >= 0x90 && $byte <= 0x9F) return $this->decodeArray($byte & 0x0F);
        // Fixstr
        if ($byte >= 0xA0 && $byte <= 0xBF) return $this->decodeString($byte & 0x1F);

        return match ($byte) {
            0xC0 => null,
            0xC2 => false,
            0xC3 => true,
            // bin 8/16/32
            0xC4 => $this->decodeBin($this->readU8()),
            0xC5 => $this->decodeBin($this->readU16()),
            0xC6 => $this->decodeBin($this->readU32()),
            // ext 8/16/32
            0xC7 => (function() { $len = $this->readU8(); $this->pos++; return $this->decodeBin($len); })(),
            0xC8 => (function() { $len = $this->readU16(); $this->pos++; return $this->decodeBin($len); })(),
            0xC9 => (function() { $len = $this->readU32(); $this->pos++; return $this->decodeBin($len); })(),
            // float 32
            0xCA => (function() {
                if ($this->pos + 4 > $this->len) throw $this->eof();
                $v = unpack('G', substr($this->data, $this->pos, 4))[1];
                $this->pos += 4;
                return (float)$v;
            })(),
            // float 64
            0xCB => (function() {
                if ($this->pos + 8 > $this->len) throw $this->eof();
                $v = unpack('E', substr($this->data, $this->pos, 8))[1];
                $this->pos += 8;
                return (float)$v;
            })(),
            // uint 8/16/32/64
            0xCC => $this->readU8(),
            0xCD => $this->readU16(),
            0xCE => $this->readU32(),
            0xCF => $this->readU64(),
            // int 8
            0xD0 => (function() { $v = $this->readU8(); return $v > 127 ? $v - 256 : $v; })(),
            // int 16
            0xD1 => (function() { $v = $this->readU16(); return $v > 32767 ? $v - 65536 : $v; })(),
            // int 32
            0xD2 => (function() { $v = $this->readU32(); return $v > 0x7FFFFFFF ? $v - 0x100000000 : $v; })(),
            // int 64
            0xD3 => (function() {
                if ($this->pos + 8 > $this->len) throw $this->eof();
                $v = unpack('J', substr($this->data, $this->pos, 8))[1];
                $this->pos += 8;
                // PHP's unpack('J') returns signed int64 on 64-bit
                return $v;
            })(),
            // fixext 1/2/4/8/16
            0xD4 => (function() { $this->pos++; return $this->decodeBin(1); })(),
            0xD5 => (function() { $this->pos++; return $this->decodeBin(2); })(),
            0xD6 => (function() { $this->pos++; return $this->decodeBin(4); })(),
            0xD7 => (function() { $this->pos++; return $this->decodeBin(8); })(),
            0xD8 => (function() { $this->pos++; return $this->decodeBin(16); })(),
            // str 8/16/32
            0xD9 => $this->decodeString($this->readU8()),
            0xDA => $this->decodeString($this->readU16()),
            0xDB => $this->decodeString($this->readU32()),
            // array 16/32
            0xDC => $this->decodeArray($this->readU16()),
            0xDD => $this->decodeArray($this->readU32()),
            // map 16/32
            0xDE => $this->decodeMap($this->readU16()),
            0xDF => $this->decodeMap($this->readU32()),
            default => throw new SerdeError(SerdeErrorCode::SyntaxError, sprintf('unknown msgpack byte 0x%02x', $byte)),
        };
    }

    private function decodeString(int $length): string
    {
        $end = $this->pos + $length;
        if ($end > $this->len) throw $this->eof();
        $s = substr($this->data, $this->pos, $length);
        $this->pos = $end;
        return $s;
    }

    private function decodeBin(int $length): string
    {
        $end = $this->pos + $length;
        if ($end > $this->len) throw $this->eof();
        $b = substr($this->data, $this->pos, $length);
        $this->pos = $end;
        return $b;
    }

    private function decodeArray(int $length): array
    {
        $arr = [];
        for ($i = 0; $i < $length; $i++) {
            $arr[] = $this->decodeValue();
        }
        return $arr;
    }

    private function decodeMap(int $length): array
    {
        $map = [];
        for ($i = 0; $i < $length; $i++) {
            $key = $this->decodeValue();
            $val = $this->decodeValue();
            $map[(string)$key] = $val;
        }
        return $map;
    }

    private function readU8(): int
    {
        if ($this->pos >= $this->len) throw $this->eof();
        return ord($this->data[$this->pos++]);
    }

    private function readU16(): int
    {
        if ($this->pos + 2 > $this->len) throw $this->eof();
        $v = unpack('n', substr($this->data, $this->pos, 2))[1];
        $this->pos += 2;
        return $v;
    }

    private function readU32(): int
    {
        if ($this->pos + 4 > $this->len) throw $this->eof();
        $v = unpack('N', substr($this->data, $this->pos, 4))[1];
        $this->pos += 4;
        return $v;
    }

    private function readU64(): int
    {
        if ($this->pos + 8 > $this->len) throw $this->eof();
        $v = unpack('J', substr($this->data, $this->pos, 8))[1];
        $this->pos += 8;
        return $v;
    }

    private function eof(): SerdeError
    {
        return new SerdeError(SerdeErrorCode::UnexpectedEof, 'unexpected eof');
    }
}

<?php

declare(strict_types=1);

/**
 * Shared vector runner (mirrors python/tests/vectors_common.py).
 * Usage: php tests/vectors.php
 */

require __DIR__ . '/bootstrap.php';

use CodingLombok\LombokSerde\Json;
use CodingLombok\LombokSerde\JsonOptions;
use CodingLombok\LombokSerde\MsgPackOptions;
use CodingLombok\LombokSerde\Msgpack;
use CodingLombok\LombokSerde\SerdeError;
use CodingLombok\LombokSerde\TableEntry;
use CodingLombok\LombokSerde\Toml;
use CodingLombok\LombokSerde\TomlOptions;
use CodingLombok\LombokSerde\Value;

const VECTORS_PATH = __DIR__ . '/../../vectors/lombokserde-vectors-v1.json';

const TAGS = ['null', 'bool', 'int', 'uint', 'float', 'str', 'bytes', 'array', 'table', 'datetime'];

function isValueTagged($v): bool
{
    return \is_array($v) && \count($v) >= 1 && \is_string($v[0]) && \in_array($v[0], TAGS, true);
}

function valueEq($a, $b): bool
{
    if (!isValueTagged($a) || !isValueTagged($b)) {
        return $a === $b;
    }
    if ($a[0] !== $b[0]) {
        return false;
    }
    switch ($a[0]) {
        case 'null':
            return true;
        case 'bool':
        case 'int':
        case 'uint':
        case 'str':
        case 'bytes':
            return $a[1] === $b[1];
        case 'float':
            return \pack('E', $a[1]) === \pack('E', $b[1]);
        case 'datetime':
            return $a[1] === $b[1] && $a[2] === $b[2];
        case 'array':
            if (\count($a[1]) !== \count($b[1])) {
                return false;
            }
            foreach ($a[1] as $i => $x) {
                if (!valueEq($x, $b[1][$i])) {
                    return false;
                }
            }

            return true;
        case 'table':
            if (\count($a[1]) !== \count($b[1])) {
                return false;
            }
            foreach ($a[1] as $i => $kv) {
                if ($kv[0] !== $b[1][$i][0] || !valueEq($kv[1], $b[1][$i][1])) {
                    return false;
                }
            }

            return true;
    }

    return false;
}

/** Parse the VVE (vector value encoding) into a Value. */
function vveParse($v): Value
{
    if ($v === null) {
        return Value::null();
    }
    if (\is_bool($v)) {
        return Value::bool($v);
    }
    if (\is_string($v)) {
        return Value::str($v);
    }
    if (\is_array($v) && !\array_is_list($v)) {
        // tagged object with exactly one key
        if (\count($v) !== 1) {
            throw new RuntimeException('VVE object must have exactly one key');
        }
        $tag = \array_key_first($v);
        $payload = $v[$tag];
        switch ($tag) {
            case '$i':
                return Value::int((int) $payload);
            case '$u':
                return Value::uint((string) $payload);
            case '$f':
                if ($payload === 'inf') {
                    return Value::float(\INF);
                }
                if ($payload === '-inf') {
                    return Value::float(-\INF);
                }
                if ($payload === 'nan') {
                    return Value::float(\unpack('E', "\x7F\xF8\x00\x00\x00\x00\x00\x00")[1]);
                }

                return Value::float((float) $payload);
            case '$b':
                return Value::bytes(\hex2bin($payload));
            case '$d':
                return Value::datetime($payload[0], $payload[1]);
            case '$t':
                $pairs = [];
                foreach ($payload as $kv) {
                    $pairs[] = new TableEntry($kv[0], vveParse($kv[1]));
                }

                return Value::tableUnchecked($pairs);
            default:
                throw new RuntimeException("unknown VVE tag {$tag}");
        }
    }
    if (\is_array($v)) {
        return Value::array(\array_map('vveParse', $v));
    }
    throw new RuntimeException('unexpected VVE node');
}

/** Lowers a Value into the plain form vveParse consumes. */
function valueToPlain(Value $v)
{
    switch ($v->kind) {
        case Value::KIND_NULL:
            return null;
        case Value::KIND_BOOL:
            return $v->bool;
        case Value::KIND_INT:
            return $v->int;
        case Value::KIND_UINT:
            return ['$u' => $v->uintStr];
        case Value::KIND_FLOAT:
            if (\is_nan($v->float)) {
                return ['$f' => 'nan'];
            }
            if (\is_infinite($v->float)) {
                return ['$f' => $v->float > 0 ? 'inf' : '-inf'];
            }

            return ['$f' => (string) $v->float];
        case Value::KIND_STR:
            return $v->str;
        case Value::KIND_BYTES:
            return ['$b' => hexEncode($v->bytes)];
        case Value::KIND_DATETIME:
            return ['$d' => [$v->datetime->kind, $v->datetime->raw]];
        case Value::KIND_ARRAY:
            return \array_map('valueToPlain', $v->array);
        case Value::KIND_TABLE:
            $pairs = [];
            foreach ($v->table as $e) {
                $pairs[] = [$e->key, valueToPlain($e->value)];
            }

            return ['$t' => $pairs];
    }
    throw new RuntimeException('bad kind');
}

/** Reconstructs the original JSON shape of a case (Value -> plain PHP). */
function caseToPlain(Value $v)
{
    switch ($v->kind) {
        case Value::KIND_NULL:
            return null;
        case Value::KIND_BOOL:
            return $v->bool;
        case Value::KIND_INT:
            return $v->int;
        case Value::KIND_STR:
            return $v->str;
        case Value::KIND_ARRAY:
            return \array_map('caseToPlain', $v->array);
        case Value::KIND_TABLE:
            $out = [];
            foreach ($v->table as $e) {
                $out[$e->key] = caseToPlain($e->value);
            }

            return $out;
    }
    throw new RuntimeException('bad case kind');
}

/** Lowers a Value to the tagged-array form used by valueEq. */
function valueToTagged(Value $v)
{
    switch ($v->kind) {
        case Value::KIND_NULL:
            return ['null'];
        case Value::KIND_BOOL:
            return ['bool', $v->bool];
        case Value::KIND_INT:
            return ['int', $v->int];
        case Value::KIND_UINT:
            return ['uint', $v->uintStr];
        case Value::KIND_FLOAT:
            return ['float', $v->float];
        case Value::KIND_STR:
            return ['str', $v->str];
        case Value::KIND_BYTES:
            return ['bytes', $v->bytes];
        case Value::KIND_DATETIME:
            return ['datetime', $v->datetime->raw, $v->datetime->kind];
        case Value::KIND_ARRAY:
            return ['array', \array_map('valueToTagged', $v->array)];
        case Value::KIND_TABLE:
            $pairs = [];
            foreach ($v->table as $e) {
                $pairs[] = [$e->key, valueToTagged($e->value)];
            }

            return ['table', $pairs];
    }
    throw new RuntimeException('bad kind');
}

function textInput(array $c): string
{
    if (isset($c['input'])) {
        return $c['input'];
    }
    if (isset($c['input_hex'])) {
        return \hex2bin($c['input_hex']);
    }
    throw new RuntimeException('case has neither input nor input_hex');
}

function hexEncode(string $b): string
{
    $out = '';
    foreach (\str_split($b) as $ch) {
        $out .= \str_pad(\dechex(\ord($ch)), 2, '0', \STR_PAD_LEFT);
    }

    return $out;
}

function runCase(array $c): array
{
    $depth = $c['options']['depth'] ?? Json::DEFAULT_DEPTH_LIMIT;
    $fmt = $c['format'];
    if ($c['op'] === 'decode') {
        $raw = textInput($c);
        if ($fmt === 'json') {
            $v = Json::decode($raw, new JsonOptions($depth));

            return ['value' => $v, 'encoding' => Json::encode($v, new JsonOptions($depth))];
        }
        if ($fmt === 'toml') {
            $v = Toml::decode($raw, new TomlOptions($depth));

            return ['value' => $v, 'encoding' => Toml::encode($v, new TomlOptions($depth))];
        }
        $v = Msgpack::decode($raw, new MsgPackOptions($depth));

        return ['value' => $v, 'encoding' => hexEncode(Msgpack::encode($v, new MsgPackOptions($depth)))];
    }
    $v = vveParse($c['value']);
    if ($fmt === 'json') {
        $raw = Json::encode($v, new JsonOptions($depth));

        return ['value' => Json::decode($raw, new JsonOptions($depth)), 'encoding' => $raw];
    }
    if ($fmt === 'toml') {
        $raw = Toml::encode($v, new TomlOptions($depth));

        return ['value' => Toml::decode($raw, new TomlOptions($depth)), 'encoding' => $raw];
    }
    $enc = Msgpack::encode($v, new MsgPackOptions($depth));

    return ['value' => Msgpack::decode($enc, new MsgPackOptions($depth)), 'encoding' => hexEncode($enc)];
}

function checkCase(array $c): ?string
{
    $ident = $c['id'];
    $expect = $c['expect'];
    try {
        $got = runCase($c);
    } catch (SerdeError $e) {
        $expErr = $expect['error'] ?? null;
        if ($expErr === null) {
            return "{$ident}: operation failed but no error expected: {$e->getMessage()}";
        }
        if ($e->code() !== $expErr['code']) {
            return "{$ident}: error code mismatch: got {$e->code()} want {$expErr['code']}";
        }
        $wantOffset = $expErr['offset'] ?? null;
        if ($e->offset !== $wantOffset) {
            $go = $e->offset === null ? 'null' : (string) $e->offset;
            $wo = $wantOffset === null ? 'null' : (string) $wantOffset;

            return "{$ident}: error offset mismatch: got {$go} want {$wo}";
        }

        return null;
    }
    if (($expect['error'] ?? null) !== null) {
        return "{$ident}: expected an error but the operation succeeded";
    }
    if (isset($expect['value'])) {
        $want = valueToTagged(vveParse($expect['value']));
        if (!valueEq(valueToTagged($got['value']), $want)) {
            return "{$ident}: value mismatch";
        }
    }
    if (isset($expect['encoding'])) {
        if ($got['encoding'] !== $expect['encoding']) {
            return "{$ident}: encoding mismatch\n  got:  {$got['encoding']}\n  want: {$expect['encoding']}";
        }
    }

    return null;
}

$raw = \file_get_contents(VECTORS_PATH);
if ($raw === false) {
    fwrite(STDERR, "vectors file missing\n");
    exit(2);
}
// dogfood: the vector file is parsed with this port's own JSON decoder
$doc = Json::decode($raw, new JsonOptions(Json::DEFAULT_DEPTH_LIMIT));
$cases = $doc->tableGet('cases');
if ($cases === null || $cases->kind !== Value::KIND_ARRAY) {
    fwrite(STDERR, "vectors: missing cases array\n");
    exit(2);
}
$failures = 0;
$total = 0;
foreach ($cases->array as $caseV) {
    $total++;
    $fail = checkCase(caseToPlain($caseV));
    if ($fail !== null) {
        $failures++;
        echo "FAIL {$fail}\n";
    }
}
echo "vectors: {$total} cases, {$failures} failures\n";
exit($failures === 0 ? 0 : 1);

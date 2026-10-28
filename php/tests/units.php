<?php

declare(strict_types=1);

/**
 * Unit battery (mirrors go/units_test.go + go/coverage_extra_test.go).
 * Usage: php tests/units.php
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
use CodingLombok\LombokSerde\U64;
use CodingLombok\LombokSerde\Value;

$tests = [];
$passed = 0;
$failed = 0;

function test(string $name, callable $fn): void
{
    global $tests;
    $tests[] = [$name, $fn];
}

function canonNan(): float
{
    return \unpack('E', "\x7F\xF8\x00\x00\x00\x00\x00\x00")[1];
}

// --- float presentation ------------------------------------------------------

test('float_presentation_all_regimes', function (): void {
    $cases = [
        [0.0, '0.0'], [-0.0, '-0.0'], [1.0, '1.0'], [-1.5, '-1.5'],
        [0.001, '0.001'], [1e-6, '0.000001'], [1e-7, '1e-7'], [2.5e-10, '2.5e-10'],
        [1e20, '100000000000000000000.0'], [1e21, '1e+21'], [-1.5e300, '-1.5e+300'],
        [5e-324, '5e-324'], [123.456, '123.456'], [12.5, '12.5'],
    ];
    foreach ($cases as [$f, $want]) {
        $got = Json::encode(Value::float($f), null);
        if ($got !== $want) {
            throw new RuntimeException("float render: {$f} -> {$got}, want {$want}");
        }
    }
});

// --- JSON edges ----------------------------------------------------------------

test('json_unicode_edges', function (): void {
    foreach (['"\\u00"', '"\\uzzzz"', '"\\uD800"', '"\\uD800\\u0041"', '"\\uDC00\\uD800"'] as $bad) {
        try {
            Json::decode($bad, null);
            throw new RuntimeException("must reject {$bad}");
        } catch (SerdeError $e) {
            // expected
        }
    }
    $v = Json::decode('"\\uD83D\\uDE00"', null);
    if ($v->str !== "\u{1F600}") {
        throw new RuntimeException('surrogate pair decode');
    }
});

test('json_int_range_edges', function (): void {
    if (Json::decode('9223372036854775807', null)->int !== \PHP_INT_MAX) {
        throw new RuntimeException('i64 max');
    }
    if (Json::decode('-9223372036854775808', null)->int !== \PHP_INT_MIN) {
        throw new RuntimeException('i64 min');
    }
    if (Json::decode('18446744073709551615', null)->uintStr !== '18446744073709551615') {
        throw new RuntimeException('u64 max');
    }
    // 2^63 crosses into the uint family; only beyond u64max errors
    if (Json::decode('9223372036854775808', null)->uintStr !== '9223372036854775808') {
        throw new RuntimeException('2^63 must be a uint');
    }
    foreach (['-9223372036854775809', '18446744073709551616'] as $bad) {
        try {
            Json::decode($bad, null);
            throw new RuntimeException("must reject {$bad}");
        } catch (SerdeError $e) {
            if ($e->code() !== 'SERDE_JSON_INT_RANGE') {
                throw new RuntimeException("{$bad}: wrong code {$e->code()}");
            }
        }
    }
    // float overflow/underflow follow Rust: +/-Inf and +/-0
    if (Json::decode('1e999', null)->float !== \INF) {
        throw new RuntimeException('1e999');
    }
    if (Json::decode('1e-999', null)->float !== 0.0) {
        throw new RuntimeException('1e-999');
    }
});

test('json_depth_and_trailing', function (): void {
    try {
        Json::decode('[[[[1]]]]', new JsonOptions(2));
        throw new RuntimeException('depth must fail');
    } catch (SerdeError $e) {
        if ($e->code() !== 'SERDE_JSON_DEPTH') {
            throw new RuntimeException('wrong code');
        }
    }
    try {
        Json::decode('{} x', null);
        throw new RuntimeException('trailing must fail');
    } catch (SerdeError $e) {
        if ($e->code() !== 'SERDE_JSON_TRAILING') {
            throw new RuntimeException('wrong code');
        }
    }
    // encode depth on tables
    $deep = Value::table([new TableEntry('a', Value::table([new TableEntry('b', Value::table([new TableEntry('c', Value::int(1))]))]))]);
    try {
        Json::encode($deep, new JsonOptions(2));
        throw new RuntimeException('encode depth must fail');
    } catch (SerdeError $e) {
        if ($e->code() !== 'SERDE_JSON_DEPTH' || $e->offset !== null) {
            throw new RuntimeException('encode depth error shape');
        }
    }
});

test('json_duplicate_key', function (): void {
    try {
        Json::decode('{"a":1,"a":2}', null);
        throw new RuntimeException('dup must fail');
    } catch (SerdeError $e) {
        if ($e->code() !== 'SERDE_JSON_SYNTAX') {
            throw new RuntimeException('wrong code: ' . $e->code());
        }
    }
});

// --- MessagePack widths ----------------------------------------------------------

test('msgpack_int_widths', function (): void {
    $cases = [
        [Value::int(-33), "\xD0"], [Value::int(-129), "\xD1"],
        [Value::int(-32769), "\xD2"], [Value::int(-2147483649), "\xD3"],
        [Value::int(128), "\xCC"], [Value::int(256), "\xCD"], [Value::int(65536), "\xCE"],
        [Value::int(-128), "\xD0\x80"], [Value::int(-32768), "\xD1\x80\x00"],
        [Value::int(-2147483648), "\xD2\x80\x00\x00\x00"],
        [Value::int(\PHP_INT_MIN), "\xD3\x80\x00\x00\x00\x00\x00\x00\x00"],
    ];
    foreach ($cases as [$v, $want]) {
        $enc = Msgpack::encode($v, null);
        if (!\str_starts_with($enc, $want)) {
            throw new RuntimeException('width: ' . bin2hex($enc) . " want {$want}");
        }
        $back = Msgpack::decode($enc, null);
        if ($back->kind !== $v->kind || $back->int !== $v->int) {
            throw new RuntimeException('roundtrip');
        }
    }
    // uint families
    if (Msgpack::encode(Value::uint(4294967296), null)[0] !== "\xCF") {
        throw new RuntimeException('u32+1 prefix');
    }
    $big = Msgpack::encode(Value::uint('18446744073709551615'), null);
    if ($big !== "\xCF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF") {
        throw new RuntimeException('u64 max: ' . bin2hex($big));
    }
    $back = Msgpack::decode($big, null);
    if ($back->kind !== Value::KIND_UINT || $back->uintStr !== '18446744073709551615') {
        throw new RuntimeException('u64 max roundtrip');
    }
});

test('msgpack_size_families', function (): void {
    $rt = static fn (Value $v): Value => Msgpack::decode(Msgpack::encode($v, null), null);
    if ($rt(Value::int(255))->int !== 255) {
        throw new RuntimeException('u8');
    }
    $a = Value::array(\array_fill(0, 65537, Value::null()));
    if (\count($rt($a)->array) !== 65537) {
        throw new RuntimeException('array16+');
    }
    $pairs = [];
    for ($j = 0; $j < 65537; $j++) {
        $pairs[] = new TableEntry("k{$j}", Value::int($j));
    }
    $m = Value::tableUnchecked($pairs);
    if (\count($rt($m)->table) !== 65537) {
        throw new RuntimeException('map32');
    }
    // 0xc1 reserved
    try {
        Msgpack::decode("\xc1", null);
        throw new RuntimeException('0xc1 must fail');
    } catch (SerdeError $e) {
        if ($e->code() !== 'SERDE_MP_UNEXPECTED') {
            throw new RuntimeException('wrong code');
        }
    }
    // ext8 carrier with a valid ts32 payload
    $ts = Msgpack::decode("\xc7\x04\xff\x01\x02\x03\x04", null);
    $direct = Msgpack::decode("\xd6\xff\x01\x02\x03\x04", null);
    if ($ts->datetime->raw !== $direct->datetime->raw) {
        throw new RuntimeException('ext8 ts32');
    }
});

test('msgpack_datetime_errors', function (): void {
    try {
        Msgpack::encode(Value::datetime('date', '2024-01-01'), null);
        throw new RuntimeException('local date must fail');
    } catch (SerdeError $e) {
        if ($e->code() !== 'SERDE_MP_DATETIME') {
            throw new RuntimeException('wrong code');
        }
    }
    try {
        Msgpack::encode(Value::datetime('offset', 'not-a-date'), null);
        throw new RuntimeException('bad raw must fail');
    } catch (SerdeError $e) {
        if ($e->code() !== 'SERDE_MP_DATETIME') {
            throw new RuntimeException('wrong code');
        }
    }
    // big seconds fall to the ext64 carrier and decode back
    $v = Value::datetime('offset', '2286-11-20T17:46:40Z');
    $enc = Msgpack::encode($v, null);
    $got = Msgpack::decode($enc, null);
    if ($got->datetime->raw !== $v->datetime->raw) {
        throw new RuntimeException('ext64 roundtrip');
    }
    // negative seconds use the ext96 carrier
    $neg = Value::datetime('offset', '1969-12-31T23:59:59Z');
    $enc = Msgpack::encode($neg, null);
    if (!\str_starts_with($enc, "\xC7\x0C\xFF")) {
        throw new RuntimeException('neg sec carrier: ' . bin2hex($enc));
    }
    if (Msgpack::decode($enc, null)->datetime->raw !== $neg->datetime->raw) {
        throw new RuntimeException('neg roundtrip');
    }
});

test('msgpack_depth', function (): void {
    $deep = Value::null();
    for ($i = 0; $i < 5; $i++) {
        $deep = Value::array([$deep]);
    }
    $enc = Msgpack::encode($deep, null);
    try {
        Msgpack::decode($enc, new MsgPackOptions(2));
        throw new RuntimeException('decode depth must fail');
    } catch (SerdeError $e) {
        if ($e->code() !== 'SERDE_MP_DEPTH') {
            throw new RuntimeException('wrong code');
        }
    }
    try {
        Msgpack::encode($deep, new MsgPackOptions(2));
        throw new RuntimeException('encode depth must fail');
    } catch (SerdeError $e) {
        if ($e->code() !== 'SERDE_MP_DEPTH') {
            throw new RuntimeException('wrong code');
        }
    }
});

// --- TOML edges ------------------------------------------------------------------

test('toml_offset_datetime_arithmetic', function (): void {
    $v = Toml::decode("a = 2024-01-01T12:00:00+01:00\n", null);
    if ($v->tableGet('a')->datetime->raw !== '2024-01-01T12:00:00+01:00') {
        throw new RuntimeException('raw preserved');
    }
});

test('toml_radix_and_signs', function (): void {
    $d = Toml::decode("a = 0xFF\nc = 0o7\nd = 0b1\n", null);
    if ($d->tableGet('a')->int !== 255) {
        throw new RuntimeException('0xFF');
    }
    try {
        Toml::decode("x = -0x1\n", null);
        throw new RuntimeException('signed hex must be rejected');
    } catch (SerdeError $e) {
        // expected
    }
});

test('toml_table_edges', function (): void {
    // table and value share a key
    try {
        Toml::decode("[a]\nb.c = 1\n[a.b]\nd = 2\n", null);
        throw new RuntimeException('share key must fail');
    } catch (SerdeError $e) {
        if ($e->code() !== 'SERDE_TOML_DUPLICATE') {
            throw new RuntimeException('wrong code: ' . $e->code());
        }
    }
    // super-table after sub-table is fine
    $v = Toml::decode("[a.b]\nx = 1\n[a]\ny = 2\n", null);
    if ($v->tableGet('a')->tableGet('b')->tableGet('x')->int !== 1) {
        throw new RuntimeException('late super table');
    }
    foreach (["[a]\n[a]\n", "[[a]]\n[a]\n"] as $bad) {
        try {
            Toml::decode($bad, null);
            throw new RuntimeException('redefine must fail');
        } catch (SerdeError $e) {
            if ($e->code() !== 'SERDE_TOML_DUPLICATE') {
                throw new RuntimeException('wrong code');
            }
        }
    }
});

test('toml_quoted_keys_and_inline', function (): void {
    $v = Toml::decode("[\"a\\\"b\"]\n\"c,d\" = 1\n", null);
    if ($v->tableGet('a"b')->tableGet('c,d')->int !== 1) {
        throw new RuntimeException('quoted roundtrip');
    }
    foreach (['a = {x = 1, x = 2}' => 'SERDE_TOML_SYNTAX', 'a = {x = 1,}' => 'SERDE_TOML_SYNTAX'] as $bad => $code) {
        try {
            Toml::decode($bad . "\n", null);
            throw new RuntimeException('inline must fail');
        } catch (SerdeError $e) {
            if ($e->code() !== $code) {
                throw new RuntimeException("wrong code {$e->code()}");
            }
        }
    }
    $v = Toml::decode("a = {b.c = 1}\n", null);
    if ($v->tableGet('a')->tableGet('b')->tableGet('c')->int !== 1) {
        throw new RuntimeException('inline dotted');
    }
    $v = Toml::decode("[[a]]\nb = 1\n[[a]]\nb = 2\n", null);
    if (\count($v->tableGet('a')->array) !== 2) {
        throw new RuntimeException('aot len');
    }
});

test('toml_ml_literal_edges', function (): void {
    $cases = [
        ["a = ''''''\n", ''],
        ["a = '''\n'''\n", ''],
        ["a = '''x''y'''\n", "x''y"],
    ];
    foreach ($cases as [$in, $want]) {
        $v = Toml::decode($in, null);
        if ($v->tableGet('a')->str !== $want) {
            throw new RuntimeException("ml literal: {$in}");
        }
    }
    foreach (["a = '''x\n", "a = ''''q''''\n"] as $bad) {
        try {
            Toml::decode($bad, null);
            throw new RuntimeException('must fail');
        } catch (SerdeError $e) {
            // expected
        }
    }
});

test('toml_datetime_shapes', function (): void {
    foreach (["d = 1979-05-27\n", "t = 07:32:00\n", "t = 07:32:00.999\n", "dt = 1979-05-27 07:32:00Z\n"] as $good) {
        Toml::decode($good, null);
    }
    foreach (["d = 1979-05-99\n", "t = 07:32\n", "dt = 1979-05-27T07:32:00+\n"] as $bad) {
        try {
            Toml::decode($bad, null);
            throw new RuntimeException('must reject');
        } catch (SerdeError $e) {
            // expected
        }
    }
});

test('toml_encode_edges', function (): void {
    foreach (
        [
            [Value::table([new TableEntry('n', Value::null())]), 'SERDE_TOML_SYNTAX'],
            [Value::table([new TableEntry('u', Value::uint('9223372036854775808'))]), 'SERDE_TOML_SYNTAX'],
            [Value::table([new TableEntry('d', Value::datetime('offset', 'junk'))]), 'SERDE_TOML_DATETIME'],
            [Value::table([new TableEntry('b', Value::bytes("\x01"))]), 'SERDE_TOML_BYTES'],
        ] as [$v, $code]
    ) {
        try {
            Toml::encode($v, null);
            throw new RuntimeException('encode must fail');
        } catch (SerdeError $e) {
            if ($e->code() !== $code) {
                throw new RuntimeException("wrong code {$e->code()}");
            }
        }
    }
    try {
        Toml::encode(Value::int(1), null);
        throw new RuntimeException('root must fail');
    } catch (SerdeError $e) {
        if ($e->code() !== 'SERDE_TOML_ROOT') {
            throw new RuntimeException('wrong code');
        }
    }
    // nan/inf
    $out = Toml::encode(Value::table([new TableEntry('x', Value::float(\NAN)), new TableEntry('y', Value::float(\INF)), new TableEntry('z', Value::float(-\INF))]), null);
    if (!\str_contains($out, 'nan') || !\str_contains($out, 'inf')) {
        throw new RuntimeException('nan/inf text');
    }
    // depth
    $deep = Value::null();
    for ($i = 0; $i < 5; $i++) {
        $deep = Value::array([$deep]);
    }
    try {
        Toml::encode(Value::table([new TableEntry('a', $deep)]), new TomlOptions(2));
        throw new RuntimeException('depth must fail');
    } catch (SerdeError $e) {
        if ($e->code() !== 'SERDE_TOML_DEPTH') {
            throw new RuntimeException('wrong code');
        }
    }
});

// --- value model -------------------------------------------------------------------

test('table_sorted_bytewise', function (): void {
    $t = Value::table([
        new TableEntry('z', Value::int(1)),
        new TableEntry('M', Value::int(3)),
        new TableEntry('a', Value::int(2)),
        new TableEntry('é', Value::float(-0.5)),
    ]);
    $keys = \array_map(static fn (TableEntry $e): string => $e->key, $t->table);
    if ($keys !== ['M', 'a', 'z', 'é']) {
        throw new RuntimeException('bytewise order: ' . \implode(',', $keys));
    }
    try {
        Value::table([new TableEntry('a', Value::int(1)), new TableEntry('a', Value::int(2))]);
        throw new RuntimeException('dup must fail');
    } catch (SerdeError $e) {
        if ($e->code() !== 'SERDE_TABLE_DUPLICATE') {
            throw new RuntimeException('wrong code');
        }
    }
});

test('u64_string_math', function (): void {
    if (U64::fromBytes("\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF") !== '18446744073709551615') {
        throw new RuntimeException('fromBytes u64 max');
    }
    if (U64::toBytes8('18446744073709551615') !== "\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF") {
        throw new RuntimeException('toBytes8 u64 max');
    }
    if (U64::i64ToBytes8(-1) !== "\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF") {
        throw new RuntimeException('i64 -1');
    }
    if (U64::i64ToBytes8(\PHP_INT_MIN) !== "\x80\x00\x00\x00\x00\x00\x00\x00") {
        throw new RuntimeException('i64 min');
    }
    if (U64::decSub('1000', '1') !== '999') {
        throw new RuntimeException('decSub');
    }
    if (U64::decAdd('999', '1') !== '1000') {
        throw new RuntimeException('decAdd');
    }
    if (U64::mulInt('12345', 100) !== '1234500') {
        throw new RuntimeException('mulInt');
    }
});

// --- runner ---

function run_unit_suite(): array
{
    global $tests, $passed, $failed;
    $passed = 0;
    $failed = 0;

    foreach ($tests as [$name, $fn]) {
        try {
            $fn();
            $passed++;
            echo "ok   {$name}\n";
        } catch (Throwable $e) {
            $failed++;
            echo "FAIL {$name}: {$e->getMessage()} @ {$e->getFile()}:{$e->getLine()}\n";
        }
    }
    echo "units: " . \count($tests) . " tests, {$passed} passed, {$failed} failed\n";

    return [$passed, $failed];
}

if (!\defined('LOMBOKSERDE_INCLUDED')) {
    [$_p, $_f] = run_unit_suite();
    exit($_f === 0 ? 0 : 1);
}

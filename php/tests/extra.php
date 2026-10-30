<?php

declare(strict_types=1);

/**
 * Extra coverage battery (complements units.php, mirroring the spirit of
 * go/coverage_extra_test.go): parser/encoder error paths, escape variants,
 * datetime shapes, MessagePack width carriers and calendar edges that the
 * shared vectors do not exercise. Loaded by tests/run.php.
 */

use CodingLombok\LombokSerde\Json;
use CodingLombok\LombokSerde\Msgpack;
use CodingLombok\LombokSerde\SerdeError;
use CodingLombok\LombokSerde\TableEntry;
use CodingLombok\LombokSerde\Toml;
use CodingLombok\LombokSerde\U64;
use CodingLombok\LombokSerde\Value;

/** Expects $fn to throw a SerdeError with the given code. */
function expectSerdeError(callable $fn, string $code, string $what): void
{
    try {
        $fn();
    } catch (SerdeError $e) {
        if ($e->code() !== $code) {
            throw new RuntimeException("{$what}: wrong code {$e->code()}");
        }

        return;
    }
    throw new RuntimeException("{$what}: expected error {$code}");
}

// --- JSON syntax edges ---------------------------------------------------------

test('x_json_empty_and_literals', function (): void {
    expectSerdeError(fn () => Json::decode('', null), 'SERDE_JSON_SYNTAX', 'empty input');
    expectSerdeError(fn () => Json::decode('   ', null), 'SERDE_JSON_SYNTAX', 'blank input');
    foreach (['truX', 'fals', 'nul'] as $bad) {
        expectSerdeError(fn () => Json::decode($bad, null), 'SERDE_JSON_SYNTAX', "literal {$bad}");
    }
    // 'truex' parses as true and then trips the trailing-content rule
    expectSerdeError(fn () => Json::decode('truex', null), 'SERDE_JSON_TRAILING', 'true + trailing');
});

test('x_json_object_array_errors', function (): void {
    expectSerdeError(fn () => Json::decode('{"a" 1}', null), 'SERDE_JSON_SYNTAX', "expected ':'");
    expectSerdeError(fn () => Json::decode('{"a":1', null), 'SERDE_JSON_SYNTAX', 'unterminated object');
    expectSerdeError(fn () => Json::decode('[1,', null), 'SERDE_JSON_SYNTAX', 'unterminated array');
    expectSerdeError(fn () => Json::decode('[1 2]', null), 'SERDE_JSON_SYNTAX', "expected ',' or ']'");
});

test('x_json_string_errors', function (): void {
    expectSerdeError(fn () => Json::decode('"abc', null), 'SERDE_JSON_SYNTAX', 'unterminated string');
    expectSerdeError(fn () => Json::decode('"a\\', null), 'SERDE_JSON_SYNTAX', 'unterminated escape');
    expectSerdeError(fn () => Json::decode('"a\x01b"', null), 'SERDE_JSON_SYNTAX', 'raw control char');
    if (Json::decode('"\\/"', null)->str !== '/') {
        throw new RuntimeException('escaped slash');
    }
});

test('x_json_number_errors', function (): void {
    expectSerdeError(fn () => Json::decode('-', null), 'SERDE_JSON_SYNTAX', 'lone minus');
    expectSerdeError(fn () => Json::decode('x', null), 'SERDE_JSON_SYNTAX', 'not a number');
    expectSerdeError(fn () => Json::decode('[1.]', null), 'SERDE_JSON_SYNTAX', "digit after '.'");
    expectSerdeError(fn () => Json::decode('[1e]', null), 'SERDE_JSON_SYNTAX', 'digit in exponent');
    // a leading zero parses as 0 and then trips the trailing-content rule
    expectSerdeError(fn () => Json::decode('01', null), 'SERDE_JSON_TRAILING', 'leading zero');
});

// --- JSON UTF-8 over raw bytes ---------------------------------------------------

test('x_json_utf8_raw_valid', function (): void {
    $cases = [
        "\xC3\xA9",            // 2-byte
        "\xE0\xA0\x80",        // U+0800 (0xE0 requires cont >= 0xA0)
        "\xE1\x80\x80",        // E1..EC
        "\xED\x9F\xBF",        // U+D7FF (0xED requires cont <= 0x9F)
        "\xEE\x80\x80",        // U+E000
        "\xEF\xBF\xBD",        // U+FFFD
        "\xF0\x90\x80\x80",    // U+10000 (0xF0 requires cont >= 0x90)
        "\xF1\x80\x80\x80",    // F1..F3
        "\xF4\x8F\xBF\xBF",    // U+10FFFF (0xF4 requires cont <= 0x8F)
    ];
    foreach ($cases as $s) {
        if (Json::decode('"' . $s . '"', null)->str !== $s) {
            throw new RuntimeException('raw utf8 roundtrip failed');
        }
    }
});

test('x_json_utf8_raw_invalid', function (): void {
    $cases = [
        "\x80",                // bare continuation
        "\xC2",                // truncated 2-byte
        "\xE0\x9F\xBF",        // 0xE0 with continuation below 0xA0
        "\xED\xA0\x80",        // surrogate 0xED 0xA0..
        "\xF0\x8F\xBF\xBF",    // 0xF0 with continuation below 0x90
        "\xF4\x90\x80\x80",    // 0xF4 with continuation above 0x8F
        "\xE0\xA0",            // truncated 3-byte
    ];
    foreach ($cases as $s) {
        expectSerdeError(fn () => Json::decode('"' . $s . '"', null), 'SERDE_JSON_UTF8', 'invalid utf8');
    }
});

// --- Value / U64 edges -------------------------------------------------------------

test('x_value_edges', function (): void {
    try {
        Value::uint(-1);
        throw new RuntimeException('uint(-1) must throw');
    } catch (\LogicException $e) {
        // expected
    }
    if (Value::str('x')->tableGet('k') !== null) {
        throw new RuntimeException('tableGet on non-table');
    }
    $t = Json::decode('{"a":1,"b":2,"c":3}', null);
    if ($t->tableGet('c')->int !== 3) {
        throw new RuntimeException('binary search right half');
    }
    if ($t->tableGet('zz') !== null) {
        throw new RuntimeException('missing key');
    }
    if (Value::int(-5)->decimalText() !== '-5') {
        throw new RuntimeException('decimalText int');
    }
    if (Value::uint('42')->decimalText() !== '42') {
        throw new RuntimeException('decimalText uint');
    }
});

test('x_u64_i64_bytes', function (): void {
    if (U64::i64ToBytes8(5) !== "\x00\x00\x00\x00\x00\x00\x00\x05") {
        throw new RuntimeException('i64ToBytes8 positive');
    }
    if (U64::i64ToBytes8(-1) !== "\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF") {
        throw new RuntimeException('i64ToBytes8 -1');
    }
});

// --- MessagePack width carriers ------------------------------------------------

test('x_mp_uint_widths', function (): void {
    if (Msgpack::encode(Value::uint('5'), null) !== "\x05") {
        throw new RuntimeException('fixuint');
    }
    if (Msgpack::encode(Value::uint('200'), null) !== "\xCC\xC8") {
        throw new RuntimeException('uint8');
    }
    if (Msgpack::encode(Value::uint('700'), null) !== "\xCD\x02\xBC") {
        throw new RuntimeException('uint16');
    }
    if (Msgpack::encode(Value::uint('70000'), null) !== "\xCE\x00\x01\x11\x70") {
        throw new RuntimeException('uint32');
    }
    if (Msgpack::encode(Value::uint('5000000000'), null) !== "\xCF\x00\x00\x00\x01\x2A\x05\xF2\x00") {
        throw new RuntimeException('uint64');
    }
    if (Msgpack::encode(Value::uint('18446744073709551615'), null) !== "\xCF\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF") {
        throw new RuntimeException('u64 max');
    }
    // the signed-int writer has its own uint64 carrier branch
    if (Msgpack::encode(Value::int(5000000000), null) !== "\xCF\x00\x00\x00\x01\x2A\x05\xF2\x00") {
        throw new RuntimeException('int64 width');
    }
});

test('x_mp_str_bin_widths', function (): void {
    $s32 = str_repeat('a', 32);
    if (Msgpack::encode(Value::str($s32), null) !== "\xD9\x20" . $s32) {
        throw new RuntimeException('str8');
    }
    $sBig = str_repeat('b', 70000);
    $enc = Msgpack::encode(Value::str($sBig), null);
    if ($enc !== "\xDB\x00\x01\x11\x70" . $sBig) {
        throw new RuntimeException('str32');
    }
    $bBig = str_repeat("\x00", 70000);
    if (Msgpack::encode(Value::bytes($bBig), null) !== "\xC6\x00\x01\x11\x70" . $bBig) {
        throw new RuntimeException('bin32');
    }
});

test('x_mp_depth_encode_decode', function (): void {
    $v = Value::table([]);
    for ($j = 0; $j < 130; $j++) {
        $v = Value::table([new TableEntry('a', $v)]);
    }
    expectSerdeError(fn () => Msgpack::encode($v, null), 'SERDE_MP_DEPTH', 'encode depth');

    $payload = str_repeat("\x81", 130) . "\xA1a\x01";
    expectSerdeError(fn () => Msgpack::decode($payload, null), 'SERDE_MP_DEPTH', 'decode depth');
});

test('x_mp_decode_errors', function (): void {
    expectSerdeError(fn () => Msgpack::decode("\xC1", null), 'SERDE_MP_UNEXPECTED', 'invalid type code');
    // length fields below the minimum for their type (canonical-form rule:
    // the shorter families are the fix* codes)
    expectSerdeError(fn () => Msgpack::decode("\xD9\x00", null), 'SERDE_MP_UNEXPECTED', 'str8 short');
    expectSerdeError(fn () => Msgpack::decode("\xC4\x00", null), 'SERDE_MP_UNEXPECTED', 'bin8 short');
    expectSerdeError(fn () => Msgpack::decode("\xC7\x00\xFF", null), 'SERDE_MP_UNEXPECTED', 'ext8 short');
    expectSerdeError(fn () => Msgpack::decode("\xDC\x00\x01\x01", null), 'SERDE_MP_UNEXPECTED', 'array16 short');
    expectSerdeError(fn () => Msgpack::decode("\xDE\x00\x01\x80", null), 'SERDE_MP_UNEXPECTED', 'map16 short');
});

// --- MessagePack timestamp carriers ---------------------------------------------

test('x_mp_ts_payload_errors', function (): void {
    // ts64 with nanoseconds out of range (bits = ns * 2^34 + sec)
    expectSerdeError(
        fn () => Msgpack::decode("\xD7\xFF" . hex2bin('EE6B280000000000'), null),
        'SERDE_MP_UNEXPECTED',
        'ts64 ns out of range',
    );
    // ts96 with ns field out of range
    expectSerdeError(
        fn () => Msgpack::decode("\xC7\x0C\xFF" . pack('N', 1000000000) . U64::i64ToBytes8(0), null),
        'SERDE_MP_UNEXPECTED',
        'ts96 ns out of range',
    );
    // unsupported timestamp payload length
    expectSerdeError(
        fn () => Msgpack::decode("\xC7\x05\xFF\x00\x00\x00\x00\x00", null),
        'SERDE_MP_EXT',
        'ts length',
    );
});

test('x_mp_ts_calendar_edges', function (): void {
    // year 0 exercises the negative-era branch of the civil calendar math
    $raw = '0000-01-01T00:00:00Z';
    $v = Value::datetime('offset', $raw);
    $enc = Msgpack::encode($v, null);
    $back = Msgpack::decode($enc, null);
    if ($back->datetime->raw !== $raw) {
        throw new RuntimeException('year 0 roundtrip: ' . $back->datetime->raw);
    }
    // year 9999 with fractional seconds forces the ts96 carrier (sec > 2^34-1);
    // the fraction is re-rendered without trailing zeros
    $back2 = Msgpack::decode(
        Msgpack::encode(Value::datetime('offset', '9999-12-31T23:59:59.500000000Z'), null),
        null,
    );
    if ($back2->datetime->raw !== '9999-12-31T23:59:59.5Z') {
        throw new RuntimeException('year 9999 roundtrip: ' . $back2->datetime->raw);
    }
    // pre-epoch decoding through datetimeFromTimestamp
    $pre = Msgpack::decode("\xC7\x0C\xFF" . pack('N', 500000000) . U64::i64ToBytes8(-62135596800), null);
    if ($pre->kind !== Value::KIND_DATETIME || !str_starts_with($pre->datetime->raw, '0001-01-01')) {
        throw new RuntimeException('pre-epoch ts96: ' . $pre->datetime->raw);
    }
});

test('x_mp_datetime_raw_rejections', function (): void {
    $mk = fn (string $raw): \Closure => fn () => Msgpack::encode(Value::datetime('offset', $raw), null);
    expectSerdeError($mk('1979-05-27T00:00:0'), 'SERDE_MP_DATETIME', 'too short');
    expectSerdeError($mk('1979-05-27X00:00:00Z'), 'SERDE_MP_DATETIME', 'bad separator');
    expectSerdeError($mk('19x9-05-27T00:00:00Z'), 'SERDE_MP_DATETIME', 'non-digit year');
    expectSerdeError($mk('1979-05-27T23:59:60Z'), 'SERDE_MP_DATETIME', 'leap second');
    expectSerdeError($mk('1979-05-27T24:00:00Z'), 'SERDE_MP_DATETIME', 'hour 24');
    expectSerdeError($mk('1979-13-27T00:00:00Z'), 'SERDE_MP_DATETIME', 'month 13');
    expectSerdeError($mk('1979-05-27T00:00:00Zx'), 'SERDE_MP_DATETIME', 'trailing junk after Z');
    expectSerdeError($mk('1979-05-27T00:00:00+5:30'), 'SERDE_MP_DATETIME', 'short offset');
    expectSerdeError($mk('1979-05-27T00:00:00+99:00'), 'SERDE_MP_DATETIME', 'offset hour 99');
    expectSerdeError($mk('1979-05-27T00:00:00+00:60'), 'SERDE_MP_DATETIME', 'offset minute 60');
    // valid ±hh:mm offsets must parse; decoding re-renders in UTC
    $pairs = [
        ['1979-05-27T07:32:00+05:30', '1979-05-27T02:02:00Z'],
        ['1979-05-27T07:32:00-08:45', '1979-05-27T16:17:00Z'],
    ];
    foreach ($pairs as [$okRaw, $wantRaw]) {
        $back = Msgpack::decode(Msgpack::encode(Value::datetime('offset', $okRaw), null), null);
        if ($back->datetime->raw !== $wantRaw) {
            throw new RuntimeException("offset roundtrip: {$back->datetime->raw}");
        }
    }
});

// --- TOML encode edges ---------------------------------------------------------

test('x_toml_encode_escapes_and_scalars', function (): void {
    // TOML documents encode from a table root
    $doc = static fn (Value $v): Value => Value::table([new TableEntry('a', $v)]);
    if (Toml::encode($doc(Value::str("a\x08\x09\x0C\x0D")), null) !== 'a = "a\\b\\t\\f\\r"' . "\n") {
        throw new RuntimeException('b/t/f/r escapes');
    }
    if (Toml::encode($doc(Value::uint('42')), null) !== "a = 42\n") {
        throw new RuntimeException('uint scalar');
    }
    expectSerdeError(
        fn () => Toml::encode($doc(Value::uint('18446744073709551615')), null),
        'SERDE_TOML_SYNTAX',
        'uint beyond TOML signed range',
    );
    // note: tomlInline's empty-table branch is defensive; the document emitter
    // renders sub-tables and arrays-of-tables in header style instead
    expectSerdeError(fn () => Toml::encode($doc(Value::null()), null), 'SERDE_TOML_SYNTAX', 'null is unsupported');
});

test('x_toml_encode_depth', function (): void {
    $v = Value::table([]);
    for ($j = 0; $j < 130; $j++) {
        $v = Value::table([new TableEntry('a', $v)]);
    }
    expectSerdeError(fn () => Toml::encode($v, null), 'SERDE_TOML_DEPTH', 'encode depth');
});


test('x_toml_encode_datetime_kinds', function (): void {
    foreach ([
        ['date', '1979-05-27'],
        ['time', '07:32:00'],
        ['time', '07:32:00.999'],
        ['localdt', '1979-05-27T07:32:00'],
        ['offset', '1979-05-27T07:32:00+05:30'],
    ] as [$kind, $raw]) {
        $doc = Value::table([new TableEntry('a', Value::datetime($kind, $raw))]);
        if (Toml::encode($doc, null) !== 'a = ' . $raw . "\n") {
            throw new RuntimeException("datetime {$kind} passthrough");
        }
    }
});

test('x_toml_encode_datetime_invalid', function (): void {
    $cases = [
        ['date', '1979-5-27'],      // wrong length
        ['date', '197905-27'],      // missing dash
        ['date', '19x9-05-27'],     // non-digit segment
        ['date', '1979-13-01'],     // month 13
        ['date', '1979-05-00'],     // day 0
        ['time', '7:32:00'],        // too short
        ['time', '0732000'],        // missing colons
        ['time', '24:00:00'],       // hour 24
        ['time', '07:60:00'],       // minute 60
        ['time', '07:32:61'],       // second 61
        ['time', '07:32:00.'],      // dot without digits
        ['time', '07:32:00.x'],     // non-digit fraction
        ['localdt', '1979-05-27T07:32'],       // below minimum length
        ['localdt', '1979/05/27T07:32:00'],    // wrong separators
        ['localdt', '1979-05-27T07:32:00Z'],   // zone on a local datetime
        ['localdt', '1979-05-27T07:32:00.'],   // dot without digits
        ['offset', '1979-05-27T07:32:00'],     // missing zone
        ['offset', '1979-05-27T07:32:00Zx'],   // trailing junk
        ['offset', '1979-05-27T07:32:00+5:30'], // short offset
        ['offset', '1979-05-27T07:32:00+99:00'], // zone hour 99
        ['offset', '1979-05-27T07:32:00+00:60'], // zone minute 60
    ];
    foreach ($cases as [$kind, $raw]) {
        $doc = Value::table([new TableEntry('a', Value::datetime($kind, $raw))]);
        expectSerdeError(
            fn () => Toml::encode($doc, null),
            'SERDE_TOML_DATETIME',
            "datetime {$kind} {$raw}",
        );
    }
});

// --- TOML parse edges -------------------------------------------------------------

test('x_toml_header_and_key_errors', function (): void {
    expectSerdeError(fn () => Toml::decode('[a', null), 'SERDE_TOML_SYNTAX', "expected ']'");
    expectSerdeError(fn () => Toml::decode('[[a', null), 'SERDE_TOML_SYNTAX', "expected ']]'");
    expectSerdeError(fn () => Toml::decode("a = 1\n[", null), 'SERDE_TOML_SYNTAX', 'expected key');
    expectSerdeError(fn () => Toml::decode('a 1', null), 'SERDE_TOML_SYNTAX', "expected '='");
    expectSerdeError(fn () => Toml::decode('a =', null), 'SERDE_TOML_SYNTAX', 'expected value');
    expectSerdeError(fn () => Toml::decode('a = {b 1}', null), 'SERDE_TOML_SYNTAX', "inline expected '='");
});

test('x_toml_table_semantics', function (): void {
    // plain header defines an explicit table
    $v = Toml::decode("[a]\nb = 1", null);
    if ($v->tableGet('a')->tableGet('b')->int !== 1) {
        throw new RuntimeException('explicit header table');
    }
    // empty inline table
    $v2 = Toml::decode('a = {}', null);
    if ($v2->tableGet('a')->kind !== Value::KIND_TABLE || \count($v2->tableGet('a')->table) !== 0) {
        throw new RuntimeException('empty inline table parse');
    }
    // header inside an array-of-tables element (pseudo-segment resolution)
    $v3 = Toml::decode("[[a]]\n[a.b]\nx = 1", null);
    if ($v3->tableGet('a')->array[0]->tableGet('b')->tableGet('x')->int !== 1) {
        throw new RuntimeException('header inside aot element');
    }
    // dotted-key table redefined by a header
    expectSerdeError(fn () => Toml::decode("a.b = 1\n[a]", null), 'SERDE_TOML_DUPLICATE', 'dotted then header');
    // header then array-of-tables on the same key
    expectSerdeError(fn () => Toml::decode("[a]\n[[a]]", null), 'SERDE_TOML_DUPLICATE', 'table then aot');
    // duplicate key in the same table
    expectSerdeError(fn () => Toml::decode("a = 1\na = 2", null), 'SERDE_TOML_DUPLICATE', 'dup key');
});

test('x_toml_depth_limits', function (): void {
    $deep = '[[' . str_repeat('a.', 130) . 'a]]';
    expectSerdeError(fn () => Toml::decode($deep, null), 'SERDE_TOML_DEPTH', 'aot header depth');
});

test('x_toml_string_edges', function (): void {
    expectSerdeError(fn () => Toml::decode('a = "abc', null), 'SERDE_TOML_SYNTAX', 'unterminated basic');
    expectSerdeError(fn () => Toml::decode("a = \"a\x01b\"", null), 'SERDE_TOML_SYNTAX', 'raw control basic');
    expectSerdeError(fn () => Toml::decode('a = "x\\', null), 'SERDE_TOML_SYNTAX', 'unterminated escape');
    expectSerdeError(fn () => Toml::decode('a = "\q"', null), 'SERDE_TOML_SYNTAX', 'invalid escape');
    expectSerdeError(fn () => Toml::decode('a = "\ "', null), 'SERDE_TOML_SYNTAX', 'escaped space in basic');
    expectSerdeError(fn () => Toml::decode('a = "abc', null), 'SERDE_TOML_SYNTAX', 'unterminated ml basic');
    if (Toml::decode('a = "\b\t\f\r"', null)->tableGet('a')->str !== "\x08\t\x0C\x0D") {
        throw new RuntimeException('b/t/f/r unescape');
    }
    if (Toml::decode('a = "\u0041"', null)->tableGet('a')->str !== 'A') {
        throw new RuntimeException('uppercase hex escape');
    }
    expectSerdeError(fn () => Toml::decode('a = "\uXY12"', null), 'SERDE_TOML_SYNTAX', 'invalid unicode escape');
    expectSerdeError(fn () => Toml::decode('a = "\u00"', null), 'SERDE_TOML_SYNTAX', 'truncated u escape');
    expectSerdeError(fn () => Toml::decode('a = "\U0001F6"', null), 'SERDE_TOML_SYNTAX', 'truncated U escape');
    expectSerdeError(fn () => Toml::decode('a = "\U00110000"', null), 'SERDE_TOML_SYNTAX', 'scalar beyond unicode');
});

test('x_toml_ml_string_edges', function (): void {
    // line-ending backslash with spaces before the newline (basic multiline)
    if (Toml::decode("a = \"\"\"x\\ \n  y\"\"\"", null)->tableGet('a')->str !== 'xy') {
        throw new RuntimeException('ml line-ending backslash (space)');
    }
    // and with CRLF directly after the backslash
    if (Toml::decode("a = \"\"\"x\\\r\ny\"\"\"", null)->tableGet('a')->str !== 'xy') {
        throw new RuntimeException('ml line-ending backslash (crlf)');
    }
    // opening CRLF is trimmed after triple quotes
    if (Toml::decode("a = \"\"\"\r\nx\"\"\"", null)->tableGet('a')->str !== 'x') {
        throw new RuntimeException('ml basic crlf open');
    }
    if (Toml::decode("a = '''\r\nx'''", null)->tableGet('a')->str !== 'x') {
        throw new RuntimeException('ml literal crlf open');
    }
    // up to two extra quotes belong to the content
    if (Toml::decode('a = """x""""', null)->tableGet('a')->str !== 'x"') {
        throw new RuntimeException('ml extra quotes');
    }
    expectSerdeError(fn () => Toml::decode('a = """abc', null), 'SERDE_TOML_SYNTAX', 'unterminated ml basic');
    expectSerdeError(fn () => Toml::decode("a = \"\"\"a\x01b\"\"\"", null), 'SERDE_TOML_SYNTAX', 'raw control ml basic');
    expectSerdeError(fn () => Toml::decode("a = '''abc", null), 'SERDE_TOML_SYNTAX', 'unterminated ml literal');
    expectSerdeError(fn () => Toml::decode("a = '''a\x01b'''", null), 'SERDE_TOML_SYNTAX', 'raw control ml literal');
    expectSerdeError(fn () => Toml::decode("a = 'abc", null), 'SERDE_TOML_SYNTAX', 'unterminated literal');
    expectSerdeError(fn () => Toml::decode("a = 'a\x01b'", null), 'SERDE_TOML_SYNTAX', 'raw control literal');
});

test('x_toml_number_edges', function (): void {
    expectSerdeError(fn () => Toml::decode('a = 99999999999999999999', null), 'SERDE_TOML_SYNTAX', 'decimal overflow');
    expectSerdeError(fn () => Toml::decode('a = 0x10000000000000000', null), 'SERDE_TOML_SYNTAX', 'hex overflow');
    expectSerdeError(fn () => Toml::decode('a = 9223372036854775808', null), 'SERDE_TOML_SYNTAX', 'beyond i64 max');
    expectSerdeError(fn () => Toml::decode('a = -9223372036854775809', null), 'SERDE_TOML_SYNTAX', 'beyond i64 min');
    expectSerdeError(fn () => Toml::decode('a = 1e', null), 'SERDE_TOML_SYNTAX', 'exponent missing digit');
    expectSerdeError(fn () => Toml::decode('a = _1', null), 'SERDE_TOML_SYNTAX', 'leading underscore');
    expectSerdeError(fn () => Toml::decode('a = 1_', null), 'SERDE_TOML_SYNTAX', 'trailing underscore');
    expectSerdeError(fn () => Toml::decode('a = 1__2', null), 'SERDE_TOML_SYNTAX', 'double underscore');
    if (Toml::decode('a = -42', null)->tableGet('a')->int !== -42) {
        throw new RuntimeException('negative int');
    }
    if (Toml::decode('a = -9223372036854775808', null)->tableGet('a')->int !== \PHP_INT_MIN) {
        throw new RuntimeException('i64 min literal');
    }
    if (Toml::decode('a = 1_2', null)->tableGet('a')->int !== 12) {
        throw new RuntimeException('digit separators');
    }
});

test('x_toml_datetime_shapes', function (): void {
    foreach ([
        '1979-05-27',               // local date
        '07:32:00',                 // local time
        '07:32:00.999',             // local time with fraction
        '1979-05-27T07:32:00',      // local datetime
        '1979-05-27 07:32:00',      // space separator
        '1979-05-27T07:32:00.123456789Z',
        '1979-05-27T07:32:00.999+05:30',
        '1979-05-27T07:32:00-08:45',
    ] as $raw) {
        $v = Toml::decode('a = ' . $raw, null)->tableGet('a');
        if ($v->kind !== Value::KIND_DATETIME || $v->datetime->raw !== $raw) {
            throw new RuntimeException("datetime shape {$raw}");
        }
    }
    expectSerdeError(fn () => Toml::decode('a = 1979-05-27T07:32:00.', null), 'SERDE_TOML_SYNTAX', 'dangling frac dot');
    expectSerdeError(fn () => Toml::decode('a = 1979-05-27Z', null), 'SERDE_TOML_SYNTAX', 'date with zone');
    expectSerdeError(fn () => Toml::decode('a = 1979-05-27T24:00:00Z', null), 'SERDE_TOML_SYNTAX', 'hour 24');
    expectSerdeError(fn () => Toml::decode('a = 1979-13-01T00:00:00Z', null), 'SERDE_TOML_SYNTAX', 'month 13');
    // a leap second passes the TOML shape check; conversion to a MessagePack
    // timestamp is what rejects it (covered in x_mp_datetime_raw_rejections)
    $leap = Toml::decode('a = 1979-05-27T07:32:60Z', null)->tableGet('a');
    if ($leap->datetime->raw !== '1979-05-27T07:32:60Z') {
        throw new RuntimeException('leap second passthrough');
    }
});

test('x_toml_comments_and_crlf', function (): void {
    // comment at EOF without a trailing newline
    $v = Toml::decode("a = 1\n# trailing comment", null);
    if ($v->tableGet('a')->int !== 1) {
        throw new RuntimeException('comment at EOF');
    }
    // CRLF line endings, bare and after a comment
    $v2 = Toml::decode("a = 1\r\nb = 2\r\n", null);
    if ($v2->tableGet('b')->int !== 2) {
        throw new RuntimeException('crlf lines');
    }
    $v3 = Toml::decode("a = 1 # c\r\nb = 2\r\n", null);
    if ($v3->tableGet('b')->int !== 2) {
        throw new RuntimeException('comment + crlf');
    }
});

test('x_toml_quoted_key_edges', function (): void {
    // keys containing quotes and backslashes survive the tree round trip
    $v = Toml::decode('["a\"b"]' . "\nx = 1", null);
    if ($v->tableGet('a"b')->tableGet('x')->int !== 1) {
        throw new RuntimeException('quoted key with quote');
    }
    $v2 = Toml::decode('"a\\\\b" = 1', null);
    if ($v2->tableGet('a\\b')->int !== 1) {
        throw new RuntimeException('quoted key with backslash');
    }
});

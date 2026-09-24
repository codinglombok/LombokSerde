<?php

declare(strict_types=1);

require_once __DIR__ . '/../vendor/autoload.php';

use LombokSerde\Json\JsonParser;
use LombokSerde\Json\JsonSerializer;
use LombokSerde\Toml\TomlParser;
use LombokSerde\Toml\TomlSerializer;
use LombokSerde\Msgpack\MsgpackEncoder;
use LombokSerde\Msgpack\MsgpackDecoder;

$pass = 0;
$fail = 0;

function assert_eq(mixed $a, mixed $b, string $name): void {
    global $pass, $fail;
    if ($a === $b) {
        $pass++;
    } else {
        $fail++;
        echo "FAIL: {$name}\n";
        echo "  expected: " . var_export($b, true) . "\n";
        echo "  got:      " . var_export($a, true) . "\n";
    }
}

// --- JSON ---
assert_eq(JsonParser::parse('null'), null, 'json null');
assert_eq(JsonParser::parse('true'), true, 'json true');
assert_eq(JsonParser::parse('false'), false, 'json false');
assert_eq(JsonParser::parse('42'), 42, 'json integer');
assert_eq(JsonParser::parse('-17'), -17, 'json negative');
assert_eq(JsonParser::parse('3.14'), 3.14, 'json float');
assert_eq(JsonParser::parse('"hello"'), 'hello', 'json string');
assert_eq(JsonParser::parse('"a\\nb"'), "a\nb", 'json escape');
assert_eq(JsonParser::parse('[]'), [], 'json empty array');
assert_eq(JsonParser::parse('[1, 2, 3]'), [1, 2, 3], 'json array');
assert_eq(JsonParser::parse('{}'), [], 'json empty object');

$obj = JsonParser::parse('{"a": 1, "b": "hello"}');
assert_eq($obj['a'], 1, 'json object a');
assert_eq($obj['b'], 'hello', 'json object b');

// JSON serialize
assert_eq(JsonSerializer::toString(null), 'null', 'json ser null');
assert_eq(JsonSerializer::toString(true), 'true', 'json ser true');
assert_eq(JsonSerializer::toString(42), '42', 'json ser int');
assert_eq(JsonSerializer::toString('hello'), '"hello"', 'json ser string');
assert_eq(JsonSerializer::toString([1, 2, 3]), '[1,2,3]', 'json ser array');

// JSON roundtrip
$input = '{"name":"test","values":[1,2,3]}';
$parsed = JsonParser::parse($input);
$serialized = JsonSerializer::toString($parsed);
$reparsed = JsonParser::parse($serialized);
assert_eq($reparsed['name'], 'test', 'json roundtrip name');
assert_eq($reparsed['values'], [1, 2, 3], 'json roundtrip values');

// --- TOML ---
$toml = TomlParser::parse("title = \"Test\"\ncount = 42\n");
assert_eq($toml['title'], 'Test', 'toml string');
assert_eq($toml['count'], 42, 'toml integer');

$toml = TomlParser::parse("[server]\nhost = \"localhost\"\nport = 8080\n");
assert_eq($toml['server']['host'], 'localhost', 'toml table host');
assert_eq($toml['server']['port'], 8080, 'toml table port');

$toml = TomlParser::parse("flag = true\n");
assert_eq($toml['flag'], true, 'toml bool');

// TOML serialize
$ser = TomlSerializer::stringify(['title' => 'Test', 'count' => 42]);
assert_eq(str_contains($ser, 'title = "Test"'), true, 'toml ser title');
assert_eq(str_contains($ser, 'count = 42'), true, 'toml ser count');

// --- MessagePack ---
// Null roundtrip
assert_eq(MsgpackDecoder::decode(MsgpackEncoder::encode(null)), null, 'msgpack null');
assert_eq(MsgpackDecoder::decode(MsgpackEncoder::encode(true)), true, 'msgpack true');
assert_eq(MsgpackDecoder::decode(MsgpackEncoder::encode(false)), false, 'msgpack false');
assert_eq(MsgpackDecoder::decode(MsgpackEncoder::encode(0)), 0, 'msgpack 0');
assert_eq(MsgpackDecoder::decode(MsgpackEncoder::encode(42)), 42, 'msgpack 42');
assert_eq(MsgpackDecoder::decode(MsgpackEncoder::encode(-1)), -1, 'msgpack -1');
assert_eq(MsgpackDecoder::decode(MsgpackEncoder::encode(200)), 200, 'msgpack 200');
assert_eq(MsgpackDecoder::decode(MsgpackEncoder::encode(1000)), 1000, 'msgpack 1000');
assert_eq(MsgpackDecoder::decode(MsgpackEncoder::encode('hello')), 'hello', 'msgpack string');
assert_eq(MsgpackDecoder::decode(MsgpackEncoder::encode('')), '', 'msgpack empty string');
assert_eq(MsgpackDecoder::decode(MsgpackEncoder::encode([1, 2, 3])), [1, 2, 3], 'msgpack array');
assert_eq(MsgpackDecoder::decode(MsgpackEncoder::encode([])), [], 'msgpack empty array');

$map = ['a' => 1, 'b' => 'hello'];
$decoded = MsgpackDecoder::decode(MsgpackEncoder::encode($map));
assert_eq($decoded['a'], 1, 'msgpack map a');
assert_eq($decoded['b'], 'hello', 'msgpack map b');

echo "\n{$pass} passed, {$fail} failed\n";
exit($fail > 0 ? 1 : 0);

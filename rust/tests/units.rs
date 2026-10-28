//! Unit tests covering encoder/validator branches beyond the shared
//! vectors (S4: >= 95% statements, >= 90% branches), plus a deterministic
//! mutation property test mirroring typescript/tests/fuzz.test.ts.

use lombokserde::*;

fn enc(s: &str) -> Vec<u8> {
    s.as_bytes().to_vec()
}

fn dec(b: Vec<u8>) -> String {
    String::from_utf8(b).unwrap()
}

fn table(pairs: Vec<(&str, Value)>) -> Value {
    Value::table(pairs.into_iter().map(|(k, v)| (k.to_string(), v)).collect())
}

fn f(x: f64) -> Value {
    Value::Float(x)
}
fn i(x: i64) -> Value {
    Value::Int(x)
}
fn s(x: &str) -> Value {
    Value::Str(x.to_string())
}

#[test]
fn float_presentation_all_regimes() {
    assert_eq!(dec(json_encode(&f(0.0), &JsonOptions::default()).unwrap()), "0.0");
    assert_eq!(dec(json_encode(&f(-0.0), &JsonOptions::default()).unwrap()), "-0.0");
    assert_eq!(dec(json_encode(&f(1.0), &JsonOptions::default()).unwrap()), "1.0");
    assert_eq!(dec(json_encode(&f(-1.5), &JsonOptions::default()).unwrap()), "-1.5");
    assert_eq!(dec(json_encode(&f(0.001), &JsonOptions::default()).unwrap()), "0.001");
    assert_eq!(dec(json_encode(&f(1e-6), &JsonOptions::default()).unwrap()), "0.000001");
    assert_eq!(dec(json_encode(&f(1e-7), &JsonOptions::default()).unwrap()), "1e-7");
    assert_eq!(dec(json_encode(&f(2.5e-10), &JsonOptions::default()).unwrap()), "2.5e-10");
    assert_eq!(
        dec(json_encode(&f(1e20), &JsonOptions::default()).unwrap()),
        "100000000000000000000.0"
    );
    assert_eq!(dec(json_encode(&f(1e21), &JsonOptions::default()).unwrap()), "1e+21");
    assert_eq!(dec(json_encode(&f(-1.5e300), &JsonOptions::default()).unwrap()), "-1.5e+300");
    assert_eq!(dec(json_encode(&f(5e-324), &JsonOptions::default()).unwrap()), "5e-324");
    assert_eq!(dec(json_encode(&f(123.456), &JsonOptions::default()).unwrap()), "123.456");
    assert_eq!(
        dec(json_encode(&f(12.5), &JsonOptions::default()).unwrap()),
        "12.5"
    );
}

#[test]
fn json_extras() {
    // slash escape
    let v = json_decode(&enc("\"a\\/b\""), &JsonOptions::default()).unwrap();
    assert_eq!(v, s("a/b"));
    // invalid low surrogate after a valid high escape
    let e = json_decode(&enc("\"\\ud83d\\u0041\""), &JsonOptions::default()).unwrap_err();
    assert_eq!(e.code, "SERDE_JSON_SYNTAX");
    assert_eq!(e.offset, Some(13));
    // missing exponent digit
    assert!(json_decode(&enc("1e+"), &JsonOptions::default()).is_err());
    assert!(json_decode(&enc("1ex"), &JsonOptions::default()).is_err());
    // encode depth on tables
    let deep = table(vec![
        ("a", table(vec![("b", table(vec![("c", i(1))]))])),
    ]);
    let e = json_encode(&deep, &JsonOptions { depth_limit: 2 }).unwrap_err();
    assert_eq!(e.code, "SERDE_JSON_DEPTH");
    assert!(e.offset.is_none());
    // raw control character
    assert!(json_decode(&enc("\"a\tb\""), &JsonOptions::default()).is_err());
    // partial literal
    assert!(json_decode(&enc("nul"), &JsonOptions::default()).is_err());
}

#[test]
fn msgpack_size_families() {
    let rt = |v: Value| msgpack_decode(&msgpack_encode(&v, &MsgPackOptions::default()).unwrap(), &MsgPackOptions::default()).unwrap();
    assert_eq!(rt(Value::UInt(255)), i(255));
    assert_eq!(rt(Value::UInt(65535)), i(65535));
    assert_eq!(rt(Value::UInt(4294967295)), i(4294967295));
    assert_eq!(rt(Value::UInt(u64::MAX)), Value::UInt(u64::MAX));
    assert_eq!(rt(i(9223372036854775807)), i(9223372036854775807));
    assert_eq!(rt(i(-9223372036854775808)), i(-9223372036854775808));
    let long = s(&"x".repeat(100));
    assert_eq!(rt(long.clone()), long);
    let long = s(&"x".repeat(300));
    assert_eq!(rt(long.clone()), long);
    let long = s(&"x".repeat(65537));
    assert_eq!(rt(long.clone()), long);
    let b = Value::Bytes(vec![7u8; 255]);
    assert_eq!(rt(b.clone()), b);
    let b = Value::Bytes(vec![7u8; 300]);
    assert_eq!(rt(b.clone()), b);
    let b = Value::Bytes(vec![7u8; 65537]);
    assert_eq!(rt(b.clone()), b);
    let a = Value::Array(vec![Value::Null; 65537]);
    assert_eq!(rt(a.clone()), a);
    let m = Value::table(
        (0..65537)
            .map(|j| (format!("k{j}"), i(j as i64)))
            .collect(),
    );
    assert_eq!(rt(m.clone()), m);
}

#[test]
fn msgpack_depth_and_timestamps() {
    // 130 nested arrays + payload
    let mut with_payload = vec![0x91u8; 130];
    with_payload[129] = 0x01;
    let e = msgpack_decode(&with_payload, &MsgPackOptions { depth_limit: 128 }).unwrap_err();
    assert_eq!(e.code, "SERDE_MP_DEPTH");
    assert!(msgpack_decode(&with_payload, &MsgPackOptions { depth_limit: 129 }).is_ok());
    // out-of-range nanoseconds (ns = 1e9)
    let mut bad64 = vec![0xd7u8, 0xff, 0, 0, 0, 0, 0, 0, 0, 0];
    let bits = (1_000_000_000u64) << 34;
    bad64[2..10].copy_from_slice(&bits.to_be_bytes());
    let e = msgpack_decode(&bad64, &MsgPackOptions::default()).unwrap_err();
    assert_eq!(e.code, "SERDE_MP_UNEXPECTED");
    let bad96 = {
        let mut v = vec![0xc7u8, 12, 0xff];
        v.extend_from_slice(&1_000_000_000u32.to_be_bytes());
        v.extend_from_slice(&0i64.to_be_bytes());
        v
    };
    let e = msgpack_decode(&bad96, &MsgPackOptions::default()).unwrap_err();
    assert_eq!(e.code, "SERDE_MP_UNEXPECTED");
    // ext8 carrier with a valid ts32 payload
    let ts = msgpack_decode(
        &[0xc7, 4, 0xff, 1, 2, 3, 4],
        &MsgPackOptions::default(),
    )
    .unwrap();
    let direct = msgpack_decode(&[0xd6, 0xff, 1, 2, 3, 4], &MsgPackOptions::default()).unwrap();
    assert_eq!(ts, direct);
    // calendar roundtrips
    assert_eq!(lombokserde::__private::days_from_civil(1979, 5, 27), 3433);
    assert_eq!(
        lombokserde::__private::civil_from_days(3433),
        (1979, 5, 27)
    );
}

#[test]
fn toml_datetime_matrix() {
    use lombokserde::__private::datetime_ok as ok;
    use lombokserde::DatetimeKind as K;
    assert!(ok("1979-05-27", K::LocalDate));
    assert!(!ok("1979-13-27", K::LocalDate));
    assert!(ok("07:32:60", K::LocalTime));
    assert!(!ok("24:00:00", K::LocalTime));
    assert!(!ok("07:32:00.", K::LocalTime));
    assert!(ok("1979-05-27T07:32:00", K::LocalDateTime));
    assert!(!ok("1979-05-27T07:32:00Z", K::LocalDateTime));
    assert!(ok("1979-05-27T07:32:00Z", K::Offset));
    assert!(ok("1979-05-27t07:32:00.25-03:30", K::Offset));
    assert!(!ok("1979-05-27T07:32:00+24:00", K::Offset));
    assert!(!ok("1979-05-27T07:32:00+07", K::Offset));
    assert!(!ok("1979-05-27T07:32", K::Offset));
}

#[test]
fn toml_redefinition_matrix() {
    // implicit promotion: [a.b] then [a]
    let d = toml_decode(&enc("[a.b]\nx = 1\n[a]\ny = 2\n"), &TomlOptions::default()).unwrap();
    assert!(d.get("a").unwrap().get("y").is_some());
    // [[a]] after [a]
    assert!(toml_decode(&enc("[a]\n[[a]]\n"), &TomlOptions::default()).is_err());
    // dotted then [[a]]
    assert!(toml_decode(&enc("a.b = 1\n[[a]]\n"), &TomlOptions::default()).is_err());
    // dotted keys into AoT elements (v1 restriction)
    let e = toml_decode(&enc("[[a]]\nx.y = 1\n"), &TomlOptions::default()).unwrap_err();
    assert_eq!(e.code, "SERDE_TOML_SYNTAX");
    // keyvals directly under [[a]]
    let d = toml_decode(&enc("[[a]]\nx = 1\ny = 2\n"), &TomlOptions::default()).unwrap();
    let arr = d.get("a").unwrap();
    match arr {
        Value::Array(items) => assert_eq!(items.len(), 1),
        _ => panic!("expected array"),
    }
    // table under AoT element
    let d = toml_decode(&enc("[[a]]\nx = 1\n[a.b]\ny = 2\n"), &TomlOptions::default()).unwrap();
    match d.get("a").unwrap() {
        Value::Array(items) => {
            assert!(items[0].get("b").is_some());
        }
        _ => panic!("expected array"),
    }
    // reserved hash keys
    let e = toml_decode(&enc("[\"#x\"]\ny = 1\n"), &TomlOptions::default()).unwrap_err();
    assert_eq!(e.code, "SERDE_TOML_SYNTAX");
    // value/table collision
    assert!(toml_decode(&enc("a = 1\n[a]\nb = 2\n"), &TomlOptions::default()).is_err());
}

#[test]
fn toml_escape_and_number_battery() {
    let d = toml_decode(
        &enc("a = \"\\b\\t\\n\\f\\r\\\"\\\\é\"\n"),
        &TomlOptions::default(),
    )
    .unwrap();
    assert_eq!(d.get("a").unwrap(), &s("\u{0008}\t\n\u{000C}\r\"\\é"));
    assert!(toml_decode(&enc("a = \"\\uZZZZ\""), &TomlOptions::default()).is_err());
    assert!(toml_decode(&enc("a = \"\\U0011FFFF\""), &TomlOptions::default()).is_err());
    assert!(toml_decode(&enc("a = 'x"), &TomlOptions::default()).is_err());
    assert!(toml_decode(&enc("a = \"\"\"x"), &TomlOptions::default()).is_err());
    let d = toml_decode(&enc("a = \"\"\"\"\"\"\"\"\n"), &TomlOptions::default()).unwrap();
    assert_eq!(d.get("a").unwrap(), &s("\"\""));
    // line-ending backslash
    let d = toml_decode(&enc("a = \"\"\"x\\\n    y\"\"\"\n"), &TomlOptions::default()).unwrap();
    assert_eq!(d.get("a").unwrap(), &s("xy"));
    // numbers
    assert!(toml_decode(&enc("a = 1e_"), &TomlOptions::default()).is_err());
    assert!(toml_decode(&enc("a = 1e"), &TomlOptions::default()).is_err());
    assert!(toml_decode(&enc("a = 0x"), &TomlOptions::default()).is_err());
    assert!(toml_decode(&enc("a = +0x10"), &TomlOptions::default()).is_err());
    assert!(toml_decode(&enc("a = -0b11"), &TomlOptions::default()).is_err());
    assert!(toml_decode(&enc("a = 007"), &TomlOptions::default()).is_err());
    assert!(toml_decode(&enc("a = 1_"), &TomlOptions::default()).is_err());
    let d = toml_decode(&enc("a = +inf\nb = -nan\n"), &TomlOptions::default()).unwrap();
    match d.get("a").unwrap() {
        Value::Float(x) => assert!(x.is_infinite() && *x > 0.0),
        _ => panic!("expected float"),
    }
    // encoder float forms + key quoting
    let doc = table(vec![
        ("k\"", i(1)),
        ("a.b", i(2)),
        ("", i(3)),
        ("fin", f(f64::INFINITY)),
        ("ninf", f(f64::NEG_INFINITY)),
        ("nan", f(f64::NAN)),
    ]);
    let out = dec(toml_encode(&doc, &TomlOptions::default()).unwrap());
    assert!(out.contains("\"k\\\"\" = 1"));
    assert!(out.contains("\"a.b\" = 2"));
    assert!(out.contains("\"\" = 3"));
    assert!(out.contains("fin = inf"));
    assert!(out.contains("ninf = -inf"));
    assert!(out.contains("nan = nan"));
    // bytes at root and nested
    assert!(toml_encode(&Value::Bytes(vec![1]), &TomlOptions::default()).is_err());
    let e = toml_encode(&table(vec![("b", Value::Bytes(vec![1]))]), &TomlOptions::default()).unwrap_err();
    assert_eq!(e.code, "SERDE_TOML_BYTES");
    // null is not a TOML value
    let e = toml_encode(&table(vec![("n", Value::Null)]), &TomlOptions::default()).unwrap_err();
    assert_eq!(e.code, "SERDE_TOML_SYNTAX");
    // uint overflow for TOML
    let e = toml_encode(&table(vec![("u", Value::UInt(u64::MAX))]), &TomlOptions::default()).unwrap_err();
    assert_eq!(e.code, "SERDE_TOML_SYNTAX");
    // bad datetime raw
    let e = toml_encode(
        &table(vec![("d", Value::Datetime(Datetime::new(DatetimeKind::Offset, "nope")))]),
        &TomlOptions::default(),
    )
    .unwrap_err();
    assert_eq!(e.code, "SERDE_TOML_DATETIME");
    // datetime raw roundtrips verbatim
    let doc = table(vec![(
        "d",
        Value::Datetime(Datetime::new(DatetimeKind::LocalDateTime, "1979-05-27t07:32:00")),
    )]);
    let out = dec(toml_encode(&doc, &TomlOptions::default()).unwrap());
    assert!(out.contains("d = 1979-05-27t07:32:00"));
}

// ---------------------------------------------------------------------------
// Deterministic mutation property (mirrors typescript/tests/fuzz.test.ts)
// ---------------------------------------------------------------------------

struct XorShift(u32);
impl XorShift {
    fn next(&mut self) -> u32 {
        let mut x = self.0;
        x ^= x << 13;
        x ^= x >> 17;
        x ^= x << 5;
        self.0 = x;
        x
    }
}

fn assert_serde_err(e: SerdeError) {
    assert!(e.code.starts_with("SERDE_"), "unexpected code {}", e.code);
}

#[test]
fn decoder_mutation_property() {
    let samples: Vec<(&str, Vec<u8>)> = vec![
        (
            "json",
            json_encode(
                &table(vec![
                    ("a", Value::Array(vec![i(1), f(2.5), s("x"), Value::Bool(true), Value::Null])),
                    ("é", f(-0.5)),
                ]),
                &JsonOptions::default(),
            )
            .unwrap(),
        ),
        (
            "toml",
            enc("a = [1, 2.5, \"x\", true]\n[b]\nc = 1979-05-27T07:32:00Z\nd = 0x2A\n"),
        ),
        (
            "msgpack",
            msgpack_encode(
                &table(vec![
                    ("a", Value::Array(vec![i(1), f(2.5), s("x")])),
                    (
                        "b",
                        Value::Datetime(Datetime::new(DatetimeKind::Offset, "2024-01-01T00:00:00Z")),
                    ),
                ]),
                &MsgPackOptions::default(),
            )
            .unwrap(),
        ),
    ];
    for (format, bytes) in &samples {
        // truncations
        for cut in 0..bytes.len() {
            let r = match *format {
                "json" => json_decode(&bytes[..cut], &JsonOptions::default()),
                "toml" => toml_decode(&bytes[..cut], &TomlOptions::default()),
                _ => msgpack_decode(&bytes[..cut], &MsgPackOptions::default()),
            };
            if let Err(e) = r {
                assert_serde_err(e);
            }
        }
        // byte flips
        let mut rng = XorShift(0x5eed ^ bytes.len() as u32);
        for iter in 0..1200 {
            let mut m = bytes.clone();
            let pos = (rng.next() as usize) % m.len();
            m[pos] ^= (1 + (rng.next() % 255)) as u8;
            let r = match *format {
                "json" => json_decode(&m, &JsonOptions::default()),
                "toml" => toml_decode(&m, &TomlOptions::default()),
                _ => msgpack_decode(&m, &MsgPackOptions::default()),
            };
            if let Err(e) = r {
                assert_serde_err(e);
            }
        }
        // garbage
        let mut rng = XorShift(0xbeef ^ bytes.len() as u32);
        for _ in 0..1500 {
            let len = 1 + (rng.next() as usize) % 24;
            let g: Vec<u8> = (0..len).map(|_| (rng.next() & 0xff) as u8).collect();
            let r = match *format {
                "json" => json_decode(&g, &JsonOptions::default()),
                "toml" => toml_decode(&g, &TomlOptions::default()),
                _ => msgpack_decode(&g, &MsgPackOptions::default()),
            };
            if let Err(e) = r {
                assert_serde_err(e);
            }
        }
    }
}

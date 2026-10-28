//! Shared vector runner: every case in vectors/lombokserde-vectors-v1.json
//! must pass bit-identically. The vector file itself is parsed with this
//! crate's own JSON decoder (dogfooding; the crate has zero dependencies).

use lombokserde::*;

const VECTORS_PATH: &str = concat!(
    env!("CARGO_MANIFEST_DIR"),
    "/../vectors/lombokserde-vectors-v1.json"
);

fn load_vectors() -> Value {
    let raw = std::fs::read(VECTORS_PATH).expect("vector file readable");
    json_decode(&raw, &JsonOptions::default()).expect("vector file is valid JSON")
}

/// Compare values with bit-identical float semantics (NaN == NaN, -0 != 0).
fn value_eq(a: &Value, b: &Value) -> bool {
    match (a, b) {
        (Value::Null, Value::Null) => true,
        (Value::Bool(x), Value::Bool(y)) => x == y,
        (Value::Int(x), Value::Int(y)) => x == y,
        (Value::UInt(x), Value::UInt(y)) => x == y,
        (Value::Float(x), Value::Float(y)) => x.to_bits() == y.to_bits(),
        (Value::Str(x), Value::Str(y)) => x == y,
        (Value::Bytes(x), Value::Bytes(y)) => x == y,
        (Value::Datetime(x), Value::Datetime(y)) => x == y,
        (Value::Array(x), Value::Array(y)) => {
            x.len() == y.len() && x.iter().zip(y.iter()).all(|(a, b)| value_eq(a, b))
        }
        (Value::Table(x), Value::Table(y)) => {
            x.len() == y.len()
                && x.iter()
                    .zip(y.iter())
                    .all(|((ka, va), (kb, vb))| ka == kb && value_eq(va, vb))
        }
        _ => false,
    }
}

/// Parse the VVE (vector value encoding) from a parsed vector JSON value.
fn vve_parse(v: &Value) -> Result<Value, String> {
    match v {
        Value::Null => Ok(Value::Null),
        Value::Bool(b) => Ok(Value::Bool(*b)),
        Value::Str(s) => Ok(Value::Str(s.clone())),
        Value::Array(items) => {
            let mut out = Vec::with_capacity(items.len());
            for x in items {
                out.push(vve_parse(x)?);
            }
            Ok(Value::Array(out))
        }
        Value::Table(pairs) => {
            if pairs.len() != 1 {
                return Err(format!(
                    "VVE object must have exactly one key, got {}",
                    pairs.len()
                ));
            }
            let (tag, payload) = &pairs[0];
            match tag.as_str() {
                "$i" => match payload {
                    Value::Str(s) => s
                        .parse::<i64>()
                        .map(Value::Int)
                        .map_err(|_| format!("bad int {s}")),
                    _ => Err("$i payload must be a string".to_string()),
                },
                "$u" => match payload {
                    Value::Str(s) => s
                        .parse::<u64>()
                        .map(Value::UInt)
                        .map_err(|_| format!("bad uint {s}")),
                    _ => Err("$u payload must be a string".to_string()),
                },
                "$f" => match payload {
                    Value::Str(s) => match s.as_str() {
                        "inf" => Ok(Value::Float(f64::INFINITY)),
                        "-inf" => Ok(Value::Float(f64::NEG_INFINITY)),
                        "nan" => Ok(Value::Float(f64::NAN)),
                        dec => dec
                            .parse::<f64>()
                            .map(Value::Float)
                            .map_err(|_| format!("bad float {dec}")),
                    },
                    _ => Err("$f payload must be a string".to_string()),
                },
                "$b" => match payload {
                    Value::Str(s) => hex_decode(s).map(Value::Bytes),
                    _ => Err("$b payload must be a string".to_string()),
                },
                "$d" => match payload {
                    Value::Array(items) if items.len() == 2 => {
                        let kind = match &items[0] {
                            Value::Str(s) => match s.as_str() {
                                "offset" => DatetimeKind::Offset,
                                "localdt" => DatetimeKind::LocalDateTime,
                                "date" => DatetimeKind::LocalDate,
                                "time" => DatetimeKind::LocalTime,
                                other => return Err(format!("bad datetime kind {other}")),
                            },
                            _ => return Err("datetime kind must be a string".to_string()),
                        };
                        let raw = match &items[1] {
                            Value::Str(s) => s.clone(),
                            _ => return Err("datetime raw must be a string".to_string()),
                        };
                        Ok(Value::Datetime(Datetime::new(kind, raw)))
                    }
                    _ => Err("$d payload must be [kind, raw]".to_string()),
                },
                "$t" => match payload {
                    Value::Array(entries) => {
                        let mut ps: Vec<(String, Value)> = Vec::with_capacity(entries.len());
                        for e in entries {
                            match e {
                                Value::Array(kv) if kv.len() == 2 => {
                                    let k = match &kv[0] {
                                        Value::Str(s) => s.clone(),
                                        _ => return Err("table key must be a string".to_string()),
                                    };
                                    ps.push((k, vve_parse(&kv[1])?));
                                }
                                _ => {
                                    return Err(
                                        "table entries must be [key, value] pairs".to_string()
                                    )
                                }
                            }
                        }
                        Ok(Value::table(ps))
                    }
                    _ => Err("$t payload must be an array of pairs".to_string()),
                },
                other => Err(format!("unknown VVE tag {other}")),
            }
        }
        other => Err(format!("unexpected VVE node {other:?}")),
    }
}

fn hex_decode(s: &str) -> Result<Vec<u8>, String> {
    if s.len() % 2 != 0 {
        return Err("odd-length hex".to_string());
    }
    (0..s.len())
        .step_by(2)
        .map(|i| u8::from_str_radix(&s[i..i + 2], 16).map_err(|e| e.to_string()))
        .collect()
}

fn hex_encode(b: &[u8]) -> String {
    let mut s = String::with_capacity(b.len() * 2);
    for byte in b {
        s.push_str(&format!("{:02x}", byte));
    }
    s
}

enum Outcome {
    Ok(Value, Value),
}

fn vector_input_bytes(case: &Value) -> Result<Vec<u8>, String> {
    match case.get("input") {
        Some(Value::Str(s)) => Ok(s.clone().into_bytes()),
        _ => match case.get("input_hex") {
            Some(Value::Str(h)) => hex_decode(h).map_err(|e| format!("bad hex: {e}")),
            _ => Err("case has neither input nor input_hex".to_string()),
        },
    }
}

fn check_case(case: &Value) -> Result<(), String> {
    let get = |k: &str| -> Result<Value, String> {
        case.get(k)
            .cloned()
            .ok_or_else(|| format!("missing key {k}"))
    };
    let id = match get("id")? {
        Value::Str(s) => s,
        _ => return Err("id must be a string".to_string()),
    };
    let fmt = match get("format")? {
        Value::Str(s) => s,
        _ => return Err("format must be a string".to_string()),
    };
    let op = match get("op")? {
        Value::Str(s) => s,
        _ => return Err("op must be a string".to_string()),
    };
    let depth = match case.get("options") {
        Some(Value::Table(opts)) => match opts.iter().find(|(k, _)| k == "depth") {
            Some((_, Value::Int(n))) => *n as u32,
            _ => DEFAULT_DEPTH_LIMIT,
        },
        _ => DEFAULT_DEPTH_LIMIT,
    };
    let expect = get("expect")?;

    let run = |depth: u32| -> Result<Outcome, SerdeError> {
        if op == "decode" {
            let input = vector_input_bytes(case)
                .map_err(|e| SerdeError::new("SERDE_TEST_INPUT", e, None))?;
            match fmt.as_str() {
                "json" => {
                    let v = json_decode(&input, &JsonOptions { depth_limit: depth })?;
                    let enc = json_encode(&v, &JsonOptions { depth_limit: depth })?;
                    Ok(Outcome::Ok(v, Value::Str(String::from_utf8(enc).unwrap())))
                }
                "toml" => {
                    let v = toml_decode(&input, &TomlOptions { depth_limit: depth })?;
                    let enc = toml_encode(&v, &TomlOptions { depth_limit: depth })?;
                    Ok(Outcome::Ok(v, Value::Str(String::from_utf8(enc).unwrap())))
                }
                "msgpack" => {
                    let v = msgpack_decode(&input, &MsgPackOptions { depth_limit: depth })?;
                    let enc = msgpack_encode(&v, &MsgPackOptions { depth_limit: depth })?;
                    Ok(Outcome::Ok(v, Value::Str(hex_encode(&enc))))
                }
                other => Err(SerdeError::new(
                    "SERDE_TEST_INPUT",
                    format!("unknown format {other}"),
                    None,
                )),
            }
        } else {
            let input_value =
                get("value").map_err(|e| SerdeError::new("SERDE_TEST_INPUT", e, None))?;
            let v = vve_parse(&input_value)
                .map_err(|e| SerdeError::new("SERDE_TEST_INPUT", e, None))?;
            match fmt.as_str() {
                "json" => {
                    let enc = json_encode(&v, &JsonOptions { depth_limit: depth })?;
                    let back = json_decode(&enc, &JsonOptions { depth_limit: depth })?;
                    Ok(Outcome::Ok(
                        back,
                        Value::Str(String::from_utf8(enc).unwrap()),
                    ))
                }
                "toml" => {
                    let enc = toml_encode(&v, &TomlOptions { depth_limit: depth })?;
                    let back = toml_decode(&enc, &TomlOptions { depth_limit: depth })?;
                    Ok(Outcome::Ok(
                        back,
                        Value::Str(String::from_utf8(enc).unwrap()),
                    ))
                }
                "msgpack" => {
                    let enc = msgpack_encode(&v, &MsgPackOptions { depth_limit: depth })?;
                    let back = msgpack_decode(&enc, &MsgPackOptions { depth_limit: depth })?;
                    Ok(Outcome::Ok(back, Value::Str(hex_encode(&enc))))
                }
                other => Err(SerdeError::new(
                    "SERDE_TEST_INPUT",
                    format!("unknown format {other}"),
                    None,
                )),
            }
        }
    };

    match run(depth) {
        Ok(Outcome::Ok(v, enc)) => {
            if let Some(exp_value) = expect.get("value") {
                let want = vve_parse(exp_value)?;
                if !value_eq(&v, &want) {
                    return Err(format!(
                        "{id}: value mismatch\n  got:  {v:?}\n  want: {want:?}"
                    ));
                }
            }
            if let Some(Value::Str(want_enc)) = expect.get("encoding") {
                let got = match &enc {
                    Value::Str(s) => s.clone(),
                    _ => unreachable!(),
                };
                if &got != want_enc {
                    return Err(format!(
                        "{id}: encoding mismatch\n  got:  {got:?}\n  want: {want_enc:?}"
                    ));
                }
            }
            if expect.get("error").is_some() {
                return Err(format!(
                    "{id}: expected an error but the operation succeeded"
                ));
            }
            Ok(())
        }
        Err(e) => {
            let exp_err = match expect.get("error") {
                Some(x) => x,
                None => return Err(format!("{id}: operation failed but no error expected: {e}")),
            };
            let code = match exp_err.get("code") {
                Some(Value::Str(s)) => s.clone(),
                _ => return Err(format!("{id}: error.code missing")),
            };
            if e.code != code {
                return Err(format!(
                    "{id}: error code mismatch: got {} want {}",
                    e.code, code
                ));
            }
            let want_offset = exp_err.get("offset").map(|o| match o {
                Value::Null => None,
                Value::Int(n) => Some(*n as usize),
                other => panic!("{id}: bad offset in vectors: {other:?}"),
            });
            if want_offset != Some(e.offset) {
                return Err(format!(
                    "{id}: error offset mismatch: got {:?} want {:?}",
                    e.offset, want_offset
                ));
            }
            Ok(())
        }
    }
}

#[test]
fn shared_vectors_bit_identical() {
    let doc = load_vectors();
    let cases = match doc.get("cases") {
        Some(Value::Array(c)) => c.clone(),
        _ => panic!("vector file has no cases array"),
    };
    assert!(
        cases.len() >= 100,
        "expected >= 100 vector cases, got {}",
        cases.len()
    );
    let mut failures = Vec::new();
    for case in &cases {
        if let Err(e) = check_case(case) {
            failures.push(e);
        }
    }
    if !failures.is_empty() {
        panic!(
            "{} of {} vector cases failed:\n{}",
            failures.len(),
            cases.len(),
            failures.join("\n")
        );
    }
}

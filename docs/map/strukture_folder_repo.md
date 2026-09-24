# LombokSerde — Folder Structure

```
LombokSerde/
├── docs/
│   ├── architecture_repo.md          # ADRs and design decisions
│   ├── masterplan_repo.md            # Implementation roadmap
│   ├── changelog.md                  # Version history
│   └── map/
│       └── strukture_folder_repo.md  # This file
│
├── rust/
│   ├── Cargo.toml
│   └── src/
│       ├── lib.rs                    # Crate root, feature gates, re-exports
│       ├── error.rs                  # SerdeError enum
│       ├── value.rs                  # Value IR enum + conversion traits
│       ├── traits.rs                 # Serialize/Deserialize trait definitions
│       ├── json/
│       │   ├── mod.rs                # JSON module root
│       │   ├── parser.rs             # Recursive descent JSON parser
│       │   ├── serializer.rs         # JSON serializer (compact + pretty)
│       │   └── tokenizer.rs          # Streaming JSON tokenizer
│       ├── toml/
│       │   ├── mod.rs                # TOML module root
│       │   ├── parser.rs             # TOML v1.0 parser
│       │   └── serializer.rs         # TOML serializer
│       └── msgpack/
│           ├── mod.rs                # MessagePack module root
│           ├── encoder.rs            # MessagePack encoder
│           └── decoder.rs            # MessagePack decoder
│
├── rust-derive/
│   ├── Cargo.toml                    # proc-macro crate
│   └── src/
│       └── lib.rs                    # #[derive(LombokSerialize, LombokDeserialize)]
│
├── typescript/
│   ├── package.json
│   ├── tsconfig.json
│   └── src/
│       ├── index.ts                  # Public API re-exports
│       ├── error.ts                  # SerdeError class
│       ├── value.ts                  # Value type + helpers
│       ├── traits.ts                 # Serialize/Deserialize interfaces
│       ├── json/
│       │   ├── index.ts
│       │   ├── parser.ts             # JSON parser
│       │   ├── serializer.ts         # JSON serializer
│       │   └── tokenizer.ts          # Streaming tokenizer
│       ├── toml/
│       │   ├── index.ts
│       │   ├── parser.ts             # TOML parser
│       │   └── serializer.ts         # TOML serializer
│       └── msgpack/
│           ├── index.ts
│           ├── encoder.ts            # MsgPack encoder
│           └── decoder.ts            # MsgPack decoder
│
├── python/
│   ├── pyproject.toml
│   └── lombokserde/
│       ├── __init__.py               # Public API
│       ├── error.py                  # SerdeError exception
│       ├── value.py                  # Value IR classes
│       ├── traits.py                 # Serialize/Deserialize protocols
│       ├── json/
│       │   ├── __init__.py
│       │   ├── parser.py             # JSON parser
│       │   ├── serializer.py         # JSON serializer
│       │   └── tokenizer.py          # Streaming tokenizer
│       ├── toml/
│       │   ├── __init__.py
│       │   ├── parser.py             # TOML parser
│       │   └── serializer.py         # TOML serializer
│       └── msgpack/
│           ├── __init__.py
│           ├── encoder.py            # MsgPack encoder
│           └── decoder.py            # MsgPack decoder
│
├── go/
│   ├── go.mod
│   ├── serde.go                      # Value IR, traits, errors
│   ├── json/
│   │   ├── parser.go                 # JSON parser
│   │   ├── serializer.go             # JSON serializer
│   │   └── tokenizer.go              # Streaming tokenizer
│   ├── toml/
│   │   ├── parser.go                 # TOML parser
│   │   └── serializer.go             # TOML serializer
│   └── msgpack/
│       ├── encoder.go                # MsgPack encoder
│       └── decoder.go                # MsgPack decoder
│
├── php/
│   ├── composer.json
│   └── src/
│       ├── SerdeError.php            # Error class
│       ├── Value.php                 # Value IR enum/class
│       ├── Serialize.php             # Serialize interface
│       ├── Deserialize.php           # Deserialize interface
│       ├── Json/
│       │   ├── Parser.php            # JSON parser
│       │   ├── Serializer.php        # JSON serializer
│       │   └── Tokenizer.php         # Streaming tokenizer
│       ├── Toml/
│       │   ├── Parser.php            # TOML parser
│       │   └── Serializer.php        # TOML serializer
│       └── Msgpack/
│           ├── Encoder.php           # MsgPack encoder
│           └── Decoder.php           # MsgPack decoder
│
├── test-vectors/
│   └── serde_vectors.json            # Cross-language test vectors
│
├── .github/
│   └── workflows/
│       ├── rust.yml
│       ├── typescript.yml
│       ├── python.yml
│       ├── go.yml
│       └── php.yml
│
├── README.md
├── LICENSE
└── .gitignore
```

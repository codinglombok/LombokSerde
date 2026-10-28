<?php

declare(strict_types=1);

namespace CodingLombok\LombokSerde;

/**
 * Stable error codes shared across all ports (SPEC section 6).
 */
final class SerdeErrorCode
{
    public const JSON_SYNTAX = 'SERDE_JSON_SYNTAX';
    public const JSON_UTF8 = 'SERDE_JSON_UTF8';
    public const JSON_DEPTH = 'SERDE_JSON_DEPTH';
    public const JSON_TRAILING = 'SERDE_JSON_TRAILING';
    public const JSON_INT_RANGE = 'SERDE_JSON_INT_RANGE';
    public const JSON_FLOAT_NANINF = 'SERDE_JSON_FLOAT_NANINF';
    public const JSON_BYTES = 'SERDE_JSON_BYTES';
    public const JSON_DATETIME = 'SERDE_JSON_DATETIME';
    public const TOML_SYNTAX = 'SERDE_TOML_SYNTAX';
    public const TOML_UTF8 = 'SERDE_TOML_UTF8';
    public const TOML_DUPLICATE = 'SERDE_TOML_DUPLICATE';
    public const TOML_DEPTH = 'SERDE_TOML_DEPTH';
    public const TOML_ROOT = 'SERDE_TOML_ROOT';
    public const TOML_BYTES = 'SERDE_TOML_BYTES';
    public const TOML_DATETIME = 'SERDE_TOML_DATETIME';
    public const MP_TRUNCATED = 'SERDE_MP_TRUNCATED';
    public const MP_UNEXPECTED = 'SERDE_MP_UNEXPECTED';
    public const MP_TRAILING = 'SERDE_MP_TRAILING';
    public const MP_UTF8 = 'SERDE_MP_UTF8';
    public const MP_EXT = 'SERDE_MP_EXT';
    public const MP_DEPTH = 'SERDE_MP_DEPTH';
    public const MP_DUPLICATE = 'SERDE_MP_DUPLICATE';
    public const MP_DATETIME = 'SERDE_MP_DATETIME';
    public const TABLE_DUPLICATE = 'SERDE_TABLE_DUPLICATE';
}

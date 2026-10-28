<?php

declare(strict_types=1);

namespace CodingLombok\LombokSerde;

/**
 * Datetime mirrors the TOML datetime kinds (SPEC section 2). `raw` keeps the
 * exact source text for TOML decode; MessagePack timestamps decode to the
 * canonical `...Z` form.
 */
final class Datetime
{
    public function __construct(
        public readonly string $kind, // offset | localdt | date | time
        public readonly string $raw,
    ) {
    }
}

/** One sorted key/value pair of a Table value. */
final class TableEntry
{
    public function __construct(
        public readonly string $key,
        public readonly Value $value,
    ) {
    }
}

/**
 * The canonical tagged union shared by all formats.
 * Invariant: Table entries are sorted bytewise by key, without duplicates.
 *
 * `uint` values always carry a canonical decimal string in $uintStr (PHP
 * ints are signed 64-bit and cannot hold the full u64 range).
 */
final class Value
{
    public const KIND_NULL = 'null';
    public const KIND_BOOL = 'bool';
    public const KIND_INT = 'int';
    public const KIND_UINT = 'uint';
    public const KIND_FLOAT = 'float';
    public const KIND_STR = 'str';
    public const KIND_BYTES = 'bytes';
    public const KIND_ARRAY = 'array';
    public const KIND_TABLE = 'table';
    public const KIND_DATETIME = 'datetime';

    public function __construct(
        public readonly string $kind,
        public readonly bool $bool = false,
        public readonly int $int = 0,
        public readonly ?string $uintStr = null,
        public readonly float $float = 0.0,
        public readonly string $str = '',
        public readonly string $bytes = '',
        public readonly array $array = [],   // list<Value>
        public readonly array $table = [],   // list<TableEntry>, sorted
        public readonly ?Datetime $datetime = null,
    ) {
    }

    // Constructors -----------------------------------------------------------

    public static function null(): self
    {
        return new self(self::KIND_NULL);
    }

    public static function bool(bool $b): self
    {
        return new self(self::KIND_BOOL, bool: $b);
    }

    public static function int(int $n): self
    {
        return new self(self::KIND_INT, int: $n);
    }

    /** $n is a non-negative PHP int or a canonical decimal string. */
    public static function uint(int|string $n): self
    {
        if (\is_int($n)) {
            if ($n < 0) {
                throw new \LogicException('uint must be non-negative');
            }
            $n = (string) $n;
        }

        return new self(self::KIND_UINT, uintStr: U64::trim($n));
    }

    public static function float(float $f): self
    {
        return new self(self::KIND_FLOAT, float: $f);
    }

    public static function str(string $s): self
    {
        return new self(self::KIND_STR, str: $s);
    }

    public static function bytes(string $b): self
    {
        return new self(self::KIND_BYTES, bytes: $b);
    }

    /** @param list<Value> $items */
    public static function array(array $items): self
    {
        return new self(self::KIND_ARRAY, array: $items);
    }

    /** Sorts the pairs bytewise and fails closed on duplicates. */
    public static function table(array $pairs): self
    {
        $entries = self::sortedEntries($pairs);
        $n = \count($entries);
        for ($j = 1; $j < $n; $j++) {
            if ($entries[$j - 1]->key === $entries[$j]->key) {
                throw new SerdeError(
                    SerdeErrorCode::TABLE_DUPLICATE,
                    "duplicate key \"{$entries[$j]->key}\"",
                );
            }
        }

        return new self(self::KIND_TABLE, table: $entries);
    }

    /** Builds a table from pairs known to be duplicate-free. */
    public static function tableUnchecked(array $pairs): self
    {
        return new self(self::KIND_TABLE, table: self::sortedEntries($pairs));
    }

    public static function datetime(string $kind, string $raw): self
    {
        return new self(self::KIND_DATETIME, datetime: new Datetime($kind, $raw));
    }

    /** @param array<int, TableEntry|array{0:string,1:Value}> $pairs */
    private static function sortedEntries(array $pairs): array
    {
        $entries = [];
        foreach ($pairs as $p) {
            $entries[] = $p instanceof TableEntry ? $p : new TableEntry($p[0], $p[1]);
        }
        usort($entries, static fn (TableEntry $a, TableEntry $b): int => \strcmp($a->key, $b->key));

        return $entries;
    }

    /** Looks a key up by binary search (bytewise order). */
    public function tableGet(string $key): ?Value
    {
        if ($this->kind !== self::KIND_TABLE) {
            return null;
        }
        $lo = 0;
        $hi = \count($this->table);
        while ($lo < $hi) {
            $mid = ($lo + $hi) >> 1;
            $c = \strcmp($this->table[$mid]->key, $key);
            if ($c === 0) {
                return $this->table[$mid]->value;
            }
            if ($c < 0) {
                $lo = $mid + 1;
            } else {
                $hi = $mid;
            }
        }

        return null;
    }

    /** Decimal text of an int or uint value (for writers). */
    public function decimalText(): string
    {
        return $this->kind === self::KIND_UINT ? $this->uintStr : (string) $this->int;
    }
}

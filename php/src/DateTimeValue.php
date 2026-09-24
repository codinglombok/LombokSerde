<?php

declare(strict_types=1);

namespace LombokSerde;

class DateTimeValue
{
    public function __construct(
        public readonly string $kind,  // 'offset', 'local-datetime', 'local-date', 'local-time'
        public readonly string $value,
    ) {}
}

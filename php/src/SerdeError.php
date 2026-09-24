<?php

declare(strict_types=1);

namespace LombokSerde;

class SerdeError extends \RuntimeException
{
    public function __construct(
        public readonly SerdeErrorCode $code,
        string $message,
        public readonly ?int $line = null,
        public readonly ?int $column = null,
    ) {
        $loc = ($line !== null && $column !== null) ? " at line {$line}, col {$column}" : '';
        parent::__construct("{$code->value}: {$message}{$loc}");
    }
}

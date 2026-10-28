<?php

declare(strict_types=1);

namespace CodingLombok\LombokSerde;

/**
 * The shared error type: `[CODE] message` and, with a position,
 * `[CODE] message (at byte N)`.
 *
 * The code is exposed through code() because \Exception already reserves a
 * $code property.
 */
final class SerdeError extends \RuntimeException
{
    public function __construct(
        private readonly string $errorCode,
        string $message,
        public readonly ?int $offset = null,
    ) {
        $loc = $offset !== null ? " (at byte {$offset})" : '';
        parent::__construct("[{$errorCode}] {$message}{$loc}");
    }

    public function code(): string
    {
        return $this->errorCode;
    }
}

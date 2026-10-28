<?php

declare(strict_types=1);

/**
 * Zero-dependency class loader for the LombokSerde PHP port (PSR-4 mirror
 * of the composer.json mapping, usable without composer install).
 */

spl_autoload_register(static function (string $class): void {
    $prefix = 'CodingLombok\\LombokSerde\\';
    if (!\str_starts_with($class, $prefix)) {
        return;
    }
    $rel = \substr($class, \strlen($prefix));
    $path = __DIR__ . '/../src/' . \str_replace('\\', '/', $rel) . '.php';
    if (\is_file($path)) {
        require $path;
    }
});

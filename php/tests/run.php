<?php

declare(strict_types=1);

// Runs every suite in one process. With the pcov extension loaded and
// --coverage=N, also fails when line coverage of src/ is below N percent
// (mirrors the LombokVector PHP runner).

$min = null;
foreach ($argv as $arg) {
    if (str_starts_with($arg, '--coverage=')) {
        $min = (float) substr($arg, strlen('--coverage='));
    }
}
$src = realpath(__DIR__ . '/../src');
$coverage = $min !== null && extension_loaded('pcov');
if ($min !== null && !$coverage) {
    fwrite(STDERR, "pcov extension not loaded; coverage not measured\n");
    exit(1);
}
if ($coverage) {
    \pcov\start();
}
\define('LOMBOKSERDE_INCLUDED', true);

require __DIR__ . '/bootstrap.php';

global $tests;
$tests = [];

require __DIR__ . '/units.php';
require __DIR__ . '/extra.php';
[$up, $uf] = run_unit_suite();

require __DIR__ . '/vectors.php';
[$vt, $vf] = run_vector_suite();

if ($coverage) {
    \pcov\stop();
    $files = [];
    $it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($src, FilesystemIterator::SKIP_DOTS));
    foreach ($it as $f) {
        $files[] = $f->getPathname();
    }
    $hit = 0;
    $total = 0;
    foreach (\pcov\collect(\pcov\inclusive, $files) as $file => $lines) {
        $missed = [];
        foreach ($lines as $line => $count) {
            $total++;
            if ($count > 0) {
                $hit++;
            } else {
                $missed[] = $line;
            }
        }
        if ($missed !== []) {
            echo substr($file, strlen($src) + 1) . ': not run ' . implode(',', $missed) . "\n";
        }
    }
    $pct = $total ? 100 * $hit / $total : 100.0;
    printf("coverage: %.1f%% of %d lines (threshold %.0f%%)\n", $pct, $total, $min);
    if ($pct < $min) {
        exit(1);
    }
}
exit(($uf + $vf) === 0 ? 0 : 1);

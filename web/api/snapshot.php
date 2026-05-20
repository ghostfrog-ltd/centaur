<?php

declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');

$projectRoot = dirname(__DIR__, 2);
$snapshotPath = $projectRoot . '/var/dashboard_snapshot.json';

if (!is_file($snapshotPath)) {
    http_response_code(503);
    echo json_encode([
        'ok' => false,
        'error' => 'snapshot_not_ready',
        'detail' => 'The host runtime has not written var/dashboard_snapshot.json yet.',
    ], JSON_PRETTY_PRINT);
    exit;
}

$payload = file_get_contents($snapshotPath);
if ($payload === false || trim($payload) === '') {
    http_response_code(500);
    echo json_encode([
        'ok' => false,
        'error' => 'snapshot_unreadable',
    ], JSON_PRETTY_PRINT);
    exit;
}

echo $payload;

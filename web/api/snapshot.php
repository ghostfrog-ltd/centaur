<?php

declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');

require __DIR__ . '/snapshot_cache.php';

$result = centaurResolveSnapshotPayload();
if ($result['ok'] !== true) {
    respondWithError(
        (int) ($result['status_code'] ?? 503),
        (string) ($result['error'] ?? 'dashboard_api_unavailable'),
        (string) ($result['detail'] ?? 'The live Centaur dashboard API did not return a usable JSON payload.'),
        $result['extra'] ?? []
    );
}

header('X-Centaur-Cache-Status: ' . (string) ($result['cache_status'] ?? 'unknown'));
header('X-Centaur-Cache-Age: ' . (string) ((int) ($result['cache_age_seconds'] ?? 0)));
echo (string) $result['body'];

function respondWithError(int $statusCode, string $error, string $detail, array $extra = []): void
{
    http_response_code($statusCode);
    echo json_encode(
        array_merge(
            [
                'ok' => false,
                'error' => $error,
                'detail' => $detail,
            ],
            $extra
        ),
        JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES
    );
    exit;
}

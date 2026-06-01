<?php

declare(strict_types=1);

function centaurSnapshotApiUrl(): string
{
    return getenv('CENTAUR_DASHBOARD_API_URL') ?: 'http://host.docker.internal:8788/api/snapshot';
}

function centaurSnapshotTimeoutSeconds(): int
{
    $timeoutSeconds = (int) (getenv('CENTAUR_DASHBOARD_API_TIMEOUT_SECONDS') ?: '20');
    return max(1, $timeoutSeconds);
}

function centaurSnapshotCacheTtlSeconds(): int
{
    $ttlSeconds = (int) (getenv('CENTAUR_DASHBOARD_CACHE_TTL_SECONDS') ?: '3600');
    return max(60, $ttlSeconds);
}

function centaurSnapshotCachePath(): string
{
    return dirname(__DIR__) . '/cache/dashboard_snapshot.json';
}

function centaurResolveSnapshotPayload(): array
{
    $apiUrl = centaurSnapshotApiUrl();
    if (filter_var($apiUrl, FILTER_VALIDATE_URL) === false) {
        return [
            'ok' => false,
            'status_code' => 500,
            'error' => 'dashboard_api_url_invalid',
            'detail' => 'CENTAUR_DASHBOARD_API_URL is not a valid URL.',
            'extra' => ['api_url' => $apiUrl],
        ];
    }

    $cachePath = centaurSnapshotCachePath();
    $cacheTtlSeconds = centaurSnapshotCacheTtlSeconds();
    $cachedPayload = centaurReadSnapshotCache($cachePath);
    if ($cachedPayload !== null && $cachedPayload['age_seconds'] <= $cacheTtlSeconds) {
        return [
            'ok' => true,
            'body' => $cachedPayload['body'],
            'decoded' => $cachedPayload['decoded'],
            'cache_status' => 'fresh',
            'cache_path' => $cachePath,
            'cache_age_seconds' => $cachedPayload['age_seconds'],
        ];
    }

    $result = centaurFetchDashboardPayload($apiUrl, centaurSnapshotTimeoutSeconds());
    if ($result['ok'] === true) {
        $decoded = json_decode($result['body'], true);
        if (!is_array($decoded)) {
            if ($cachedPayload !== null) {
                return [
                    'ok' => true,
                    'body' => $cachedPayload['body'],
                    'decoded' => $cachedPayload['decoded'],
                    'cache_status' => 'stale',
                    'cache_path' => $cachePath,
                    'cache_age_seconds' => $cachedPayload['age_seconds'],
                ];
            }

            return [
                'ok' => false,
                'status_code' => 502,
                'error' => 'dashboard_api_invalid_json',
                'detail' => 'The live Centaur dashboard API returned invalid JSON.',
                'extra' => ['api_url' => $apiUrl],
            ];
        }

        $encoded = json_encode($decoded, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
        if ($encoded === false) {
            $encoded = $result['body'];
        }
        centaurWriteSnapshotCache($cachePath, $encoded);

        return [
            'ok' => true,
            'body' => $encoded,
            'decoded' => $decoded,
            'cache_status' => 'miss',
            'cache_path' => $cachePath,
            'cache_age_seconds' => 0,
        ];
    }

    if ($cachedPayload !== null) {
        return [
            'ok' => true,
            'body' => $cachedPayload['body'],
            'decoded' => $cachedPayload['decoded'],
            'cache_status' => 'stale',
            'cache_path' => $cachePath,
            'cache_age_seconds' => $cachedPayload['age_seconds'],
        ];
    }

    return [
        'ok' => false,
        'status_code' => 503,
        'error' => 'dashboard_api_unavailable',
        'detail' => 'The live Centaur dashboard API did not return a usable JSON payload.',
        'extra' => [
            'api_url' => $apiUrl,
            'transport' => $result['transport'],
            'upstream_status' => $result['status_code'],
            'upstream_error' => $result['error'],
        ],
    ];
}

function centaurReadSnapshotCache(string $cachePath): ?array
{
    if (!is_file($cachePath) || !is_readable($cachePath)) {
        return null;
    }

    $body = @file_get_contents($cachePath);
    if (!is_string($body) || trim($body) === '') {
        return null;
    }

    $decoded = json_decode($body, true);
    if (!is_array($decoded)) {
        return null;
    }

    $modifiedAt = @filemtime($cachePath);
    if (!is_int($modifiedAt) || $modifiedAt <= 0) {
        $modifiedAt = time();
    }

    return [
        'body' => $body,
        'decoded' => $decoded,
        'age_seconds' => max(0, time() - $modifiedAt),
    ];
}

function centaurWriteSnapshotCache(string $cachePath, string $body): void
{
    $cacheDir = dirname($cachePath);
    if (!is_dir($cacheDir)) {
        @mkdir($cacheDir, 0775, true);
    }
    @file_put_contents($cachePath, $body, LOCK_EX);
}

function centaurFetchDashboardPayload(string $url, int $timeoutSeconds): array
{
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_CONNECTTIMEOUT => min(5, $timeoutSeconds),
            CURLOPT_TIMEOUT => $timeoutSeconds,
            CURLOPT_HTTPHEADER => ['Accept: application/json'],
        ]);
        $body = curl_exec($ch);
        $error = curl_error($ch);
        $statusCode = (int) curl_getinfo($ch, CURLINFO_RESPONSE_CODE);
        unset($ch);

        if ($body === false || $error !== '') {
            return [
                'ok' => false,
                'transport' => 'curl',
                'status_code' => $statusCode,
                'error' => $error !== '' ? $error : 'curl_exec_failed',
                'body' => '',
            ];
        }

        return [
            'ok' => $statusCode >= 200 && $statusCode < 300 && trim($body) !== '',
            'transport' => 'curl',
            'status_code' => $statusCode,
            'error' => '',
            'body' => $body,
        ];
    }

    $context = stream_context_create([
        'http' => [
            'method' => 'GET',
            'timeout' => $timeoutSeconds,
            'ignore_errors' => true,
            'header' => "Accept: application/json\r\n",
        ],
    ]);
    $body = @file_get_contents($url, false, $context);
    $headers = $http_response_header ?? [];
    $statusCode = centaurExtractStatusCode($headers);

    if ($body === false) {
        return [
            'ok' => false,
            'transport' => 'stream',
            'status_code' => $statusCode,
            'error' => 'file_get_contents_failed',
            'body' => '',
        ];
    }

    return [
        'ok' => $statusCode >= 200 && $statusCode < 300 && trim($body) !== '',
        'transport' => 'stream',
        'status_code' => $statusCode,
        'error' => '',
        'body' => $body,
    ];
}

function centaurExtractStatusCode(array $headers): int
{
    foreach ($headers as $header) {
        if (preg_match('/^HTTP\/\S+\s+(\d{3})\b/', $header, $matches) === 1) {
            return (int) $matches[1];
        }
    }

    return 0;
}

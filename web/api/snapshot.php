<?php

declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');

$apiUrl = getenv('CENTAUR_DASHBOARD_API_URL') ?: 'http://host.docker.internal:8788/api/snapshot';
$timeoutSeconds = (int) (getenv('CENTAUR_DASHBOARD_API_TIMEOUT_SECONDS') ?: '8');
if ($timeoutSeconds <= 0) {
    $timeoutSeconds = 8;
}

if (filter_var($apiUrl, FILTER_VALIDATE_URL) === false) {
    respondWithError(
        500,
        'dashboard_api_url_invalid',
        'CENTAUR_DASHBOARD_API_URL is not a valid URL.',
        ['api_url' => $apiUrl]
    );
}

$result = fetchDashboardPayload($apiUrl, $timeoutSeconds);
if ($result['ok'] !== true) {
    respondWithError(
        503,
        'dashboard_api_unavailable',
        'The live Centaur dashboard API did not return a usable JSON payload.',
        [
            'api_url' => $apiUrl,
            'transport' => $result['transport'],
            'upstream_status' => $result['status_code'],
            'upstream_error' => $result['error'],
        ]
    );
}

$decoded = json_decode($result['body'], true);
if (!is_array($decoded)) {
    respondWithError(
        502,
        'dashboard_api_invalid_json',
        'The live Centaur dashboard API returned invalid JSON.',
        ['api_url' => $apiUrl]
    );
}

echo json_encode($decoded, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);

function fetchDashboardPayload(string $url, int $timeoutSeconds): array
{
    if (function_exists('curl_init')) {
        $ch = curl_init($url);
        curl_setopt_array($ch, [
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_FOLLOWLOCATION => false,
            CURLOPT_CONNECTTIMEOUT => min(3, $timeoutSeconds),
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
    $statusCode = extractStatusCode($headers);

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

function extractStatusCode(array $headers): int
{
    foreach ($headers as $header) {
        if (preg_match('/^HTTP\/\S+\s+(\d{3})\b/', $header, $matches) === 1) {
            return (int) $matches[1];
        }
    }

    return 0;
}

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

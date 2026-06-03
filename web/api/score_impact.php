<?php

declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');

require __DIR__ . '/snapshot_cache.php';

$days = max(1, min(366, (int) ($_GET['days'] ?? 90)));
$url = centaurScoreImpactApiUrl($days);
$result = centaurFetchDashboardPayload($url, centaurSnapshotTimeoutSeconds());

if (($result['ok'] ?? false) !== true) {
    http_response_code(503);
    echo json_encode(
        [
            'ok' => false,
            'error' => 'score_impact_api_unavailable',
            'detail' => 'The Centaur dashboard API did not return score-impact data.',
            'api_url' => $url,
            'transport' => $result['transport'] ?? 'unknown',
            'upstream_status' => $result['status_code'] ?? 0,
            'upstream_error' => $result['error'] ?? '',
        ],
        JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES
    );
    exit;
}

echo (string) $result['body'];

function centaurScoreImpactApiUrl(int $days): string
{
    $snapshotUrl = centaurSnapshotApiUrl();
    $path = '/api/score-impact?' . http_build_query(['days' => $days]);
    if (str_ends_with($snapshotUrl, '/api/snapshot')) {
        return substr($snapshotUrl, 0, -strlen('/api/snapshot')) . $path;
    }
    $parts = parse_url($snapshotUrl);
    if (!is_array($parts) || empty($parts['scheme']) || empty($parts['host'])) {
        return $snapshotUrl;
    }
    $port = isset($parts['port']) ? ':' . (string) $parts['port'] : '';
    return $parts['scheme'] . '://' . $parts['host'] . $port . $path;
}

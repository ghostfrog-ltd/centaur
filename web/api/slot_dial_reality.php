<?php

declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');

require __DIR__ . '/snapshot_cache.php';

$hours = max(1, min(720, (int) ($_GET['hours'] ?? 168)));
$brokerId = preg_replace('/[^a-z0-9_\\-]/i', '', (string) ($_GET['broker_id'] ?? 'alpaca_paper'));
if ($brokerId === '') {
    $brokerId = 'alpaca_paper';
}

$params = [
    'hours' => $hours,
    'broker_id' => $brokerId,
    'target_win_pct' => slotDialRealityBoundedFloat($_GET['target_win_pct'] ?? null, 1.6, 0.01, 20.0),
    'loss_cap_pct' => slotDialRealityBoundedFloat($_GET['loss_cap_pct'] ?? null, 0.8, 0.0, 20.0),
    'slot_size_usd' => slotDialRealityBoundedFloat($_GET['slot_size_usd'] ?? null, 10.0, 0.01, 10000.0),
    'trades_per_day' => slotDialRealityBoundedFloat($_GET['trades_per_day'] ?? null, 100.0, 0.1, 1000.0),
    'losses_per_day' => slotDialRealityBoundedFloat($_GET['losses_per_day'] ?? null, 50.0, 0.0, 1000.0),
];

$url = centaurSlotDialRealityApiUrl($params);
$result = centaurFetchDashboardPayload($url, centaurSnapshotTimeoutSeconds());

if (($result['ok'] ?? false) !== true) {
    http_response_code(503);
    echo json_encode(
        [
            'ok' => false,
            'error' => 'slot_dial_reality_api_unavailable',
            'detail' => 'The Centaur dashboard API did not return slot dial reality data.',
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

function slotDialRealityBoundedFloat(mixed $value, float $default, float $min, float $max): float
{
    if (!is_numeric($value)) {
        return $default;
    }
    $number = (float) $value;
    if (!is_finite($number)) {
        return $default;
    }
    return max($min, min($max, $number));
}

function centaurSlotDialRealityApiUrl(array $params): string
{
    $snapshotUrl = centaurSnapshotApiUrl();
    $path = '/api/slot-dial-reality?' . http_build_query($params);
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

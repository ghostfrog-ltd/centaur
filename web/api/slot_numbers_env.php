<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');

const SLOT_NUMBERS_ALLOWED_ENV_KEYS = [
    'PAPER_EXECUTION_DEFAULT_NOTIONAL_USD',
    'LIVE_EXECUTION_DEFAULT_NOTIONAL_USD',
    'PAPER_EXECUTION_PROFIT_CAPTURE_PCT',
    'LIVE_EXECUTION_PROFIT_CAPTURE_PCT',
    'SHADOW_STOP_LOSS_PCT',
    'PAPER_CRYPTO_MOMENTUM_STOP_LOSS_PCT',
    'LIVE_CRYPTO_MOMENTUM_STOP_LOSS_PCT',
];

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
try {
    if ($method === 'GET') {
        slotNumbersRespond([
            'ok' => true,
            'values' => slotNumbersReadAllowedEnvValues(),
            'writable' => is_writable(slotNumbersEnvPath()),
        ]);
    }
    if ($method === 'POST') {
        slotNumbersHandlePost();
    }
    slotNumbersRespondError(405, 'method_not_allowed', 'Use GET or POST.');
} catch (Throwable $exc) {
    slotNumbersRespondError(500, 'slot_numbers_env_error', $exc->getMessage());
}

function slotNumbersHandlePost(): void
{
    $payload = json_decode((string) file_get_contents('php://input'), true);
    if (!is_array($payload)) {
        slotNumbersRespondError(400, 'invalid_json', 'Request body must be JSON.');
    }
    if (($payload['ack'] ?? '') !== 'update_slot_numbers_env') {
        slotNumbersRespondError(400, 'missing_ack', 'Saving requires the update_slot_numbers_env acknowledgement.');
    }

    $values = $payload['values'] ?? null;
    if (!is_array($values)) {
        slotNumbersRespondError(400, 'missing_values', 'Request body must include values.');
    }

    $cleanValues = [];
    foreach (SLOT_NUMBERS_ALLOWED_ENV_KEYS as $key) {
        if (!array_key_exists($key, $values)) {
            continue;
        }
        $cleanValues[$key] = slotNumbersValidateEnvValue($key, $values[$key]);
    }
    if (!$cleanValues) {
        slotNumbersRespondError(400, 'no_allowed_values', 'No allowed .env keys were provided.');
    }

    $before = slotNumbersReadAllowedEnvValues();
    slotNumbersUpdateEnvFile($cleanValues);
    $after = slotNumbersReadAllowedEnvValues();
    slotNumbersRespond([
        'ok' => true,
        'updated' => $cleanValues,
        'before' => $before,
        'after' => $after,
    ]);
}

function slotNumbersProjectRoot(): string
{
    return dirname(__DIR__, 2);
}

function slotNumbersEnvPath(): string
{
    return slotNumbersProjectRoot() . '/.env';
}

function slotNumbersReadAllowedEnvValues(): array
{
    $path = slotNumbersEnvPath();
    if (!is_readable($path)) {
        return [];
    }

    $values = [];
    $lines = file($path, FILE_IGNORE_NEW_LINES);
    if (!is_array($lines)) {
        return [];
    }
    foreach ($lines as $line) {
        if (!preg_match('/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/', $line, $matches)) {
            continue;
        }
        $key = $matches[1];
        if (!in_array($key, SLOT_NUMBERS_ALLOWED_ENV_KEYS, true)) {
            continue;
        }
        $values[$key] = trim($matches[2]);
    }
    return $values;
}

function slotNumbersValidateEnvValue(string $key, mixed $value): string
{
    if (is_int($value) || is_float($value)) {
        $raw = (string) $value;
    } elseif (is_string($value)) {
        $raw = trim($value);
    } else {
        slotNumbersRespondError(400, 'invalid_value', "$key must be a number.");
    }

    if (!preg_match('/^\d+(?:\.\d+)?$/', $raw)) {
        slotNumbersRespondError(400, 'invalid_value', "$key must be a non-negative number.");
    }
    $number = (float) $raw;
    if (!is_finite($number) || $number < 0) {
        slotNumbersRespondError(400, 'invalid_value', "$key must be a non-negative finite number.");
    }
    if (str_ends_with($key, '_DEFAULT_NOTIONAL_USD') && $number > 10.0) {
        slotNumbersRespondError(400, 'notional_too_high', "$key cannot be raised above 10 from this page.");
    }
    if (str_contains($key, 'PROFIT_CAPTURE_PCT') && $number > 10.0) {
        slotNumbersRespondError(400, 'profit_capture_too_high', "$key cannot be above 10% from this page.");
    }
    if (str_contains($key, 'STOP_LOSS_PCT') && $number > 10.0) {
        slotNumbersRespondError(400, 'stop_loss_too_high', "$key cannot be above 10% from this page.");
    }
    return rtrim(rtrim(sprintf('%.4F', $number), '0'), '.');
}

function slotNumbersUpdateEnvFile(array $updates): void
{
    $path = slotNumbersEnvPath();
    if (!is_readable($path) || !is_writable($path)) {
        slotNumbersRespondError(500, 'env_not_writable', '.env is not readable and writable from the web process.');
    }

    $handle = fopen($path, 'c+');
    if ($handle === false) {
        slotNumbersRespondError(500, 'env_open_failed', 'Could not open .env for update.');
    }
    try {
        if (!flock($handle, LOCK_EX)) {
            slotNumbersRespondError(500, 'env_lock_failed', 'Could not lock .env for update.');
        }
        rewind($handle);
        $contents = stream_get_contents($handle);
        if (!is_string($contents)) {
            slotNumbersRespondError(500, 'env_read_failed', 'Could not read .env.');
        }
        $lines = preg_split('/\R/', $contents);
        if (!is_array($lines)) {
            $lines = [];
        }
        if ($contents !== '' && preg_match('/\R$/', $contents) === 1) {
            array_pop($lines);
        }

        $seen = [];
        foreach ($lines as $index => $line) {
            if (!preg_match('/^(\s*)([A-Z0-9_]+)(\s*=\s*)(.*)$/', $line, $matches)) {
                continue;
            }
            $key = $matches[2];
            if (!array_key_exists($key, $updates)) {
                continue;
            }
            $lines[$index] = $matches[1] . $key . $matches[3] . $updates[$key];
            $seen[$key] = true;
        }
        foreach ($updates as $key => $value) {
            if (!isset($seen[$key])) {
                $lines[] = $key . '=' . $value;
            }
        }

        $nextContents = implode(PHP_EOL, $lines) . PHP_EOL;
        rewind($handle);
        if (!ftruncate($handle, 0)) {
            slotNumbersRespondError(500, 'env_truncate_failed', 'Could not truncate .env.');
        }
        if (fwrite($handle, $nextContents) === false) {
            slotNumbersRespondError(500, 'env_write_failed', 'Could not write .env.');
        }
        fflush($handle);
        flock($handle, LOCK_UN);
    } finally {
        fclose($handle);
    }
}

function slotNumbersRespond(array $payload): void
{
    echo json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
    exit;
}

function slotNumbersRespondError(int $statusCode, string $error, string $detail): void
{
    http_response_code($statusCode);
    slotNumbersRespond([
        'ok' => false,
        'error' => $error,
        'detail' => $detail,
    ]);
}

<?php
declare(strict_types=1);

header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');

const SCORE_NUMBERS_ALLOWED_ENV_KEYS = [
    'PAPER_MIN_SIGNAL_SCORE_TO_TRADE',
    'LIVE_MIN_SIGNAL_SCORE_TO_TRADE',
    'PAPER_OBSERVE_ONLY_SIGNAL_SCORE_FLOOR',
    'LIVE_OBSERVE_ONLY_SIGNAL_SCORE_FLOOR',
];

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
try {
    if ($method === 'GET') {
        scoreNumbersRespond([
            'ok' => true,
            'values' => scoreNumbersReadAllowedEnvValues(),
            'writable' => is_writable(scoreNumbersEnvPath()),
        ]);
    }
    if ($method === 'POST') {
        scoreNumbersHandlePost();
    }
    scoreNumbersRespondError(405, 'method_not_allowed', 'Use GET or POST.');
} catch (Throwable $exc) {
    scoreNumbersRespondError(500, 'score_numbers_env_error', $exc->getMessage());
}

function scoreNumbersHandlePost(): void
{
    $payload = json_decode((string) file_get_contents('php://input'), true);
    if (!is_array($payload)) {
        scoreNumbersRespondError(400, 'invalid_json', 'Request body must be JSON.');
    }
    if (($payload['ack'] ?? '') !== 'update_score_numbers_env') {
        scoreNumbersRespondError(400, 'missing_ack', 'Saving requires the update_score_numbers_env acknowledgement.');
    }

    $values = $payload['values'] ?? null;
    if (!is_array($values)) {
        scoreNumbersRespondError(400, 'missing_values', 'Request body must include values.');
    }

    $cleanValues = [];
    foreach (SCORE_NUMBERS_ALLOWED_ENV_KEYS as $key) {
        if (!array_key_exists($key, $values)) {
            continue;
        }
        $cleanValues[$key] = scoreNumbersValidateEnvValue($key, $values[$key]);
    }
    if (!$cleanValues) {
        scoreNumbersRespondError(400, 'no_allowed_values', 'No allowed .env keys were provided.');
    }

    $before = scoreNumbersReadAllowedEnvValues();
    scoreNumbersUpdateEnvFile($cleanValues);
    $after = scoreNumbersReadAllowedEnvValues();
    scoreNumbersRespond([
        'ok' => true,
        'updated' => $cleanValues,
        'before' => $before,
        'after' => $after,
    ]);
}

function scoreNumbersProjectRoot(): string
{
    return dirname(__DIR__, 2);
}

function scoreNumbersEnvPath(): string
{
    return scoreNumbersProjectRoot() . '/.env';
}

function scoreNumbersReadAllowedEnvValues(): array
{
    $path = scoreNumbersEnvPath();
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
        if (!in_array($key, SCORE_NUMBERS_ALLOWED_ENV_KEYS, true)) {
            continue;
        }
        $values[$key] = trim($matches[2]);
    }
    return $values;
}

function scoreNumbersValidateEnvValue(string $key, mixed $value): string
{
    if (is_int($value) || is_float($value)) {
        $raw = (string) $value;
    } elseif (is_string($value)) {
        $raw = trim($value);
    } else {
        scoreNumbersRespondError(400, 'invalid_value', "$key must be a number.");
    }

    if (!preg_match('/^\d+(?:\.\d+)?$/', $raw)) {
        scoreNumbersRespondError(400, 'invalid_value', "$key must be a non-negative number.");
    }
    $number = (float) $raw;
    if (!is_finite($number) || $number < 0 || $number > 150.0) {
        scoreNumbersRespondError(400, 'invalid_value', "$key must be between 0 and 150.");
    }
    return rtrim(rtrim(sprintf('%.4F', $number), '0'), '.');
}

function scoreNumbersUpdateEnvFile(array $updates): void
{
    $path = scoreNumbersEnvPath();
    if (!is_readable($path) || !is_writable($path)) {
        scoreNumbersRespondError(500, 'env_not_writable', '.env is not readable and writable from the web process.');
    }

    $handle = fopen($path, 'c+');
    if ($handle === false) {
        scoreNumbersRespondError(500, 'env_open_failed', 'Could not open .env for update.');
    }
    try {
        if (!flock($handle, LOCK_EX)) {
            scoreNumbersRespondError(500, 'env_lock_failed', 'Could not lock .env for update.');
        }
        rewind($handle);
        $contents = stream_get_contents($handle);
        if (!is_string($contents)) {
            scoreNumbersRespondError(500, 'env_read_failed', 'Could not read .env.');
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
            scoreNumbersRespondError(500, 'env_truncate_failed', 'Could not truncate .env.');
        }
        if (fwrite($handle, $nextContents) === false) {
            scoreNumbersRespondError(500, 'env_write_failed', 'Could not write .env.');
        }
        fflush($handle);
        flock($handle, LOCK_UN);
    } finally {
        fclose($handle);
    }
}

function scoreNumbersRespond(array $payload): void
{
    echo json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
    exit;
}

function scoreNumbersRespondError(int $statusCode, string $error, string $detail): void
{
    http_response_code($statusCode);
    scoreNumbersRespond([
        'ok' => false,
        'error' => $error,
        'detail' => $detail,
    ]);
}

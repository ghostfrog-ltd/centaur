<?php
declare(strict_types=1);

header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');

require __DIR__ . '/navigation.php';

function commandsEscape(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES | ENT_SUBSTITUTE, 'UTF-8');
}

function commandGroups(): array
{
    return [
        [
            'title' => 'Quick Start',
            'description' => 'The most common operator entry points for opening the local site, checking health, and seeing the current runtime summary.',
            'items' => [
                [
                    'command' => 'ddev start',
                    'example' => 'ddev start',
                    'tone' => 'ops',
                    'what' => 'Starts the local DDEV stack that serves the routed dashboard site.',
                ],
                [
                    'command' => 'scripts/centaur-agent.sh dashboard',
                    'example' => 'scripts/centaur-agent.sh dashboard',
                    'tone' => 'ops',
                    'what' => 'Convenience launcher for the DDEV-routed dashboard. It starts DDEV and reminds you of the dashboard URL.',
                ],
                [
                    'command' => 'Open the site',
                    'example' => 'https://ghostfrog-centaur.ddev.site',
                    'tone' => 'info',
                    'what' => 'Primary routed Centaur web dashboard and operator site.',
                ],
                [
                    'command' => 'Readable status summary',
                    'example' => '.venv-mac/bin/python main.py --status',
                    'tone' => 'read',
                    'what' => 'Prints a one-shot status report without running a control tick.',
                ],
                [
                    'command' => 'Launch agent + logs + summary',
                    'example' => 'scripts/centaur-agent.sh status',
                    'tone' => 'read',
                    'what' => 'Shows launchd agent details, recent wrapper/runtime logs, and then runs the same readable status summary.',
                ],
            ],
        ],
        [
            'title' => 'Run Centaur',
            'description' => 'Commands that actually run the control pipeline or its local development loop. These are operational commands, not read-only reports.',
            'items' => [
                [
                    'command' => 'One-shot control tick',
                    'example' => '.venv-mac/bin/python main.py',
                    'tone' => 'run',
                    'what' => 'Runs a single control tick with the current runtime config.',
                ],
                [
                    'command' => 'Development loop',
                    'example' => '.venv-mac/bin/python main.py --loop --interval-seconds 60 --max-ticks 10',
                    'tone' => 'run',
                    'what' => 'Runs repeated local ticks on a timer. Good for controlled testing without handing work to launchd.',
                ],
                [
                    'command' => 'Production heartbeat loop',
                    'example' => '.venv-mac/bin/python main.py --heartbeat-service --interval-seconds 30',
                    'tone' => 'run',
                    'what' => 'Runs the supervised heartbeat loop used by unattended service setups.',
                ],
                [
                    'command' => 'Launchd start',
                    'example' => 'scripts/centaur-agent.sh start',
                    'tone' => 'run',
                    'what' => 'Bootstraps and kickstarts the configured Centaur launch agent.',
                ],
                [
                    'command' => 'Launchd stop',
                    'example' => 'scripts/centaur-agent.sh stop',
                    'tone' => 'warn',
                    'what' => 'Stops the configured Centaur launch agent.',
                ],
                [
                    'command' => 'Launchd restart',
                    'example' => 'scripts/centaur-agent.sh restart',
                    'tone' => 'warn',
                    'what' => 'Restarts the configured Centaur launch agent and reloads the service state.',
                ],
            ],
        ],
        [
            'title' => 'Reports And Audits',
            'description' => 'Read-only commands for understanding the current system, evidence, execution history, and health signals before changing behavior.',
            'items' => [
                [
                    'command' => 'Autopilot proof',
                    'example' => '.venv-mac/bin/python main.py --autopilot-proof',
                    'tone' => 'read',
                    'what' => 'Runs a safe dry-run proof that autonomy stays in the learning lanes while broker paper and live lanes remain manual-only. This proof harness is separate from the real heartbeat path and must not be used to confirm or resolve real-heartbeat research-cycle alerts.',
                ],
                [
                    'command' => 'Evidence registry',
                    'example' => '.venv-mac/bin/python main.py --evidence-report',
                    'tone' => 'read',
                    'what' => 'Lists the shadow and counterfactual evidence streams that should be reviewed before changing behavior.',
                ],
                [
                    'command' => 'Threshold adviser',
                    'example' => '.venv-mac/bin/python main.py --threshold-advice',
                    'tone' => 'read',
                    'what' => 'Runs the recommendation-only GA adviser for the strategy suppress threshold.',
                ],
                [
                    'command' => 'Holding-window adviser',
                    'example' => '.venv-mac/bin/python main.py --holding-window-advice --strategy-id mean_reversion.snapback',
                    'tone' => 'read',
                    'what' => 'Compares holding-window policies for a strategy without changing runtime exits.',
                ],
                [
                    'command' => 'Paper exit review',
                    'example' => '.venv-mac/bin/python main.py --paper-exit-review --strategy-id mean_reversion.snapback',
                    'tone' => 'read',
                    'what' => 'Runs a post-mortem that compares actual paper exits with stored shadow checkpoints.',
                ],
                [
                    'command' => 'Strategy health',
                    'example' => '.venv-mac/bin/python main.py --strategy-health --strategy-id mean_reversion.snapback',
                    'tone' => 'read',
                    'what' => 'Bundles paper P/L, exit behavior, proposal flow, and signal visibility into one strategy-specific report.',
                ],
                [
                    'command' => 'Proposal pipeline diagnostics',
                    'example' => '.venv-mac/bin/python main.py --proposal-pipeline-diagnostics',
                    'tone' => 'read',
                    'what' => 'Explains where execution-allowed strategies are getting filtered out, including candidate counts, raw signals, stage rejections, and closest misses.',
                ],
                [
                    'command' => 'Slow queue process',
                    'example' => '.venv-mac/bin/python main.py --slow-enrichment-queue-process',
                    'tone' => 'maint',
                    'what' => 'Runs the advisory slow enrichment queue worker once until idle and reports processed, repaired, remaining, and terminal counts.',
                ],
                [
                    'command' => 'Slow queue repair',
                    'example' => '.venv-mac/bin/python main.py --slow-enrichment-queue-repair',
                    'tone' => 'maint',
                    'what' => 'Repairs expired or stale advisory slow queue rows so deferred candidate coverage can resume without raising the cap.',
                ],
                [
                    'command' => 'Crypto health',
                    'example' => '.venv-mac/bin/python main.py --crypto-health --days 2',
                    'tone' => 'read',
                    'what' => 'Shows recent crypto scan activity, bar-fetch visibility, and related overnight operator signals.',
                ],
                [
                    'command' => 'Overnight giveback',
                    'example' => '.venv-mac/bin/python main.py --overnight-giveback --days 7',
                    'tone' => 'read',
                    'what' => 'Reviews overnight paper giveback behavior over the selected lookback window.',
                ],
                [
                    'command' => 'Adapter inventory',
                    'example' => '.venv-mac/bin/python main.py --adapter-inventory',
                    'tone' => 'read',
                    'what' => 'Shows active, bridged, scaffold-only, disabled, and not-yet-implemented adapters.',
                ],
                [
                    'command' => 'Storage separation report',
                    'example' => '.venv-mac/bin/python main.py --storage-separation-report',
                    'tone' => 'read',
                    'what' => 'Audits the paper/live provenance and storage-boundary contract.',
                ],
                [
                    'command' => 'PostgreSQL preflight',
                    'example' => '.venv-mac/bin/python main.py --postgres-preflight',
                    'tone' => 'read',
                    'what' => 'Shows safe PostgreSQL runtime diagnostics, launchd wiring, backend selection, control-tick readability, and heartbeat snapshot write/read checks without printing secrets.',
                ],
            ],
        ],
        [
            'title' => 'Dashboard And Site',
            'description' => 'Commands for the operator surfaces rather than the control pipeline itself.',
            'items' => [
                [
                    'command' => 'Primary routed dashboard',
                    'example' => 'https://ghostfrog-centaur.ddev.site',
                    'tone' => 'info',
                    'what' => 'The main local Centaur web experience served through DDEV/OrbStack.',
                ],
                [
                    'command' => 'Live JSON snapshot proxy',
                    'example' => 'https://ghostfrog-centaur.ddev.site/snapshot/',
                    'tone' => 'info',
                    'what' => 'Read-only JSON view of the current dashboard snapshot payload.',
                ],
                [
                    'command' => 'Run Python dashboard API',
                    'example' => '.venv-mac/bin/python main.py --dashboard --host 0.0.0.0 --port 8788',
                    'tone' => 'run',
                    'what' => 'Starts the direct Python-served dashboard API/web surface that the routed site proxies.',
                ],
                [
                    'command' => 'Legacy desktop dashboard',
                    'example' => '.venv-mac/bin/python main.py --dashboard-desktop',
                    'tone' => 'run',
                    'what' => 'Opens the older local desktop monitor window.',
                ],
            ],
        ],
        [
            'title' => 'Research And Data Work',
            'description' => 'One-shot maintenance and replay commands for historical data, training outcomes, and internal accounting.',
            'items' => [
                [
                    'command' => 'Research cycle',
                    'example' => '.venv-mac/bin/python main.py --research-cycle',
                    'tone' => 'maint',
                    'what' => 'Runs one autonomous replay-only research cycle, stores research evidence, updates promotion recommendations, and does not enable broker paper or live execution.',
                ],
                [
                    'command' => 'Research status',
                    'example' => '.venv-mac/bin/python main.py --research-status',
                    'tone' => 'read',
                    'what' => 'Shows the latest persisted research-cycle decisions, replay windows, timeframes used/skipped, recommendations, blockers, and current approval state.',
                ],
                [
                    'command' => 'Real heartbeat research-cycle status',
                    'example' => '.venv-mac/bin/python main.py --research-cycle-status',
                    'tone' => 'read',
                    'what' => 'Shows the latest persisted real-heartbeat research cycle when one exists, or explains why none has been recorded yet with diagnostics such as whether autonomous learning was called, whether research was enabled, whether the cycle started/completed, the source tag, decision counts, candidate counts, alert counts, and any persistence failure.',
                ],
                [
                    'command' => 'Real heartbeat autonomous learning once',
                    'example' => '.venv-mac/bin/python main.py --heartbeat-autonomous-learning-once',
                    'tone' => 'maint',
                    'what' => 'Runs the same autonomous-learning path used by the real control heartbeat once, records it with source=real_heartbeat, and leaves broker paper/live safety unchanged. Use this when tracing why the live heartbeat is not recording a usable research cycle.',
                ],
                [
                    'command' => 'Research proof vs real',
                    'example' => '.venv-mac/bin/python main.py --research-proof-vs-real',
                    'tone' => 'read',
                    'what' => 'Compares the synthetic autopilot proof harness with the latest persisted real-heartbeat research cycle, including inputs, strategies evaluated, historical windows, replay evidence, paper-sim evidence, usable decisions, candidate counts, removal candidate counts, gates, thresholds, and the recorded reasons the real runtime produced fewer or no candidates.',
                ],
                [
                    'command' => 'Historical backfill',
                    'example' => '.venv-mac/bin/python main.py --backfill --days 5 --timeframe 1Min --equity-symbols AAPL,MSFT',
                    'tone' => 'maint',
                    'what' => 'Fetches historical bars for the requested lookback, timeframe, and symbols.',
                ],
                [
                    'command' => 'Historical replay',
                    'example' => '.venv-mac/bin/python main.py --replay --days 5 --timeframe 1Min --max-replay-timestamps 500',
                    'tone' => 'maint',
                    'what' => 'Runs stored historical bars through the replay pipeline to generate replay evidence. Replay/backtest evidence does not affect paper/live allocation fitness unless the explicit INCLUDE_BACKTEST_EVIDENCE_* fitness switches are enabled.',
                ],
                [
                    'command' => 'Historical bars status',
                    'example' => '.venv-mac/bin/python main.py --historical-bars-status --days 1 --timeframe 1Min',
                    'tone' => 'read',
                    'what' => 'Checks whether the historical bars store actually has replay-ready rows for the requested window and timeframe, and shows historical-vs-latest storage counts, source labels, timeframe labels, timestamp coverage, newest bar age, and replay readiness blockers.',
                ],
                [
                    'command' => 'Replay a fixed window',
                    'example' => '.venv-mac/bin/python main.py --replay --replay-start-at 2026-06-01T00:00:00Z --replay-end-at 2026-06-03T23:59:59Z',
                    'tone' => 'maint',
                    'what' => 'Replays a specific time range instead of a simple day-count window.',
                ],
                [
                    'command' => 'Replay dry run',
                    'example' => '.venv-mac/bin/python main.py --replay --days 5 --timeframe 1Min --max-replay-timestamps 500 --dry-run',
                    'tone' => 'read',
                    'what' => 'Processes replay timestamps and prints replay diagnostics without writing replay proposals, replay outcomes, fitness snapshots, or the replay tick record. Use this first when checking coverage, blockers, and future-data gaps.',
                ],
                [
                    'command' => 'Replay summary by run id',
                    'example' => '.venv-mac/bin/python main.py --replay-summary --replay-run-id replayrun-20260606-120000-123456',
                    'tone' => 'read',
                    'what' => 'Shows the persisted summary for one replay_run_id, including timestamps processed, candidates evaluated, signals generated, research signals generated, outcomes recorded, checkpoint win/return stats, and top blockers by strategy.',
                ],
                [
                    'command' => 'Replay comparison across windows',
                    'example' => '.venv-mac/bin/python main.py --replay-comparison --replay-limit 5',
                    'tone' => 'read',
                    'what' => 'Compares multiple persisted historical replay windows for the research-only crypto pullback regimes, including replay_run_id, date range, timeframe, proposals, outcomes, 15m/1h/1d/7d checkpoint metrics, best/worst symbols, and sample-size warnings.',
                ],
                [
                    'command' => 'Backfill API cost rollups',
                    'example' => '.venv-mac/bin/python main.py --backfill-api-costs',
                    'tone' => 'maint',
                    'what' => 'Reprices stored API usage events from current pricing assumptions and rebuilds cost rollups.',
                ],
            ],
        ],
        [
            'title' => 'Promotion And Alerts',
            'description' => 'Operator commands for reviewing research and paper-sim evidence, handling manual paper approvals, and resolving repeating attention alerts.',
            'items' => [
                [
                    'command' => 'Promotion status',
                    'example' => '.venv-mac/bin/python main.py --promotion-status',
                    'tone' => 'read',
                    'what' => 'Shows persisted strategy promotion stages, evidence summaries, blocker reasons, and any current manual paper approvals.',
                ],
                [
                    'command' => 'Promotion evaluate',
                    'example' => '.venv-mac/bin/python main.py --promotion-evaluate --strategy-id mean_reversion.snapback --profile-id snapback',
                    'tone' => 'read',
                    'what' => 'Reviews replay and paper-sim evidence for one strategy/profile without auto-approving broker paper execution.',
                ],
                [
                    'command' => 'Approve broker paper',
                    'example' => '.venv-mac/bin/python main.py --promotion-approve-paper --strategy-id mean_reversion.snapback --profile-id snapback --max-paper-notional 10 --max-open-trades 1 --cooldown-minutes 60 --confirm-promotion-approval',
                    'tone' => 'warn',
                    'what' => 'Manually approves one exact strategy/profile for broker paper execution with explicit risk caps. This is never automatic.',
                ],
                [
                    'command' => 'Reject promotion',
                    'example' => '.venv-mac/bin/python main.py --promotion-reject --strategy-id mean_reversion.snapback --profile-id snapback --reason "manual review rejected"',
                    'tone' => 'warn',
                    'what' => 'Records an auditable rejection for a strategy/profile and resolves the related approval request alert.',
                ],
                [
                    'command' => 'Acknowledge attention alert',
                    'example' => '.venv-mac/bin/python main.py --alert-ack --event-id paper_candidate|mean_reversion.snapback|snapback',
                    'tone' => 'warn',
                    'what' => 'Acknowledges an open attention alert and stops its repeat reminder loop without approving anything.',
                ],
                [
                    'command' => 'Resolve attention alert',
                    'example' => '.venv-mac/bin/python main.py --alert-resolve --event-id paper_candidate|mean_reversion.snapback|snapback --reason "review complete"',
                    'tone' => 'warn',
                    'what' => 'Marks an attention alert resolved with an auditable reason and stops further Slack reminders for that issue.',
                ],
            ],
        ],
        [
            'title' => 'Trading 212 Helpers',
            'description' => 'Specialized support commands for the Trading 212 paper lane. Read these carefully before using the mutating seed flow.',
            'items' => [
                [
                    'command' => 'Instrument readiness report',
                    'example' => '.venv-mac/bin/python main.py --trading212-instruments',
                    'tone' => 'read',
                    'what' => 'Fetches Trading 212 instrument metadata and reports UK ticker readiness.',
                ],
                [
                    'command' => 'Seed price discovery dry run',
                    'example' => '.venv-mac/bin/python main.py --trading212-seed-prices --equity-symbols VOD,SHEL',
                    'tone' => 'warn',
                    'what' => 'Previews tiny Trading 212 paper seed orders for price discovery without actually submitting them.',
                ],
                [
                    'command' => 'Seed price discovery submit',
                    'example' => '.venv-mac/bin/python main.py --trading212-seed-prices --confirm-trading212-paper-seed --equity-symbols VOD,SHEL --trading212-seed-quantity 0.01',
                    'tone' => 'danger',
                    'what' => 'Actually submits capped tiny Trading 212 paper seed market orders for the chosen symbols.',
                ],
            ],
        ],
    ];
}

$groups = commandGroups();
$commandRows = [];
foreach ($groups as $group) {
    foreach (($group['items'] ?? []) as $item) {
        $commandRows[] = [
            'category' => (string) ($group['title'] ?? 'Commands'),
            'name' => (string) ($item['command'] ?? ''),
            'command' => (string) ($item['example'] ?? ''),
            'description' => (string) ($item['what'] ?? ''),
            'tone' => (string) ($item['tone'] ?? 'read'),
        ];
    }
}
$toneOrder = [
    'info' => 10,
    'read' => 20,
    'ops' => 30,
    'run' => 40,
    'maint' => 50,
    'warn' => 60,
    'danger' => 70,
];
usort(
    $commandRows,
    static function (array $left, array $right) use ($toneOrder): int {
        $leftTone = (string) ($left['tone'] ?? 'read');
        $rightTone = (string) ($right['tone'] ?? 'read');
        $leftRank = $toneOrder[$leftTone] ?? 999;
        $rightRank = $toneOrder[$rightTone] ?? 999;
        if ($leftRank !== $rightRank) {
            return $leftRank <=> $rightRank;
        }
        $leftCategory = (string) ($left['category'] ?? '');
        $rightCategory = (string) ($right['category'] ?? '');
        $categoryCompare = strcasecmp($leftCategory, $rightCategory);
        if ($categoryCompare !== 0) {
            return $categoryCompare;
        }
        return strcasecmp((string) ($left['name'] ?? ''), (string) ($right['name'] ?? ''));
    }
);
$toneLabels = [
    'info' => 'Open',
    'read' => 'Read-only',
    'run' => 'Runs Centaur',
    'ops' => 'Ops helper',
    'maint' => 'Maintenance',
    'warn' => 'Use carefully',
    'danger' => 'Mutates paper account',
];
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Centaur Commands</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f3f4ee;
      --bg-accent: radial-gradient(circle at top left, rgba(15, 139, 141, 0.12), transparent 32%), linear-gradient(180deg, #fbfcf7 0%, #eef2ea 100%);
      --surface: rgba(255, 255, 255, 0.92);
      --surface-strong: #ffffff;
      --ink: #182126;
      --muted: #607075;
      --line: #d8e0d9;
      --teal: #0f8b8d;
      --teal-dark: #0a6468;
      --olive: #728661;
      --gold: #b98719;
      --amber: #b66518;
      --red: #b04d3c;
      --shadow: 0 22px 54px rgba(24, 33, 38, 0.08);
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      background: var(--bg-accent);
      color: var(--ink);
      font-family: "Avenir Next", Avenir, "Segoe UI", sans-serif;
    }

    .shell {
      width: min(1280px, calc(100% - 28px));
      margin: 0 auto;
      padding: 24px 0 40px;
    }

    .hero {
      display: grid;
      gap: 18px;
      align-items: start;
      margin-bottom: 22px;
    }

    .hero-card,
    .summary,
    .group,
    .command-card {
      border: 1px solid var(--line);
      border-radius: 24px;
      background: var(--surface);
      box-shadow: var(--shadow);
    }

    .hero-card {
      padding: 26px 24px 22px;
      overflow: hidden;
      position: relative;
    }

    .hero-card::after {
      content: "";
      position: absolute;
      inset: auto -60px -80px auto;
      width: 220px;
      height: 220px;
      border-radius: 999px;
      background: radial-gradient(circle, rgba(15, 139, 141, 0.16), transparent 68%);
      pointer-events: none;
    }

    .toolbar {
      display: flex;
      justify-content: flex-end;
      margin-bottom: 18px;
    }

    .eyebrow {
      margin: 0 0 8px;
      color: var(--teal-dark);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    h1 {
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(34px, 6vw, 58px);
      line-height: 0.95;
      letter-spacing: -0.03em;
    }

    .lede {
      max-width: 880px;
      margin: 14px 0 0;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.62;
    }

    .summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      padding: 16px;
      margin-bottom: 22px;
    }

    .summary-block {
      padding: 14px 16px;
      border-radius: 18px;
      background: rgba(238, 245, 241, 0.82);
    }

    .summary-label {
      display: block;
      margin-bottom: 6px;
      color: var(--teal-dark);
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .summary-value {
      font-size: 14px;
      line-height: 1.5;
      color: var(--ink);
    }

    .table-wrap {
      border: 1px solid var(--line);
      border-radius: 24px;
      background: var(--surface);
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .table-scroll {
      overflow-x: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 980px;
    }

    thead th {
      text-align: left;
      padding: 14px 16px;
      background: #edf7f6;
      color: var(--teal-dark);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
    }

    tbody td {
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
      background: rgba(255, 255, 255, 0.88);
    }

    tbody tr:last-child td {
      border-bottom: none;
    }

    tbody tr:nth-child(even) td {
      background: rgba(244, 248, 244, 0.92);
    }

    .col-name {
      min-width: 180px;
      font-weight: 700;
    }

    .col-category {
      min-width: 150px;
      color: var(--muted);
    }

    .col-command {
      min-width: 300px;
    }

    .col-description {
      min-width: 340px;
      color: var(--muted);
      line-height: 1.58;
    }

    .inline-code {
      display: inline-block;
      padding: 8px 10px;
      border-radius: 12px;
      background: #182126;
      color: #f8fbf9;
      white-space: pre-wrap;
      word-break: break-word;
      line-height: 1.5;
      font-size: 13px;
    }

    .tag {
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      border-radius: 999px;
      padding: 0 10px;
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.04em;
      text-transform: uppercase;
      white-space: nowrap;
    }

    .tag.info,
    .tag.read,
    .tag.ops {
      background: #edf7f6;
      color: var(--teal-dark);
    }

    .tag.run,
    .tag.maint {
      background: #f2f5ea;
      color: #5a6e49;
    }

    .tag.warn {
      background: #fff5e8;
      color: var(--amber);
    }

    .tag.danger {
      background: #fff0ed;
      color: var(--red);
    }

    code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    }

    .footer-note {
      margin-top: 20px;
      border-left: 4px solid var(--gold);
      border-radius: 14px;
      padding: 14px 16px;
      background: #fff8e7;
      color: #6a5217;
      line-height: 1.58;
    }

    @media (max-width: 720px) {
      .shell {
        width: min(100%, calc(100% - 18px));
      }

      .hero-card,
      .table-wrap {
        padding-left: 16px;
        padding-right: 16px;
      }

      .summary {
        padding: 12px;
      }
    }
  </style>
</head>
<body>
  <main class="shell">
    <div class="toolbar centaur-menu-toolbar">
      <?php centaurRenderNavigation('/commands.php'); ?>
    </div>

    <section class="hero">
      <article class="hero-card">
        <p class="eyebrow">Project Centaur</p>
        <h1>Commands You Can Run</h1>
        <p class="lede">A simple operator table for Centaur’s main commands. Every row shows the command name, the exact command to run, and what it does, without splitting the page into lots of separate sections.</p>
      </article>
    </section>

    <section class="summary" aria-label="Command guide summary">
      <div class="summary-block">
        <span class="summary-label">Open The Site</span>
        <div class="summary-value"><a href="https://ghostfrog-centaur.ddev.site">ghostfrog-centaur.ddev.site</a></div>
      </div>
      <div class="summary-block">
        <span class="summary-label">Quick Health Check</span>
        <div class="summary-value"><code>.venv-mac/bin/python main.py --status</code></div>
      </div>
      <div class="summary-block">
        <span class="summary-label">Read First Before Changing Behavior</span>
        <div class="summary-value"><code>.venv-mac/bin/python main.py --evidence-report</code></div>
      </div>
      <div class="summary-block">
        <span class="summary-label">Why No Proposals?</span>
        <div class="summary-value"><code>.venv-mac/bin/python main.py --proposal-pipeline-diagnostics</code></div>
      </div>
      <div class="summary-block">
        <span class="summary-label">Safe Replay First</span>
        <div class="summary-value"><code>.venv-mac/bin/python main.py --replay --days 5 --timeframe 1Min --dry-run</code></div>
      </div>
      <div class="summary-block">
        <span class="summary-label">Main Safety Split</span>
        <div class="summary-value">Read-only reports are safe to inspect. Runtime, maintenance, and paper-seed commands can change state or do real work.</div>
      </div>
    </section>

    <section class="table-wrap" aria-label="Centaur command table">
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Command</th>
              <th>Description</th>
              <th>Category</th>
              <th>Type</th>
            </tr>
          </thead>
          <tbody>
            <?php foreach ($commandRows as $row): ?>
              <?php $tone = (string) $row['tone']; ?>
              <tr>
                <td class="col-name"><?= commandsEscape((string) $row['name']) ?></td>
                <td class="col-command"><span class="inline-code"><code><?= commandsEscape((string) $row['command']) ?></code></span></td>
                <td class="col-description"><?= commandsEscape((string) $row['description']) ?></td>
                <td class="col-category"><?= commandsEscape((string) $row['category']) ?></td>
                <td><span class="tag <?= commandsEscape($tone) ?>"><?= commandsEscape($toneLabels[$tone] ?? 'Command') ?></span></td>
              </tr>
            <?php endforeach; ?>
          </tbody>
        </table>
      </div>
    </section>

    <aside class="footer-note">
      Command examples here reflect the current Centaur operator surfaces in this repo: the routed DDEV site, the `main.py` CLI, the `scripts/centaur-agent.sh` helper, and the Trading 212 support commands. For replay work, start with <code>--replay --dry-run</code>, then use the printed <code>replay_run_id</code> with <code>--replay-summary --replay-run-id ...</code> after a persisted run. Replay/backtest evidence stays out of paper/live allocation fitness by default unless <code>INCLUDE_BACKTEST_EVIDENCE_IN_PAPER_FITNESS=true</code> or <code>INCLUDE_BACKTEST_EVIDENCE_IN_LIVE_FITNESS=true</code> is explicitly enabled.
    </aside>
  </main>
</body>
</html>

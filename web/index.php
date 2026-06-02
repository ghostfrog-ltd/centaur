<?php
declare(strict_types=1);

header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');

require __DIR__ . '/api/snapshot_cache.php';

$initialSnapshotJson = initialSnapshotJson();

function initialSnapshotJson(): string
{
    $result = centaurResolveSnapshotPayload(preferCached: true);
    if (($result['ok'] ?? false) !== true) {
        return 'null';
    }

    $decoded = $result['decoded'] ?? null;
    if (!is_array($decoded)) {
        return 'null';
    }
    return json_encode($decoded, JSON_UNESCAPED_SLASHES) ?: 'null';
}
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Centaur Slot Compounding</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f7f5;
      --surface: #ffffff;
      --surface-2: #eef5f1;
      --ink: #172022;
      --muted: #657174;
      --line: #d7e1dc;
      --teal: #0f8b8d;
      --teal-dark: #096669;
      --gold: #c98f13;
      --blue: #3867d6;
      --rose: #c94b5f;
      --green: #258b57;
      --shadow: 0 16px 40px rgba(18, 31, 32, 0.08);
    }

    * {
      box-sizing: border-box;
    }

    [hidden] {
      display: none !important;
    }

    body {
      margin: 0;
      background:
        linear-gradient(180deg, rgba(15, 139, 141, 0.08), rgba(244, 247, 245, 0) 34rem),
        var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    button,
    input,
    select {
      font: inherit;
    }

    .shell {
      width: min(1460px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0 32px;
    }

    .topbar {
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 18px;
    }

    .eyebrow {
      margin: 0 0 7px;
      color: var(--teal-dark);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    h1 {
      margin: 0;
      font-size: clamp(28px, 3vw, 44px);
      line-height: 1.02;
      letter-spacing: 0;
    }

    .toolbar {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 10px;
    }

    .button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 40px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      color: var(--ink);
      cursor: pointer;
      font-weight: 750;
      padding: 0 14px;
      box-shadow: 0 6px 18px rgba(18, 31, 32, 0.05);
      text-decoration: none;
    }

    .button:hover {
      border-color: rgba(15, 139, 141, 0.45);
    }

    .button.primary {
      background: var(--teal);
      border-color: var(--teal);
      color: white;
    }

    .grid {
      display: grid;
      grid-template-columns: minmax(320px, 0.82fr) minmax(0, 1.58fr);
      gap: 18px;
      align-items: start;
    }

    .panel {
      background: rgba(255, 255, 255, 0.9);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
      min-height: 56px;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.76);
    }

    .panel-title {
      font-size: 15px;
      font-weight: 850;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      border-radius: 999px;
      padding: 4px 10px;
      background: var(--surface-2);
      color: var(--teal-dark);
      font-size: 12px;
      font-weight: 800;
      white-space: nowrap;
    }

    .badge-row {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
    }

    .controls {
      display: grid;
      gap: 16px;
      padding: 16px;
    }

    .control {
      display: grid;
      gap: 8px;
    }

    .control-top {
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: baseline;
    }

    label {
      color: var(--muted);
      font-size: 13px;
      font-weight: 750;
    }

    .readout {
      color: var(--ink);
      font-size: 13px;
      font-weight: 850;
      white-space: nowrap;
    }

    input[type="range"] {
      width: 100%;
      accent-color: var(--teal);
    }

    .number-row {
      display: grid;
      grid-template-columns: 1fr 86px;
      gap: 10px;
      align-items: center;
    }

    input[type="number"],
    select {
      width: 100%;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: white;
      color: var(--ink);
      padding: 7px 10px;
      text-align: right;
      font-weight: 750;
    }

    select {
      text-align: left;
    }

    .segmented {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 4px;
      padding: 4px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface-2);
    }

    .segment {
      min-height: 34px;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      font-weight: 850;
    }

    .segment.active {
      background: var(--surface);
      color: var(--teal-dark);
      box-shadow: 0 4px 14px rgba(18, 31, 32, 0.08);
    }

    .main {
      display: grid;
      gap: 18px;
      min-width: 0;
    }

    .stats {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }

    .stat {
      min-height: 112px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      box-shadow: 0 8px 22px rgba(18, 31, 32, 0.05);
      min-width: 0;
    }

    .stat-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    .stat-value {
      margin-top: 12px;
      font-size: clamp(22px, 2.25vw, 34px);
      font-weight: 900;
      line-height: 1;
      overflow-wrap: anywhere;
    }

    .stat-detail {
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }

    .chart-wrap {
      padding: 12px 14px 16px;
      min-width: 0;
    }

    canvas {
      width: 100%;
      aspect-ratio: 16 / 8.5;
      display: block;
      border-radius: 8px;
      background: linear-gradient(180deg, #ffffff, #f7faf8);
      border: 1px solid var(--line);
    }

    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 12px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 750;
    }

    .key {
      display: inline-flex;
      align-items: center;
      gap: 7px;
    }

    .swatch {
      width: 18px;
      height: 4px;
      border-radius: 999px;
      background: var(--teal);
    }

    .swatch.gold {
      background: var(--gold);
    }

    .swatch.blue {
      background: var(--blue);
    }

    .details {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 18px;
    }

    .wide {
      grid-column: 1 / -1;
    }

    .tabs {
      display: grid;
      gap: 14px;
    }

    .tab-list {
      display: inline-grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 4px;
      width: min(480px, 100%);
      padding: 4px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(238, 245, 241, 0.92);
    }

    .tab-button {
      min-height: 40px;
      border: 0;
      border-radius: 6px;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      font-weight: 900;
      padding: 0 14px;
    }

    .tab-button.active {
      background: var(--surface);
      color: var(--teal-dark);
      box-shadow: 0 4px 14px rgba(18, 31, 32, 0.08);
    }

    .tab-page {
      display: grid;
      gap: 18px;
    }

    .table-wrap {
      max-height: 392px;
      overflow: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
    }

    th,
    td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: right;
      font-size: 13px;
      white-space: nowrap;
    }

    th {
      position: sticky;
      top: 0;
      background: #f8fbf9;
      color: var(--muted);
      font-size: 11px;
      font-weight: 850;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      z-index: 1;
    }

    th:first-child,
    td:first-child {
      text-align: left;
    }

    .meter-list {
      display: grid;
      gap: 12px;
      padding: 16px;
    }

    .meter-row {
      display: grid;
      gap: 8px;
    }

    .meter-top {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 750;
    }

    .meter-value {
      color: var(--ink);
      font-weight: 900;
    }

    .meter {
      height: 12px;
      border-radius: 999px;
      background: var(--surface-2);
      overflow: hidden;
      border: 1px solid var(--line);
    }

    .meter-fill {
      height: 100%;
      width: 0;
      background: linear-gradient(90deg, var(--teal), var(--green));
      border-radius: inherit;
    }

    .meter-fill.gold {
      background: linear-gradient(90deg, var(--gold), #e0b540);
    }

    .meter-fill.blue {
      background: linear-gradient(90deg, var(--blue), #6c8ff0);
    }

    .note {
      margin: 0;
      padding: 12px 16px 16px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      border-top: 1px solid var(--line);
      background: rgba(238, 245, 241, 0.52);
    }

    @media (max-width: 1120px) {
      .grid,
      .details {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 1280px) {
      .stats {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
    }

    @media (max-width: 680px) {
      .shell {
        width: min(100% - 24px, 1460px);
        padding-top: 16px;
      }

      .topbar {
        align-items: stretch;
        flex-direction: column;
      }

      .toolbar {
        justify-content: stretch;
      }

      .button {
        flex: 1 1 auto;
      }

      .stats {
        grid-template-columns: 1fr;
      }

      canvas {
        aspect-ratio: 1 / 0.92;
      }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">Project Centaur</p>
        <h1>Slot Compounding</h1>
      </div>
      <div class="toolbar">
        <button id="preset-current" class="button primary" type="button">Current Envelope</button>
        <button id="preset-fast" class="button" type="button">Faster Test</button>
        <button id="reset" class="button" type="button">Reset</button>
        <a class="button" href="/reports/50-dollar-day-plan.md" download>Download Plan</a>
        <a class="button" href="/flow.php">Flow Map</a>
        <a class="button" href="/glossary.php">Glossary</a>
        <a class="button" href="/dashboard.php">Dashboard</a>
      </div>
    </header>

    <section class="grid">
      <aside class="panel" aria-label="Model controls">
        <div class="panel-head">
          <div class="panel-title">Inputs</div>
          <div class="badge-row">
            <span id="source-badge" class="badge">Current envelope</span>
            <span id="input-badge" class="badge">$10 slots</span>
          </div>
        </div>
        <div class="controls">
          <div class="control">
            <div class="control-top">
              <label for="base-slots">Base Slots</label>
              <span id="base-slots-readout" class="readout">10</span>
            </div>
            <div class="number-row">
              <input id="base-slots" type="range" min="1" max="500" step="1" value="10">
              <input id="base-slots-number" type="number" min="1" max="500" step="1" value="10">
            </div>
          </div>

          <div class="control">
            <div class="control-top">
              <label for="slot-size">Per Slot Contains</label>
              <span id="slot-size-readout" class="readout">$10.00</span>
            </div>
            <div class="number-row">
              <input id="slot-size" type="range" min="1" max="100" step="1" value="10">
              <input id="slot-size-number" type="number" min="1" max="10000" step="1" value="10">
            </div>
          </div>

          <div class="control">
            <div class="control-top">
              <label>Per Slot Back Mode</label>
              <span id="back-mode-readout" class="readout">Percent</span>
            </div>
            <div class="segmented" role="group" aria-label="Per slot back mode">
              <button id="mode-percent" class="segment active" type="button">Percent</button>
              <button id="mode-dollars" class="segment" type="button">Dollars</button>
            </div>
          </div>

          <div class="control" id="return-percent-control">
            <div class="control-top">
              <label for="return-percent">Avg Win Per Winning Slot</label>
              <span id="return-percent-readout" class="readout">0%</span>
            </div>
            <div class="number-row">
              <input id="return-percent" type="range" min="-5" max="12" step="0.01" value="0">
              <input id="return-percent-number" type="number" min="-100" max="100" step="0.01" value="0">
            </div>
          </div>

          <div class="control" id="return-dollars-control" hidden>
            <div class="control-top">
              <label for="return-dollars">Avg Win Per Winning Slot</label>
              <span id="return-dollars-readout" class="readout">$0.00</span>
            </div>
            <div class="number-row">
              <input id="return-dollars" type="range" min="-5" max="5" step="0.01" value="0">
              <input id="return-dollars-number" type="number" min="-10000" max="10000" step="0.01" value="0">
            </div>
          </div>

          <div class="control">
            <div class="control-top">
              <label for="win-rate">Win Rate Assumption</label>
              <span id="win-rate-readout" class="readout">100%</span>
            </div>
            <div class="number-row">
              <input id="win-rate" type="range" min="0" max="100" step="1" value="100">
              <input id="win-rate-number" type="number" min="0" max="100" step="1" value="100">
            </div>
          </div>

          <div class="control">
            <div class="control-top">
              <label for="loss-percent">Avg Loss Per Losing Slot</label>
              <span id="loss-percent-readout" class="readout">0%</span>
            </div>
            <div class="number-row">
              <input id="loss-percent" type="range" min="0" max="12" step="0.05" value="0">
              <input id="loss-percent-number" type="number" min="0" max="100" step="0.05" value="0">
            </div>
          </div>

          <div class="control">
            <div class="control-top">
              <label for="slot-fill">Slots Used Per Cycle</label>
              <span id="slot-fill-readout" class="readout">100%</span>
            </div>
            <div class="number-row">
              <input id="slot-fill" type="range" min="1" max="100" step="1" value="100">
              <input id="slot-fill-number" type="number" min="1" max="100" step="1" value="100">
            </div>
          </div>

          <div class="control">
            <div class="control-top">
              <label for="starting-profit">Starting Snapshot P/L</label>
              <span id="starting-profit-readout" class="readout">$0.00</span>
            </div>
            <div class="number-row">
              <input id="starting-profit" type="range" min="-100" max="250" step="1" value="0">
              <input id="starting-profit-number" type="number" min="-100000" max="100000" step="1" value="0">
            </div>
          </div>

          <div class="control">
            <div class="control-top">
              <label for="cycles">Modeled Active Days</label>
              <span id="cycles-readout" class="readout">365</span>
            </div>
            <div class="number-row">
              <input id="cycles" type="range" min="1" max="1000" step="1" value="365">
              <input id="cycles-number" type="number" min="1" max="1000" step="1" value="365">
            </div>
          </div>

          <div class="control">
            <div class="control-top">
              <label for="cycles-per-day">Cycles Per Active Day</label>
              <span id="cycles-per-day-readout" class="readout">1</span>
            </div>
            <div class="number-row">
              <input id="cycles-per-day" type="range" min="1" max="48" step="1" value="1">
              <input id="cycles-per-day-number" type="number" min="1" max="48" step="1" value="1">
            </div>
          </div>
        </div>
        <p class="note">Read-only projection. When the live follower is enabled, dashboard defaults use the live account and live closed-fill outcomes. Slots used per cycle and cycles per active day are derived from observed closed-trade throughput when available, not current open-position occupancy. Cycles per active day models faster slot turnover by multiplying the active-day horizon into closed-trade cycles. Paper values are used only when live is not active or no live account snapshot is available. Account-level P/L can include open red positions. Browser refreshes load the latest dashboard API payload. Calendar holidays and closed equity sessions are not automatically modeled; the active-day count is editable.</p>
      </aside>

      <section class="main">
        <div class="stats" aria-label="Simulation summary">
          <article class="stat">
            <div class="stat-label">Projected Profit</div>
            <div id="stat-profit" class="stat-value">$0.00</div>
            <div id="stat-profit-detail" class="stat-detail">0 cycles</div>
          </article>
          <article class="stat">
            <div class="stat-label">Projected Slots</div>
            <div id="stat-slots" class="stat-value">0</div>
            <div id="stat-slots-detail" class="stat-detail">0 earned</div>
          </article>
          <article class="stat">
            <div class="stat-label">Slot Capacity</div>
            <div id="stat-capacity" class="stat-value">$0.00</div>
            <div id="stat-capacity-detail" class="stat-detail">0 x $0</div>
          </article>
          <article class="stat">
            <div class="stat-label">Next Slot Needs</div>
            <div id="stat-next" class="stat-value">$0.00</div>
            <div id="stat-next-detail" class="stat-detail">remaining</div>
          </article>
        </div>

        <section class="tabs">
          <div class="tab-list" role="tablist" aria-label="Compounding views">
            <button id="tab-graph-button" class="tab-button active" type="button" role="tab" aria-controls="tab-graph" aria-selected="true">Graph</button>
            <button id="tab-slices-button" class="tab-button" type="button" role="tab" aria-controls="tab-slices" aria-selected="false">30 Active-Day Slices</button>
          </div>

          <section id="tab-graph" class="tab-page" role="tabpanel" aria-labelledby="tab-graph-button">
            <section class="panel" aria-label="Compounding chart">
              <div class="panel-head">
                <div class="panel-title">Curve</div>
                <span id="chart-badge" class="badge">120 cycles</span>
              </div>
              <div class="chart-wrap">
                <canvas id="chart" aria-label="Profit, slot count, and slot capacity over time"></canvas>
                <div class="legend">
                  <span class="key"><span class="swatch"></span>Tracked P/L</span>
                  <span class="key"><span class="swatch gold"></span>Effective Slots</span>
                  <span class="key"><span class="swatch blue"></span>Slot Capacity</span>
                </div>
              </div>
            </section>

            <section class="details">
              <section class="panel">
                <div class="panel-head">
                  <div class="panel-title">Milestones</div>
                  <span id="milestone-badge" class="badge">0 earned</span>
                </div>
                <div class="meter-list" id="meters"></div>
              </section>

              <section class="panel">
                <div class="panel-head">
                  <div class="panel-title">Sampled Timeline</div>
                  <span id="table-badge" class="badge">12 rows</span>
                </div>
                <div class="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Cycle</th>
                        <th>Profit</th>
                        <th>Earned</th>
                        <th>Slots</th>
                        <th>Capacity</th>
                        <th>Net Cycle</th>
                      </tr>
                    </thead>
                    <tbody id="timeline-body"></tbody>
                  </table>
                </div>
              </section>
            </section>
          </section>

          <section id="tab-slices" class="tab-page" role="tabpanel" aria-labelledby="tab-slices-button" hidden>
            <section class="panel">
              <div class="panel-head">
                <div class="panel-title">30 Active-Day Slices</div>
                <span id="slice-badge" class="badge">1 model year</span>
              </div>
              <div class="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Active Days</th>
                      <th>#</th>
                      <th>Slice Earned</th>
                      <th>Avg / Day</th>
                      <th>Ending Profit</th>
                      <th>Earned Slots</th>
                      <th>Total Slots</th>
                      <th>Capacity</th>
                    </tr>
                  </thead>
                  <tbody id="slice-body"></tbody>
                </table>
              </div>
            </section>
          </section>
        </section>
      </section>
    </section>
  </main>

  <script>
    const embeddedSnapshot = <?php echo $initialSnapshotJson; ?>;

    const currentEnvelope = {
      baseSlots: 10,
      slotSize: 10,
      profitCapturePct: 1.25,
      activeDaysPerYear: 252,
      maxOrdersPerTick: 1,
      dailyDrawdownUsd: 5
    };

    const defaults = {
      baseSlots: currentEnvelope.baseSlots,
      slotSize: currentEnvelope.slotSize,
      backMode: "percent",
      returnPercent: 0,
      returnDollars: 0,
      winRate: 100,
      lossPercent: 0,
      slotFill: 100,
      startingProfit: 0,
      cycles: currentEnvelope.activeDaysPerYear,
      cyclesPerDay: 1
    };

    const fastPreset = {
      baseSlots: 10,
      slotSize: 10,
      backMode: "percent",
      returnPercent: 2.5,
      returnDollars: 0.25,
      winRate: 100,
      lossPercent: 0,
      slotFill: 100,
      startingProfit: 0,
      cycles: 240,
      cyclesPerDay: 12
    };

    const fields = {
      baseSlots: bindNumber("base-slots"),
      slotSize: bindNumber("slot-size"),
      returnPercent: bindNumber("return-percent"),
      returnDollars: bindNumber("return-dollars"),
      winRate: bindNumber("win-rate"),
      lossPercent: bindNumber("loss-percent"),
      slotFill: bindNumber("slot-fill"),
      startingProfit: bindNumber("starting-profit"),
      cycles: bindNumber("cycles"),
      cyclesPerDay: bindNumber("cycles-per-day")
    };

    const nodes = {
      sourceBadge: document.getElementById("source-badge"),
      inputBadge: document.getElementById("input-badge"),
      baseSlotsReadout: document.getElementById("base-slots-readout"),
      slotSizeReadout: document.getElementById("slot-size-readout"),
      backModeReadout: document.getElementById("back-mode-readout"),
      returnPercentReadout: document.getElementById("return-percent-readout"),
      returnDollarsReadout: document.getElementById("return-dollars-readout"),
      winRateReadout: document.getElementById("win-rate-readout"),
      lossPercentReadout: document.getElementById("loss-percent-readout"),
      slotFillReadout: document.getElementById("slot-fill-readout"),
      startingProfitReadout: document.getElementById("starting-profit-readout"),
      cyclesReadout: document.getElementById("cycles-readout"),
      cyclesPerDayReadout: document.getElementById("cycles-per-day-readout"),
      returnPercentControl: document.getElementById("return-percent-control"),
      returnDollarsControl: document.getElementById("return-dollars-control"),
      modePercent: document.getElementById("mode-percent"),
      modeDollars: document.getElementById("mode-dollars"),
      tabGraphButton: document.getElementById("tab-graph-button"),
      tabSlicesButton: document.getElementById("tab-slices-button"),
      tabGraph: document.getElementById("tab-graph"),
      tabSlices: document.getElementById("tab-slices"),
      statProfit: document.getElementById("stat-profit"),
      statProfitDetail: document.getElementById("stat-profit-detail"),
      statSlots: document.getElementById("stat-slots"),
      statSlotsDetail: document.getElementById("stat-slots-detail"),
      statCapacity: document.getElementById("stat-capacity"),
      statCapacityDetail: document.getElementById("stat-capacity-detail"),
      statNext: document.getElementById("stat-next"),
      statNextDetail: document.getElementById("stat-next-detail"),
      chartBadge: document.getElementById("chart-badge"),
      milestoneBadge: document.getElementById("milestone-badge"),
      sliceBadge: document.getElementById("slice-badge"),
      tableBadge: document.getElementById("table-badge"),
      meters: document.getElementById("meters"),
      sliceBody: document.getElementById("slice-body"),
      timelineBody: document.getElementById("timeline-body"),
      chart: document.getElementById("chart")
    };

    let backMode = defaults.backMode;
    let currentDefaultSource = "Current envelope";
    let latestRows = [];

    function bindNumber(id) {
      return {
        range: document.getElementById(id),
        number: document.getElementById(`${id}-number`)
      };
    }

    function clamp(value, min, max) {
      const number = Number(value);
      if (!Number.isFinite(number)) return min;
      return Math.min(max, Math.max(min, number));
    }

    function valueOf(fieldName) {
      return Number(fields[fieldName].number.value);
    }

    function setField(fieldName, value) {
      const field = fields[fieldName];
      const min = Number(field.number.min);
      const max = Number(field.number.max);
      const next = clamp(value, min, max);
      field.number.value = String(next);
      const rangeMin = Number(field.range.min);
      const rangeMax = Number(field.range.max);
      field.range.value = String(clamp(next, rangeMin, rangeMax));
    }

    function numberOrNull(value) {
      const number = Number(value);
      return Number.isFinite(number) ? number : null;
    }

    function firstMeaningfulNumber(...values) {
      const finite = values.filter((value) => value !== null && value !== undefined && Number.isFinite(Number(value)))
        .map((value) => Number(value));
      const nonZero = finite.find((value) => Math.abs(value) > 0.000001);
      return nonZero ?? finite[0] ?? null;
    }

    function withCurrentSlotEconomics(preset) {
      const slotSize = numberOrNull(preset.slotSize) ?? currentEnvelope.slotSize;
      const returnPercent = numberOrNull(preset.returnPercent) ?? 0;
      return {
        ...preset,
        returnDollars: Number(((slotSize * returnPercent) / 100).toFixed(4))
      };
    }

    function syncField(fieldName, source) {
      const field = fields[fieldName];
      const sourceNode = field[source];
      const targetNode = source === "range" ? field.number : field.range;
      const targetMin = Number(targetNode.min);
      const targetMax = Number(targetNode.max);
      targetNode.value = String(clamp(sourceNode.value, targetMin, targetMax));
    }

    function fmtCurrency(value, decimals = 2) {
      if (!Number.isFinite(value)) return "-";
      return `$${value.toLocaleString(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
      })}`;
    }

    function fmtNumber(value, decimals = 0) {
      if (!Number.isFinite(value)) return "-";
      return value.toLocaleString(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
      });
    }

    function pct(value) {
      return `${fmtNumber(value, value % 1 === 0 ? 0 : 2)}%`;
    }

    function fmtSnapshotLabel(value) {
      if (!value) return "Latest snapshot";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return "Latest snapshot";
      return `Snapshot ${date.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric"
      })} ${date.toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit"
      })}`;
    }

    function selectCompoundingAccount(snapshot) {
      const safeSnapshot = snapshot && typeof snapshot === "object" ? snapshot : {};
      const liveOverview = safeSnapshot.live_execution_overview || {};
      const brokerAccounts = Array.isArray(safeSnapshot.broker_accounts) ? safeSnapshot.broker_accounts : [];
      const liveBrokerId = String(liveOverview.broker_id || "alpaca_live").trim().toLowerCase();
      const liveAccount = brokerAccounts.find((row) => (
        row
        && row.has_snapshot
        && String(row.broker_id || "").trim().toLowerCase() === liveBrokerId
      ));

      if (liveOverview.enabled && liveAccount) {
        const slotSize = numberOrNull(liveOverview.slot_size_usd) ?? currentEnvelope.slotSize;
        const envelopeMaxUsd = numberOrNull(liveOverview.envelope_max_usd);
        const positionMarketValueUsd = numberOrNull(liveAccount.position_market_value);
        const inferredOpenPositions = positionMarketValueUsd !== null && slotSize > 0
          ? Math.max(0, Math.round(positionMarketValueUsd / slotSize))
          : null;
        const equity = numberOrNull(liveAccount.equity);
        const lastEquity = numberOrNull(liveAccount.last_equity);
        return {
          mode: "live",
          brokerLabel: String(liveAccount.broker_label || "Alpaca Live"),
          account: {
            slot_size_usd: slotSize,
            base_max_open_positions: numberOrNull(liveOverview.max_open_positions),
            effective_max_open_positions: numberOrNull(liveOverview.max_open_positions),
            capital_envelope_max_usd: envelopeMaxUsd,
            capital_committed_usd: positionMarketValueUsd,
            capital_committed_pct: envelopeMaxUsd && positionMarketValueUsd !== null
              ? Number(((positionMarketValueUsd / envelopeMaxUsd) * 100).toFixed(2))
              : null,
            open_positions_count: inferredOpenPositions,
            open_position_unrealized_pl_usd: numberOrNull(liveAccount.open_position_unrealized_pl),
            day_change_usd: equity !== null && lastEquity !== null
              ? Number((equity - lastEquity).toFixed(6))
              : null,
            earned_slot_pnl_usd: null,
          },
        };
      }

      return {
        mode: "paper",
        brokerLabel: "Alpaca Paper",
        account: safeSnapshot.account_overview || {},
      };
    }

    function selectOutcomeMetrics(snapshot, selected) {
      const safeSnapshot = snapshot && typeof snapshot === "object" ? snapshot : {};
      return selected.mode === "live"
        ? (safeSnapshot.live_trade_outcome_metrics || {})
        : (safeSnapshot.paper_trade_outcome_metrics || {});
    }

    function snapshotSourceLabel(snapshot) {
      const base = fmtSnapshotLabel(snapshot && snapshot.checked_at);
      const selected = selectCompoundingAccount(snapshot);
      const account = selected.account || {};
      const outcomes = selectOutcomeMetrics(snapshot, selected);
      const closedTrades = numberOrNull(outcomes.closed_trades) ?? 0;
      const openPositions = numberOrNull(account.open_positions_count);
      const effectiveSlots = numberOrNull(account.effective_max_open_positions)
        ?? numberOrNull(account.base_max_open_positions);

      if (closedTrades > 0) {
        return `${base} | ${selected.mode} outcomes ${fmtNumber(closedTrades, 0)} closed`;
      }
      if (openPositions !== null && effectiveSlots !== null && effectiveSlots > 0) {
        return `${base} | ${selected.mode} ${fmtNumber(openPositions, 0)}/${fmtNumber(effectiveSlots, 0)} slots | no closed outcomes`;
      }
      return `${base} | ${selected.mode} account defaults | no closed outcomes`;
    }

    function getInputs() {
      const slotSize = Math.max(0.01, valueOf("slotSize"));
      const returnPerSlot = backMode === "percent"
        ? slotSize * (valueOf("returnPercent") / 100)
        : valueOf("returnDollars");
      const activeDays = Math.max(1, Math.floor(valueOf("cycles")));
      const cyclesPerDay = Math.max(1, Math.floor(valueOf("cyclesPerDay")));
      return {
        baseSlots: Math.max(0, Math.floor(valueOf("baseSlots"))),
        slotSize,
        backMode,
        returnPercent: valueOf("returnPercent"),
        returnDollars: valueOf("returnDollars"),
        returnPerSlot,
        winRate: clamp(valueOf("winRate"), 0, 100) / 100,
        lossPercent: valueOf("lossPercent"),
        slotFill: clamp(valueOf("slotFill"), 0, 100) / 100,
        startingProfit: valueOf("startingProfit"),
        activeDays,
        cycles: activeDays * cyclesPerDay,
        cyclesPerDay
      };
    }

    function simulate(inputs) {
      const rows = [];
      let profit = inputs.startingProfit;

      for (let cycle = 0; cycle <= inputs.cycles; cycle += 1) {
        const earnedSlots = Math.floor(Math.max(0, profit) / inputs.slotSize);
        const effectiveSlots = inputs.baseSlots + earnedSlots;
        const slotsUsed = effectiveSlots * inputs.slotFill;
        const winningSlots = slotsUsed * inputs.winRate;
        const losingSlots = slotsUsed - winningSlots;
        const grossBack = cycle === 0 ? 0 : winningSlots * inputs.returnPerSlot;
        const lossDrag = cycle === 0 ? 0 : losingSlots * inputs.slotSize * (inputs.lossPercent / 100);
        const cycleBack = grossBack - lossDrag;
        const capacity = effectiveSlots * inputs.slotSize;
        rows.push({
          cycle,
          day: cycle / inputs.cyclesPerDay,
          profit,
          earnedSlots,
          effectiveSlots,
          capacity,
          grossBack,
          lossDrag,
          cycleBack
        });
        if (cycle < inputs.cycles) {
          profit += cycleBack;
        }
      }

      return rows;
    }

    function sampleRows(rows, count = 12) {
      if (rows.length <= count) return rows;
      const chosen = new Map();
      const maxIndex = rows.length - 1;
      for (let i = 0; i < count; i += 1) {
        const index = Math.round((i / (count - 1)) * maxIndex);
        chosen.set(index, rows[index]);
      }
      return Array.from(chosen.values());
    }

    function updateReadouts(inputs) {
      nodes.sourceBadge.textContent = currentDefaultSource;
      nodes.inputBadge.textContent = `${fmtCurrency(inputs.slotSize, 0)} slots`;
      nodes.baseSlotsReadout.textContent = fmtNumber(inputs.baseSlots);
      nodes.slotSizeReadout.textContent = fmtCurrency(inputs.slotSize);
      nodes.backModeReadout.textContent = backMode === "percent" ? "Percent" : "Dollars";
      nodes.returnPercentReadout.textContent = pct(inputs.returnPercent);
      nodes.returnDollarsReadout.textContent = fmtCurrency(inputs.returnDollars);
      nodes.winRateReadout.textContent = `${pct(inputs.winRate * 100)} win / ${pct((1 - inputs.winRate) * 100)} loss`;
      nodes.lossPercentReadout.textContent = pct(inputs.lossPercent);
      nodes.slotFillReadout.textContent = pct(inputs.slotFill * 100);
      nodes.startingProfitReadout.textContent = fmtCurrency(inputs.startingProfit);
      nodes.cyclesReadout.textContent = fmtNumber(inputs.activeDays);
      nodes.cyclesPerDayReadout.textContent = fmtNumber(inputs.cyclesPerDay);
      nodes.modePercent.classList.toggle("active", backMode === "percent");
      nodes.modeDollars.classList.toggle("active", backMode === "dollars");
      nodes.returnPercentControl.hidden = backMode !== "percent";
      nodes.returnDollarsControl.hidden = backMode !== "dollars";
    }

    function updateSummary(inputs, rows) {
      const end = rows[rows.length - 1];
      const gained = end.profit - inputs.startingProfit;
      const nextSlotAt = (end.earnedSlots + 1) * inputs.slotSize;
      const nextSlotNeeds = Math.max(0, nextSlotAt - Math.max(0, end.profit));
      const days = end.day;
      const slotTurnsPerDay = end.effectiveSlots * inputs.slotFill * inputs.cyclesPerDay;
      const returnText = backMode === "percent"
        ? `${pct(inputs.returnPercent)} avg win | ${pct(inputs.winRate * 100)} win / ${pct((1 - inputs.winRate) * 100)} loss`
        : `${fmtCurrency(inputs.returnPerSlot)} avg win | ${pct(inputs.winRate * 100)} win / ${pct((1 - inputs.winRate) * 100)} loss`;

      nodes.statProfit.textContent = fmtCurrency(end.profit);
      nodes.statProfitDetail.textContent = `${fmtCurrency(gained)} gained over ${fmtNumber(days, 1)} active days`;
      nodes.statSlots.textContent = fmtNumber(end.effectiveSlots);
      nodes.statSlotsDetail.textContent = `${fmtNumber(end.earnedSlots)} earned from ${fmtCurrency(Math.max(0, end.profit))} tracked P/L`;
      nodes.statCapacity.textContent = fmtCurrency(end.capacity);
      nodes.statCapacityDetail.textContent = `${fmtNumber(end.effectiveSlots)} x ${fmtCurrency(inputs.slotSize)} | ${fmtNumber(slotTurnsPerDay, 1)} projected slot turns/day | ${returnText} | ${pct(inputs.lossPercent)} loss`;
      nodes.statNext.textContent = fmtCurrency(nextSlotNeeds);
      nodes.statNextDetail.textContent = nextSlotNeeds === 0 ? "next slot unlocked" : `next slot at ${fmtCurrency(nextSlotAt)}`;
      nodes.chartBadge.textContent = `${fmtNumber(inputs.cycles)} cycles | ${fmtNumber(inputs.cyclesPerDay)} per day | ${fmtNumber(days, 1)} active days`;
      nodes.milestoneBadge.textContent = `${fmtNumber(end.earnedSlots)} earned`;
    }

    function updateMeters(inputs, rows) {
      const end = rows[rows.length - 1];
      const milestones = [
        { label: "Next earned slot", target: (end.earnedSlots + 1) * inputs.slotSize, tone: "" },
        { label: "Double base capacity", target: inputs.baseSlots * inputs.slotSize, tone: "gold" },
        { label: "Triple base capacity", target: inputs.baseSlots * inputs.slotSize * 2, tone: "blue" }
      ];

      nodes.meters.innerHTML = milestones.map((item) => {
        const progress = item.target > 0 ? clamp((Math.max(0, end.profit) / item.target) * 100, 0, 100) : 100;
        return `
          <div class="meter-row">
            <div class="meter-top">
              <span>${item.label}</span>
              <span class="meter-value">${fmtCurrency(Math.max(0, end.profit))} / ${fmtCurrency(item.target)}</span>
            </div>
            <div class="meter"><div class="meter-fill ${item.tone}" style="width: ${progress}%"></div></div>
          </div>
        `;
      }).join("");
    }

    function updateTimeline(rows) {
      const sampled = sampleRows(rows, 12);
      nodes.tableBadge.textContent = `${sampled.length} rows`;
      nodes.timelineBody.innerHTML = sampled.map((row) => `
        <tr>
          <td>${fmtNumber(row.cycle)}</td>
          <td>${fmtCurrency(row.profit)}</td>
          <td>${fmtNumber(row.earnedSlots)}</td>
          <td>${fmtNumber(row.effectiveSlots)}</td>
          <td>${fmtCurrency(row.capacity)}</td>
          <td>${fmtCurrency(row.cycleBack)}</td>
        </tr>
      `).join("");
    }

    function updateSlices(inputs) {
      const periodDays = 30;
      const totalDays = currentEnvelope.activeDaysPerYear * 5;
      const rows = simulate({
        ...inputs,
        cycles: Math.ceil(totalDays * inputs.cyclesPerDay)
      });
      const slices = [];

      if (totalDays <= 0) {
        nodes.sliceBadge.textContent = "0 slices";
        nodes.sliceBody.innerHTML = "";
        return;
      }

      for (let startDay = 0; startDay < totalDays; startDay += periodDays) {
        const endDay = Math.min(startDay + periodDays, totalDays);
        const start = rowAtDay(rows, startDay);
        const finish = rowAtDay(rows, endDay);
        const days = Math.max(0.0001, finish.day - start.day);
        const earned = finish.profit - start.profit;
        slices.push({
          startDay,
          endDay,
          earned,
          averagePerDay: earned / days,
          endingProfit: finish.profit,
          earnedSlots: finish.earnedSlots,
          effectiveSlots: finish.effectiveSlots,
          capacity: finish.capacity
        });
      }

      nodes.sliceBadge.textContent = `${slices.length} slices | 5 years`;
      nodes.sliceBody.innerHTML = slices.map((slice, index) => `
        <tr>
          <td>${fmtNumber(slice.startDay, 0)}-${fmtNumber(slice.endDay, 0)}</td>
          <td>${fmtNumber(index + 1)}</td>
          <td>${fmtCurrency(slice.earned)}</td>
          <td>${fmtCurrency(slice.averagePerDay)}</td>
          <td>${fmtCurrency(slice.endingProfit)}</td>
          <td>${fmtNumber(slice.earnedSlots)}</td>
          <td>${fmtNumber(slice.effectiveSlots)}</td>
          <td>${fmtCurrency(slice.capacity)}</td>
        </tr>
      `).join("");
    }

    function rowAtDay(rows, targetDay) {
      let closest = rows[0];
      for (const row of rows) {
        if (Math.abs(row.day - targetDay) < Math.abs(closest.day - targetDay)) {
          closest = row;
        }
        if (row.day >= targetDay) return row;
      }
      return rows[rows.length - 1];
    }

    function drawChart(rows) {
      const canvas = nodes.chart;
      const rect = canvas.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      const width = Math.max(320, Math.floor(rect.width * dpr));
      const height = Math.max(240, Math.floor(rect.height * dpr));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      const ctx = canvas.getContext("2d");
      ctx.clearRect(0, 0, width, height);
      ctx.scale(dpr, dpr);

      const w = width / dpr;
      const h = height / dpr;
      const pad = {
        left: Math.max(48, Math.min(72, w * 0.09)),
        right: Math.max(34, Math.min(54, w * 0.06)),
        top: 28,
        bottom: 42
      };
      const plotW = w - pad.left - pad.right;
      const plotH = h - pad.top - pad.bottom;
      const maxCycle = Math.max(1, rows[rows.length - 1].cycle);
      const maxMoney = Math.max(
        1,
        ...rows.map((row) => Math.max(row.profit, row.capacity, 0))
      );
      const maxSlots = Math.max(1, ...rows.map((row) => row.effectiveSlots));
      const moneyTop = niceCeil(maxMoney);
      const slotsTop = niceCeil(maxSlots);

      const x = (cycle) => pad.left + (cycle / maxCycle) * plotW;
      const yMoney = (value) => pad.top + plotH - (Math.max(0, value) / moneyTop) * plotH;
      const ySlots = (value) => pad.top + plotH - (value / slotsTop) * plotH;

      ctx.fillStyle = "#ffffff";
      roundRect(ctx, 0.5, 0.5, w - 1, h - 1, 8);
      ctx.fill();

      drawGrid(ctx, { pad, plotW, plotH, w, h, moneyTop, slotsTop });

      drawArea(ctx, rows, x, yMoney, pad.top + plotH);
      drawLine(ctx, rows, x, yMoney, "profit", "#0f8b8d", 3);
      drawLine(ctx, rows, x, yMoney, "capacity", "#3867d6", 2);
      drawStepLine(ctx, rows, x, ySlots, "effectiveSlots", "#c98f13", 2.5);

      const end = rows[rows.length - 1];
      drawPoint(ctx, x(end.cycle), yMoney(end.profit), "#0f8b8d");
      drawPoint(ctx, x(end.cycle), ySlots(end.effectiveSlots), "#c98f13");

      ctx.setTransform(1, 0, 0, 1, 0, 0);
    }

    function niceCeil(value) {
      const exponent = Math.floor(Math.log10(value));
      const base = Math.pow(10, exponent);
      const fraction = value / base;
      const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
      return nice * base;
    }

    function drawGrid(ctx, chart) {
      const { pad, plotW, plotH, w, moneyTop, slotsTop } = chart;
      ctx.strokeStyle = "#e3ebe7";
      ctx.lineWidth = 1;
      ctx.fillStyle = "#657174";
      ctx.font = "12px ui-sans-serif, system-ui, sans-serif";
      ctx.textBaseline = "middle";

      for (let i = 0; i <= 4; i += 1) {
        const t = i / 4;
        const y = pad.top + plotH - t * plotH;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(pad.left + plotW, y);
        ctx.stroke();
        ctx.textAlign = "right";
        ctx.fillText(fmtAxisMoney(moneyTop * t), pad.left - 10, y);
        ctx.textAlign = "left";
        ctx.fillText(fmtNumber(slotsTop * t, 0), pad.left + plotW + 10, y);
      }

      ctx.strokeStyle = "#cfdad5";
      ctx.beginPath();
      ctx.moveTo(pad.left, pad.top);
      ctx.lineTo(pad.left, pad.top + plotH);
      ctx.lineTo(pad.left + plotW, pad.top + plotH);
      ctx.lineTo(pad.left + plotW, pad.top);
      ctx.stroke();

      ctx.fillStyle = "#657174";
      ctx.textAlign = "left";
      ctx.textBaseline = "alphabetic";
      ctx.fillText("P/L and capacity", pad.left, 18);
      ctx.textAlign = "right";
      ctx.fillText("slots", w - pad.right, 18);
      ctx.textAlign = "center";
      ctx.fillText("cycles", pad.left + plotW / 2, pad.top + plotH + 30);
    }

    function fmtAxisMoney(value) {
      if (value >= 1000) return `$${fmtNumber(value / 1000, 1)}k`;
      return `$${fmtNumber(value, 0)}`;
    }

    function drawArea(ctx, rows, x, y, baseline) {
      ctx.beginPath();
      rows.forEach((row, index) => {
        const px = x(row.cycle);
        const py = y(row.profit);
        if (index === 0) ctx.moveTo(px, baseline);
        ctx.lineTo(px, py);
      });
      ctx.lineTo(x(rows[rows.length - 1].cycle), baseline);
      ctx.closePath();
      const gradient = ctx.createLinearGradient(0, 0, 0, baseline);
      gradient.addColorStop(0, "rgba(15, 139, 141, 0.24)");
      gradient.addColorStop(1, "rgba(15, 139, 141, 0.02)");
      ctx.fillStyle = gradient;
      ctx.fill();
    }

    function drawLine(ctx, rows, x, y, key, color, width) {
      ctx.beginPath();
      rows.forEach((row, index) => {
        const px = x(row.cycle);
        const py = y(row[key]);
        if (index === 0) ctx.moveTo(px, py);
        else ctx.lineTo(px, py);
      });
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.stroke();
    }

    function drawStepLine(ctx, rows, x, y, key, color, width) {
      ctx.beginPath();
      rows.forEach((row, index) => {
        const px = x(row.cycle);
        const py = y(row[key]);
        if (index === 0) {
          ctx.moveTo(px, py);
          return;
        }
        const prev = rows[index - 1];
        const prevX = x(prev.cycle);
        const prevY = y(prev[key]);
        ctx.lineTo(px, prevY);
        ctx.lineTo(px, py);
      });
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.stroke();
    }

    function drawPoint(ctx, x, y, color) {
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    function roundRect(ctx, x, y, width, height, radius) {
      ctx.beginPath();
      ctx.moveTo(x + radius, y);
      ctx.arcTo(x + width, y, x + width, y + height, radius);
      ctx.arcTo(x + width, y + height, x, y + height, radius);
      ctx.arcTo(x, y + height, x, y, radius);
      ctx.arcTo(x, y, x + width, y, radius);
      ctx.closePath();
    }

    function render() {
      const inputs = getInputs();
      const rows = simulate(inputs);
      updateReadouts(inputs);
      updateSummary(inputs, rows);
      updateMeters(inputs, rows);
      latestRows = rows;
      updateSlices(inputs);
      updateTimeline(rows);
      if (!nodes.tabGraph.hidden) {
        drawChart(rows);
      }
    }

    function applyPreset(preset, sourceLabel = "Current envelope") {
      const normalizedPreset = withCurrentSlotEconomics(preset);
      currentDefaultSource = sourceLabel;
      backMode = normalizedPreset.backMode;
      Object.entries(normalizedPreset).forEach(([key, value]) => {
        if (key in fields) setField(key, value);
      });
      render();
    }

    function presetFromSnapshot(snapshot) {
      const selected = selectCompoundingAccount(snapshot);
      const account = selected.account || {};
      const performance = snapshot && typeof snapshot === "object" ? snapshot.performance_comparison || {} : {};
      const outcomes = selectOutcomeMetrics(snapshot, selected);
      const slotSize = numberOrNull(account.slot_size_usd) ?? currentEnvelope.slotSize;
      const baseSlots = numberOrNull(account.base_max_open_positions) ?? currentEnvelope.baseSlots;
      const effectiveSlots = numberOrNull(account.effective_max_open_positions) ?? baseSlots;
      const openPositions = numberOrNull(account.open_positions_count);
      const openPositionUnrealizedPlUsd = numberOrNull(account.open_position_unrealized_pl_usd);
      const currentSlotFillPct = effectiveSlots > 0 && openPositions !== null
        ? Number(((openPositions / effectiveSlots) * 100).toFixed(2))
        : numberOrNull(account.capital_committed_pct);
      const trackedPnl = firstMeaningfulNumber(
        numberOrNull(performance.total_pnl_usd),
        openPositionUnrealizedPlUsd,
        numberOrNull(account.day_change_usd),
        numberOrNull(account.earned_slot_pnl_usd)
      );
      const closedTrades = numberOrNull(outcomes.closed_trades) ?? 0;
      const avgWinPct = numberOrNull(outcomes.avg_win_pct);
      const avgLossPct = numberOrNull(outcomes.avg_loss_pct);
      const winRate = numberOrNull(outcomes.win_rate);
      const observedSlotFillPct = numberOrNull(outcomes.observed_slot_fill_pct);
      const observedTradesPerDay = numberOrNull(outcomes.observed_trades_per_day);
      const hasOutcomeMetrics = closedTrades > 0;
      const observedCyclesPerDay = hasOutcomeMetrics && observedTradesPerDay !== null && effectiveSlots > 0
        ? Math.max(1, Math.ceil(observedTradesPerDay / effectiveSlots))
        : defaults.cyclesPerDay;
      const observedSlotsPerCyclePct = hasOutcomeMetrics && observedTradesPerDay !== null && effectiveSlots > 0
        ? Number(clamp((observedTradesPerDay / (effectiveSlots * observedCyclesPerDay)) * 100, 1, 100).toFixed(2))
        : null;
      return {
        ...defaults,
        baseSlots,
        slotSize,
        returnPercent: hasOutcomeMetrics && avgWinPct !== null
          ? avgWinPct
          : 0,
        winRate: hasOutcomeMetrics && winRate !== null ? Number((winRate * 100).toFixed(2)) : 0,
        lossPercent: hasOutcomeMetrics && avgLossPct !== null ? avgLossPct : 0,
        slotFill: observedSlotsPerCyclePct !== null
          ? observedSlotsPerCyclePct
          : hasOutcomeMetrics && observedSlotFillPct !== null && observedSlotFillPct > 0
          ? observedSlotFillPct
          : (currentSlotFillPct ?? defaults.slotFill),
        startingProfit: trackedPnl === null ? defaults.startingProfit : Number(trackedPnl.toFixed(2)),
        cyclesPerDay: observedCyclesPerDay
      };
    }

    function loadJson(url) {
      if (typeof window.fetch === "function") {
        return window.fetch(url, { cache: "no-store" }).then((response) => {
          if (!response.ok) {
            throw new Error(`Snapshot request failed with ${response.status}`);
          }
          return response.json();
        });
      }
      if (typeof window.XMLHttpRequest !== "function") {
        return Promise.reject(new Error("Snapshot requests are not supported by this browser"));
      }

      return new Promise((resolve, reject) => {
        const request = new XMLHttpRequest();
        request.open("GET", url, true);
        request.setRequestHeader("Accept", "application/json");
        request.onload = () => {
          if (request.status < 200 || request.status >= 300) {
            reject(new Error(`Snapshot request failed with ${request.status}`));
            return;
          }
          try {
            resolve(JSON.parse(request.responseText));
          } catch (error) {
            reject(error);
          }
        };
        request.onerror = () => reject(new Error("Snapshot request failed"));
        request.send();
      });
    }

    async function loadSnapshotDefaults() {
      if (!["http:", "https:"].includes(window.location.protocol)) {
        return false;
      }
      const snapshot = await loadJson("/snapshot/");
      applyPreset(presetFromSnapshot(snapshot), snapshotSourceLabel(snapshot));
      return true;
    }

    async function initialize() {
      if (embeddedSnapshot && typeof embeddedSnapshot === "object") {
        applyPreset(presetFromSnapshot(embeddedSnapshot), snapshotSourceLabel(embeddedSnapshot));
      } else {
        applyPreset(defaults, "Current envelope");
      }
      try {
        await loadSnapshotDefaults();
      } catch (error) {
        if (!embeddedSnapshot || typeof embeddedSnapshot !== "object") {
          currentDefaultSource = "Current envelope";
          render();
        }
      }
    }

    function setActiveTab(tabName) {
      const graphActive = tabName === "graph";
      nodes.tabGraph.hidden = !graphActive;
      nodes.tabSlices.hidden = graphActive;
      nodes.tabGraphButton.classList.toggle("active", graphActive);
      nodes.tabSlicesButton.classList.toggle("active", !graphActive);
      nodes.tabGraphButton.setAttribute("aria-selected", graphActive ? "true" : "false");
      nodes.tabSlicesButton.setAttribute("aria-selected", graphActive ? "false" : "true");
      if (graphActive && latestRows.length) {
        drawChart(latestRows);
      }
    }

    Object.entries(fields).forEach(([fieldName, field]) => {
      field.range.addEventListener("input", () => {
        syncField(fieldName, "range");
        render();
      });
      field.number.addEventListener("input", () => {
        syncField(fieldName, "number");
        render();
      });
    });

    nodes.modePercent.addEventListener("click", () => {
      backMode = "percent";
      render();
    });

    nodes.modeDollars.addEventListener("click", () => {
      backMode = "dollars";
      render();
    });

    nodes.tabGraphButton.addEventListener("click", () => setActiveTab("graph"));
    nodes.tabSlicesButton.addEventListener("click", () => setActiveTab("slices"));

    document.getElementById("preset-current").addEventListener("click", async () => {
      try {
        const loaded = await loadSnapshotDefaults();
        if (!loaded) {
          if (embeddedSnapshot && typeof embeddedSnapshot === "object") {
            applyPreset(presetFromSnapshot(embeddedSnapshot), snapshotSourceLabel(embeddedSnapshot));
          } else {
            applyPreset(defaults, "Current envelope");
          }
        }
      } catch (error) {
        if (embeddedSnapshot && typeof embeddedSnapshot === "object") {
          applyPreset(presetFromSnapshot(embeddedSnapshot), snapshotSourceLabel(embeddedSnapshot));
        } else {
          applyPreset(defaults, "Current envelope");
        }
      }
    });
    document.getElementById("preset-fast").addEventListener("click", () => applyPreset(fastPreset, "Faster test"));
    document.getElementById("reset").addEventListener("click", () => applyPreset(defaults, "Current envelope"));
    window.addEventListener("resize", render);

    initialize();
  </script>
</body>
</html>

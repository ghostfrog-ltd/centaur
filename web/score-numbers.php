<?php
declare(strict_types=1);

header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');

require __DIR__ . '/navigation.php';
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Centaur Score Numbers</title>
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
      --blue: #3867d6;
      --gold: #c98f13;
      --rose: #c94b5f;
      --green: #258b57;
      --shadow: 0 16px 40px rgba(18, 31, 32, 0.08);
    }

    * {
      box-sizing: border-box;
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
      width: min(1260px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0 34px;
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

    .lede {
      max-width: 780px;
      margin: 10px 0 0;
      color: var(--muted);
      line-height: 1.5;
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

    .button.primary {
      background: var(--teal);
      border-color: var(--teal);
      color: white;
    }

    .button.danger {
      background: var(--rose);
      border-color: var(--rose);
      color: white;
    }

    .layout {
      display: grid;
      grid-template-columns: minmax(300px, 0.78fr) minmax(0, 1.42fr);
      gap: 18px;
      align-items: start;
    }

    .panel {
      min-width: 0;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.92);
      box-shadow: var(--shadow);
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

    .badge.danger {
      background: rgba(201, 75, 95, 0.12);
      color: var(--rose);
    }

    .controls {
      display: grid;
      gap: 17px;
      padding: 16px;
    }

    .control {
      display: grid;
      gap: 8px;
    }

    .control-top {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 14px;
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

    .number-row {
      display: grid;
      grid-template-columns: 1fr 92px;
      gap: 10px;
      align-items: center;
    }

    input[type="range"] {
      width: 100%;
      accent-color: var(--teal);
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
      font-weight: 750;
    }

    input[type="number"] {
      text-align: right;
    }

    .rule {
      margin: 0;
      border-top: 1px solid var(--line);
      background: rgba(238, 245, 241, 0.52);
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
      padding: 13px 16px 16px;
    }

    .cards {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }

    .card {
      min-height: 132px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 16px;
      box-shadow: 0 8px 22px rgba(18, 31, 32, 0.05);
      min-width: 0;
    }

    .card.positive {
      border-color: rgba(37, 139, 87, 0.35);
    }

    .card.warning {
      border-color: rgba(201, 143, 19, 0.38);
    }

    .card.danger {
      border-color: rgba(201, 75, 95, 0.42);
    }

    .card.blue {
      border-color: rgba(56, 103, 214, 0.34);
    }

    .card-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    .card-value {
      margin-top: 14px;
      font-size: clamp(28px, 3vw, 46px);
      font-weight: 950;
      line-height: 0.95;
      overflow-wrap: anywhere;
    }

    .card-detail {
      margin-top: 10px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.35;
    }

    .control-note {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.35;
    }

    .two-up {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      padding: 16px;
    }

    .mini-card {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfdfc;
      padding: 14px;
    }

    .mini-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    .mini-value {
      margin-top: 8px;
      font-size: 24px;
      font-weight: 950;
      line-height: 1;
      overflow-wrap: anywhere;
    }

    .mini-detail {
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }

    .tone-positive,
    td.positive {
      color: var(--green);
    }

    .tone-warning {
      color: var(--gold);
    }

    .tone-danger,
    td.negative {
      color: var(--rose);
    }

    .pill {
      display: inline-flex;
      align-items: center;
      min-height: 24px;
      border-radius: 999px;
      padding: 3px 9px;
      background: var(--surface-2);
      color: var(--teal-dark);
      font-size: 12px;
      font-weight: 850;
      white-space: nowrap;
    }

    .pill.warning {
      background: rgba(201, 143, 19, 0.12);
      color: #8a620d;
    }

    .pill.danger {
      background: rgba(201, 75, 95, 0.12);
      color: var(--rose);
    }

    .stack {
      display: grid;
      gap: 18px;
    }

    .chart {
      display: grid;
      gap: 8px;
      padding: 16px;
    }

    .bar-row {
      display: grid;
      grid-template-columns: 66px minmax(0, 1fr) 54px;
      gap: 10px;
      align-items: center;
      min-height: 28px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 750;
    }

    .bar-track {
      position: relative;
      height: 18px;
      border-radius: 5px;
      background: #eef4f1;
      overflow: hidden;
    }

    .bar-fill {
      position: absolute;
      inset: 0 auto 0 0;
      width: 0%;
      border-radius: inherit;
      background: linear-gradient(90deg, var(--teal), var(--blue));
    }

    .table-wrap {
      max-width: 100%;
      overflow-x: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
    }

    th,
    td {
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }

    th {
      background: #f8fbf9;
      color: var(--muted);
      font-size: 11px;
      font-weight: 850;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      white-space: nowrap;
    }

    code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-weight: 800;
    }

    .status {
      color: var(--muted);
      font-size: 13px;
      font-weight: 750;
    }

    .status.bad {
      color: var(--rose);
    }

    .status.good {
      color: var(--green);
    }

    .empty {
      margin: 0;
      padding: 16px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
    }

    @media (max-width: 980px) {
      .layout {
        grid-template-columns: 1fr;
      }

      .cards {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }

      .two-up {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 680px) {
      .shell {
        width: min(100% - 24px, 1120px);
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

      .cards {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">Project Centaur</p>
        <h1>Score Numbers</h1>
        <p class="lede">Move the score, observe-only, throughput, and loss-guard sliders to see how recent proposal evidence would move. Saving only changes the score and observe-only floor .env values; it does not change notional, slots, brokers, daily loss protection, or live approval.</p>
      </div>
      <div class="toolbar centaur-menu-toolbar">
        <?php centaurRenderNavigation('/score-numbers.php'); ?>
      </div>
    </header>

    <section class="layout">
      <aside class="panel" aria-label="Score controls">
        <div class="panel-head">
          <div class="panel-title">Score Dial</div>
          <span id="runtime-badge" class="badge">loading</span>
        </div>
        <div class="controls">
          <div class="control">
            <div class="control-top">
              <label for="score-threshold">Score To Trade</label>
              <span id="score-readout" class="readout">90.0</span>
            </div>
            <div class="number-row">
              <input id="score-threshold" type="range" min="50" max="110" step="0.5" value="90">
              <input id="score-threshold-number" type="number" min="0" max="150" step="0.5" value="90">
            </div>
            <div class="control-note">Actual override uses raw/base score for allowed strategies. The displayed proposal score may be adjusted by fitness.</div>
          </div>

          <div class="control">
            <div class="control-top">
              <label for="observe-floor">Observe-Only Floor</label>
              <span id="observe-readout" class="readout">80.0</span>
            </div>
            <div class="number-row">
              <input id="observe-floor" type="range" min="50" max="110" step="0.5" value="80">
              <input id="observe-floor-number" type="number" min="0" max="150" step="0.5" value="80">
            </div>
            <div class="control-note">Shows extra candidates worth watching below the trade dial without treating them as executable.</div>
          </div>

          <div class="control">
            <div class="control-top">
              <label for="target-min">Target Min Trades Per Day</label>
              <span id="target-readout" class="readout">15-20</span>
            </div>
            <div class="number-row">
              <input id="target-min" type="range" min="0" max="80" step="1" value="15">
              <input id="target-min-number" type="number" min="0" max="80" step="1" value="15">
            </div>
            <div class="control-note">Throughput target only. It must not widen risk, notional, slots, broker scope, or live gates.</div>
          </div>

          <div class="control">
            <div class="control-top">
              <label for="target-max">Target Max Trades Per Day</label>
              <span id="target-max-readout" class="readout">20</span>
            </div>
            <div class="number-row">
              <input id="target-max" type="range" min="0" max="80" step="1" value="20">
              <input id="target-max-number" type="number" min="0" max="80" step="1" value="20">
            </div>
          </div>

          <div class="control">
            <div class="control-top">
              <label for="loss-guard">Daily Loss Guard</label>
              <span id="guard-readout" class="readout">$2.00</span>
            </div>
            <div class="number-row">
              <input id="loss-guard" type="range" min="0.5" max="10" step="0.25" value="2">
              <input id="loss-guard-number" type="number" min="0" max="50" step="0.25" value="2">
            </div>
            <div class="control-note">Visual comparison only. The live protector is latched by runtime config and current broker/account evidence.</div>
          </div>

          <div class="control">
            <div class="control-top">
              <label for="days">Evidence Window</label>
              <span id="days-readout" class="readout">90 days</span>
            </div>
            <select id="days">
              <option value="7">7 days</option>
              <option value="30">30 days</option>
              <option value="90" selected>90 days</option>
              <option value="180">180 days</option>
              <option value="366">366 days</option>
            </select>
          </div>

          <button id="refresh" class="button primary" type="button">Refresh</button>
          <button id="save-env" class="button danger" type="button">Save Score Values To .env</button>
          <div id="load-status" class="status">Loading score evidence...</div>
          <div id="save-status" class="status">Loads score values from .env on page open.</div>
        </div>
        <p class="rule">Saving writes PAPER/LIVE_MIN_SIGNAL_SCORE_TO_TRADE and PAPER/LIVE_OBSERVE_ONLY_SIGNAL_SCORE_FLOOR to .env. Future ticks and restarted dashboard API processes read those values; CFO, risk, slots, market hours, projected gain, drawdown, broker, and live guards still apply after a signal survives allocation.</p>
      </aside>

      <section class="stack">
        <div id="cards" class="cards" aria-label="Score impact summary"></div>

        <section class="panel" aria-label="Throughput and protection">
          <div class="panel-head">
            <div class="panel-title">Throughput, Fitness, And Protection</div>
            <span id="guard-badge" class="badge">loading</span>
          </div>
          <div id="throughput-panel" class="two-up"></div>
          <p class="rule">Score can increase candidates, but fitness and daily protection explain why a good-looking score may still not become a trade.</p>
        </section>

        <section class="panel" aria-label="Score distribution">
          <div class="panel-head">
            <div class="panel-title">Generated Proposal Score Distribution</div>
            <span id="bucket-badge" class="badge">0 proposals</span>
          </div>
          <div id="chart" class="chart"></div>
          <p id="scope-note" class="rule">Read-only generated proposal evidence.</p>
        </section>

        <section class="panel" aria-label="Fitness evidence">
          <div class="panel-head">
            <div class="panel-title">Latest Fitness Evidence</div>
            <span id="fitness-badge" class="badge">0 rows</span>
          </div>
          <div id="fitness-table" class="table-wrap"></div>
        </section>

        <section class="panel" aria-label="Strategy score impact">
          <div class="panel-head">
            <div class="panel-title">Strategy Breakdown</div>
            <span id="strategy-badge" class="badge">0 rows</span>
          </div>
          <div id="strategy-table" class="table-wrap"></div>
        </section>

        <section class="panel" aria-label="Recent high scores">
          <div class="panel-head">
            <div class="panel-title">Highest Recent Proposal Scores</div>
            <span id="recent-badge" class="badge">0 rows</span>
          </div>
          <div id="recent-table" class="table-wrap"></div>
        </section>
      </section>
    </section>
  </main>

  <script>
    const fields = {
      threshold: {
        range: document.getElementById("score-threshold"),
        number: document.getElementById("score-threshold-number")
      },
      observe: {
        range: document.getElementById("observe-floor"),
        number: document.getElementById("observe-floor-number")
      },
      guard: {
        range: document.getElementById("loss-guard"),
        number: document.getElementById("loss-guard-number")
      },
      targetMin: {
        range: document.getElementById("target-min"),
        number: document.getElementById("target-min-number")
      },
      targetMax: {
        range: document.getElementById("target-max"),
        number: document.getElementById("target-max-number")
      },
      days: document.getElementById("days")
    };

    const nodes = {
      scoreReadout: document.getElementById("score-readout"),
      observeReadout: document.getElementById("observe-readout"),
      targetReadout: document.getElementById("target-readout"),
      targetMaxReadout: document.getElementById("target-max-readout"),
      guardReadout: document.getElementById("guard-readout"),
      daysReadout: document.getElementById("days-readout"),
      runtimeBadge: document.getElementById("runtime-badge"),
      loadStatus: document.getElementById("load-status"),
      saveStatus: document.getElementById("save-status"),
      refresh: document.getElementById("refresh"),
      saveEnv: document.getElementById("save-env"),
      cards: document.getElementById("cards"),
      guardBadge: document.getElementById("guard-badge"),
      throughputPanel: document.getElementById("throughput-panel"),
      bucketBadge: document.getElementById("bucket-badge"),
      chart: document.getElementById("chart"),
      scopeNote: document.getElementById("scope-note"),
      fitnessBadge: document.getElementById("fitness-badge"),
      fitnessTable: document.getElementById("fitness-table"),
      strategyBadge: document.getElementById("strategy-badge"),
      strategyTable: document.getElementById("strategy-table"),
      recentBadge: document.getElementById("recent-badge"),
      recentTable: document.getElementById("recent-table")
    };

    let report = null;
    let scoreEnvLoaded = false;

    function clamp(value, min, max) {
      const number = Number(value);
      if (!Number.isFinite(number)) return min;
      return Math.min(max, Math.max(min, number));
    }

    function pairValue(pair) {
      return Number(pair.number.value);
    }

    function thresholdValue() {
      return pairValue(fields.threshold);
    }

    function observeValue() {
      return pairValue(fields.observe);
    }

    function guardValue() {
      return pairValue(fields.guard);
    }

    function targetBounds() {
      const min = pairValue(fields.targetMin) || 0;
      const max = pairValue(fields.targetMax) || 0;
      return {
        min: Math.min(min, max),
        max: Math.max(min, max)
      };
    }

    function syncPair(pair, source, readout, formatter) {
      const sourceNode = pair[source];
      const targetNode = source === "range" ? pair.number : pair.range;
      targetNode.value = String(clamp(sourceNode.value, Number(targetNode.min), Number(targetNode.max)));
      readout.textContent = formatter(pairValue(pair));
      render();
    }

    function syncTarget() {
      const bounds = targetBounds();
      nodes.targetReadout.textContent = `${fmtInteger(bounds.min)}-${fmtInteger(bounds.max)}`;
      nodes.targetMaxReadout.textContent = fmtInteger(pairValue(fields.targetMax));
      render();
    }

    function syncTargetPair(pair, source) {
      const sourceNode = pair[source];
      const targetNode = source === "range" ? pair.number : pair.range;
      targetNode.value = String(clamp(sourceNode.value, Number(targetNode.min), Number(targetNode.max)));
      if (pair === fields.targetMin && pairValue(fields.targetMin) > pairValue(fields.targetMax)) {
        setPairValue(fields.targetMax, pairValue(fields.targetMin));
      }
      if (pair === fields.targetMax && pairValue(fields.targetMax) < pairValue(fields.targetMin)) {
        setPairValue(fields.targetMin, pairValue(fields.targetMax));
      }
      syncTarget();
    }

    function setPairValue(pair, value) {
      const next = String(value);
      pair.number.value = next;
      pair.range.value = String(clamp(value, Number(pair.range.min), Number(pair.range.max)));
    }

    function buckets() {
      return Array.isArray(report?.observed?.buckets) ? report.observed.buckets : [];
    }

    function baseBuckets() {
      return Array.isArray(report?.observed?.base_buckets) ? report.observed.base_buckets : [];
    }

    function strategyBuckets() {
      return Array.isArray(report?.observed?.strategy_buckets) ? report.observed.strategy_buckets : [];
    }

    function strategyBaseBuckets() {
      return Array.isArray(report?.observed?.strategy_base_buckets) ? report.observed.strategy_base_buckets : [];
    }

    function countAtThreshold(rows, threshold) {
      return rows.reduce((total, row) => {
        const score = Number(row.score_bucket);
        const count = Number(row.proposal_count) || 0;
        return score >= threshold ? total + count : total;
      }, 0);
    }

    function totalCount() {
      return Number(report?.observed?.total_count) || 0;
    }

    function baseTotalCount() {
      return Number(report?.observed?.base_total_count) || 0;
    }

    function currentPaperThreshold() {
      return Number(report?.config?.paper_min_signal_score_to_trade) || 90;
    }

    function currentLiveThreshold() {
      return Number(report?.config?.live_min_signal_score_to_trade) || 90;
    }

    function currentPaperObserveFloor() {
      return Number(report?.config?.paper_observe_only_signal_score_floor) || 80;
    }

    function render() {
      if (!report) {
        renderEmpty();
        return;
      }
      const selected = thresholdValue();
      const observe = observeValue();
      const guard = guardValue();
      const targets = targetBounds();
      const total = totalCount();
      const baseTotal = baseTotalCount();
      const adjustedSelected = countAtThreshold(buckets(), selected);
      const baseSelected = countAtThreshold(baseBuckets(), selected);
      const adjustedAllowed = allowedCountAtThreshold(selected, "adjusted");
      const baseAllowed = allowedCountAtThreshold(selected, "base");
      const adjustedAllowedAtObserve = allowedCountAtThreshold(observe, "adjusted");
      const observeBand = Math.max(0, adjustedAllowedAtObserve - adjustedAllowed);
      const paperBaseAllowed = allowedCountAtThreshold(currentPaperThreshold(), "base");
      const delta = baseAllowed - paperBaseAllowed;
      const scoreToTrade = Number(report?.observed?.score_to_trade_count) || 0;
      const days = Number(report?.days || fields.days.value) || 1;
      const candidatesPerDay = baseAllowed / days;
      const actual = actualDailyStats();
      const protection = protectionState();
      const fitness = fitnessSummary();
      const guardTone = protection.blocked || protection.drawdown >= guard ? "danger" : "positive";
      const throughputTone = candidatesPerDay < targets.min ? "warning" : (candidatesPerDay > targets.max ? "warning" : "positive");

      nodes.runtimeBadge.textContent = `${report.runtime?.environment || "-"} / ${report.runtime?.mode || "-"}`;
      nodes.daysReadout.textContent = `${days} days`;
      nodes.bucketBadge.textContent = `${fmtInteger(total)} displayed / ${fmtInteger(baseTotal)} raw`;
      nodes.scopeNote.textContent = report.scope_note || "Read-only generated proposal evidence.";
      nodes.guardBadge.textContent = protection.blocked ? "protected" : "active";
      nodes.guardBadge.classList.toggle("danger", protection.blocked);

      nodes.cards.innerHTML = [
        {
          label: "Selected Trade Score",
          value: fmtNumber(selected, 1),
          detail: `runtime paper ${fmtNumber(currentPaperThreshold(), 1)} / live ${fmtNumber(currentLiveThreshold(), 1)}`,
          tone: "blue"
        },
        {
          label: "Raw/Base Allowed At Dial",
          value: fmtInteger(baseAllowed),
          detail: `${fmtPct(part(baseAllowed, baseTotal))} of raw-score proposal rows match allowed strategies`,
          tone: "positive"
        },
        {
          label: "Displayed Score At Dial",
          value: fmtInteger(adjustedAllowed),
          detail: `${fmtPct(part(adjustedAllowed, total))} after score/fitness adjustment`,
          tone: "blue"
        },
        {
          label: "Observe-Only Band",
          value: fmtInteger(observeBand),
          detail: `displayed-score allowed proposals from ${fmtNumber(observe, 1)} up to below ${fmtNumber(selected, 1)}`,
          tone: observeBand > 0 ? "warning" : "blue"
        },
        {
          label: "Candidates Per Day",
          value: fmtNumber(candidatesPerDay, 1),
          detail: `proposal estimate against ${fmtInteger(targets.min)}-${fmtInteger(targets.max)} target trades/day`,
          tone: throughputTone
        },
        {
          label: "Actual Closed Per Day",
          value: fmtNumber(actual.avgClosedPerDay, 1),
          detail: `${fmtInteger(actual.totalClosed)} closed trades across ${fmtInteger(actual.days)} recent P/L days`,
          tone: actual.avgClosedPerDay >= targets.min && actual.avgClosedPerDay <= targets.max ? "positive" : "warning"
        },
        {
          label: "Daily Loss Guard",
          value: `${fmtMoney(protection.drawdown)} / ${fmtMoney(guard)}`,
          detail: `runtime limit ${fmtMoney(protection.runtimeLimit)}; ${protection.reason || "no current block reason"}`,
          tone: guardTone
        },
        {
          label: "Fitness Evidence",
          value: `${fmtInteger(fitness.positive)}+ / ${fmtInteger(fitness.negative)}-`,
          detail: `latest rows: best ${fmtNumber(fitness.best, 2)} / worst ${fmtNumber(fitness.worst, 2)}`,
          tone: fitness.negative > fitness.positive ? "danger" : "positive"
        },
        {
          label: "Recorded Score-To-Trade",
          value: fmtInteger(scoreToTrade),
          detail: "historical proposals admitted by the override after fitness suppression",
          tone: "blue"
        }
      ].map((card) => `
        <article class="card ${card.tone}">
          <div class="card-label">${escapeHtml(card.label)}</div>
          <div class="card-value">${escapeHtml(card.value)}</div>
          <div class="card-detail">${escapeHtml(card.detail)}</div>
        </article>
      `).join("");

      renderThroughputPanel({
        candidatesPerDay,
        targets,
        actual,
        protection,
        guard,
        fitness,
        baseAllowed,
        observeBand,
        adjustedSelected,
        baseSelected,
        delta
      });
      renderChart(selected);
      renderFitnessTable();
      renderStrategyTable(selected, observe);
      renderRecentTable();
    }

    function renderChart(selected) {
      const ranges = scoreRanges();
      const maxCount = Math.max(1, ...ranges.map((row) => row.count));
      nodes.chart.innerHTML = ranges.map((row) => {
        const active = row.high >= selected;
        const width = Math.max(2, (row.count / maxCount) * 100);
        return `
          <div class="bar-row">
            <div>${escapeHtml(row.label)}</div>
            <div class="bar-track" title="${escapeHtml(row.count)} proposals">
              <div class="bar-fill" style="width: ${width}%; ${active ? "" : "background: #a8b7b5;"}"></div>
            </div>
            <div>${fmtInteger(row.count)}</div>
          </div>
        `;
      }).join("");
    }

    function scoreRanges() {
      const rangeSize = 5;
      const ranges = [];
      ranges.push({
        low: 105,
        high: Number.POSITIVE_INFINITY,
        label: "105+",
        count: 0
      });
      for (let low = 100; low >= 50; low -= rangeSize) {
        ranges.push({
          low,
          high: low + rangeSize - 0.1,
          label: low === 100 ? "100" : `${low}-${low + rangeSize - 0.1}`,
          count: 0
        });
      }
      const rows = buckets();
      rows.forEach((row) => {
        const score = Number(row.score_bucket);
        const count = Number(row.proposal_count) || 0;
        const target = ranges.find((range) => score >= range.low && score <= range.high);
        if (target) {
          target.count += count;
        }
      });
      return ranges;
    }

    function renderThroughputPanel(summary) {
      const targetText = `${fmtInteger(summary.targets.min)}-${fmtInteger(summary.targets.max)}`;
      const status = summary.candidatesPerDay < summary.targets.min
        ? "below target"
        : (summary.candidatesPerDay > summary.targets.max ? "above target" : "inside target");
      const statusTone = summary.candidatesPerDay < summary.targets.min || summary.candidatesPerDay > summary.targets.max
        ? "tone-warning"
        : "tone-positive";
      const guardWouldBlock = summary.protection.drawdown >= summary.guard && summary.protection.drawdown > 0;
      nodes.throughputPanel.innerHTML = [
        {
          label: "Throughput Target",
          value: `${fmtNumber(summary.candidatesPerDay, 1)} / day`,
          detail: `<span class="${statusTone}">${escapeHtml(status)}</span> versus ${escapeHtml(targetText)} trades/day. This is proposal flow, not guaranteed fills.`
        },
        {
          label: "Actual Recent Trading",
          value: `${fmtNumber(summary.actual.avgClosedPerDay, 1)} / day`,
          detail: `${fmtInteger(summary.actual.totalClosed)} closed trades; recent P/L ${fmtMoney(summary.actual.realizedPnl)}.`
        },
        {
          label: "Daily Protection",
          value: summary.protection.blocked ? "blocked" : "active",
          detail: `${guardWouldBlock ? '<span class="tone-danger">slider guard would block</span>' : '<span class="tone-positive">slider guard would not block</span>'}; current drawdown ${fmtMoney(summary.protection.drawdown)}.`
        },
        {
          label: "Score/Fitness Difference",
          value: `${fmtInteger(summary.baseSelected)} raw / ${fmtInteger(summary.adjustedSelected)} shown`,
          detail: `Raw score is the override proxy; displayed score includes fitness effects. Vs paper dial: ${escapeHtml(signedInteger(summary.delta))}.`
        },
        {
          label: "Observe-Only Supply",
          value: fmtInteger(summary.observeBand),
          detail: "Candidates below the trade dial that could be measured without being allowed through."
        },
        {
          label: "Fitness Direction",
          value: `${fmtInteger(summary.fitness.positive)} positive`,
          detail: `${fmtInteger(summary.fitness.negative)} negative latest fitness rows; best ${fmtNumber(summary.fitness.best, 2)}, worst ${fmtNumber(summary.fitness.worst, 2)}.`
        }
      ].map((item) => `
        <article class="mini-card">
          <div class="mini-label">${escapeHtml(item.label)}</div>
          <div class="mini-value">${escapeHtml(item.value)}</div>
          <div class="mini-detail">${item.detail}</div>
        </article>
      `).join("");
    }

    function renderFitnessTable() {
      const rows = Array.isArray(report?.health?.latest_fitness_snapshot)
        ? report.health.latest_fitness_snapshot
        : [];
      nodes.fitnessBadge.textContent = `${fmtInteger(rows.length)} rows`;
      if (!rows.length) {
        nodes.fitnessTable.innerHTML = `<p class="empty">No latest fitness snapshot rows are available.</p>`;
        return;
      }
      nodes.fitnessTable.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>Rank</th>
              <th>Strategy</th>
              <th>Window</th>
              <th>Proposals</th>
              <th>Avg Return</th>
              <th>Fitness</th>
              <th>Last Evaluated</th>
            </tr>
          </thead>
          <tbody>${rows.map((row) => {
            const fitness = Number(row.composite_fitness_score);
            const fitnessClass = fitness > 0 ? "positive" : (fitness < 0 ? "negative" : "");
            const avgReturn = Number(row.avg_realized_return_pct);
            const avgClass = avgReturn > 0 ? "positive" : (avgReturn < 0 ? "negative" : "");
            return `
              <tr>
                <td>${fmtInteger(row.fitness_rank)}</td>
                <td><code>${escapeHtml(row.strategy_id || "unassigned")}</code></td>
                <td>${escapeHtml(row.checkpoint_code || "-")}</td>
                <td>${fmtInteger(row.evaluated_proposals)}</td>
                <td class="${avgClass}">${fmtNumber(row.avg_realized_return_pct, 2)}%</td>
                <td class="${fitnessClass}">${fmtNumber(row.composite_fitness_score, 2)}</td>
                <td>${escapeHtml(fmtDateTime(row.last_evaluated_at))}</td>
              </tr>
            `;
          }).join("")}</tbody>
        </table>
      `;
    }

    function renderStrategyTable(selected, observe) {
      const strategies = Array.isArray(report?.observed?.strategies) ? report.observed.strategies : [];
      nodes.strategyBadge.textContent = `${fmtInteger(strategies.length)} rows`;
      if (!strategies.length) {
        nodes.strategyTable.innerHTML = `<p class="empty">No generated proposal score rows are available for this window.</p>`;
        return;
      }
      const adjustedCounts = countsByStrategy(selected, "adjusted");
      const baseCounts = countsByStrategy(selected, "base");
      const observeCounts = countsByStrategy(observe, "adjusted");
      const paperCounts = countsByStrategy(currentPaperThreshold(), "base");
      const rows = strategies.map((row) => {
        const key = strategyKey(row.strategy_id, row.asset_class);
        const atAdjusted = adjustedCounts.get(key) || 0;
        const atBase = baseCounts.get(key) || 0;
        const atObserve = observeCounts.get(key) || 0;
        const atPaper = paperCounts.get(key) || 0;
        const observeBand = Math.max(0, atObserve - atAdjusted);
        return `
          <tr>
            <td><code>${escapeHtml(row.strategy_id || "unassigned")}</code></td>
            <td>${escapeHtml(row.asset_class || "-")}</td>
            <td>${allowedStrategy(row.strategy_id) ? "yes" : "no"}</td>
            <td>${fmtInteger(row.proposal_count)}</td>
            <td>${fmtInteger(atBase)}</td>
            <td>${fmtInteger(atAdjusted)}</td>
            <td>${fmtInteger(observeBand)}</td>
            <td>${signedInteger(atBase - atPaper)}</td>
            <td>${fmtInteger(row.score_to_trade_count || 0)}</td>
            <td>${fmtNumber(row.avg_base_signal_score, 2)}</td>
            <td>${fmtNumber(row.avg_signal_score, 2)}</td>
            <td>${fmtNumber(row.min_signal_score, 1)}-${fmtNumber(row.max_signal_score, 1)}</td>
          </tr>
        `;
      }).join("");
      nodes.strategyTable.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>Strategy</th>
              <th>Asset</th>
              <th>Allowed</th>
              <th>Total</th>
              <th>Raw At Dial</th>
              <th>Shown At Dial</th>
              <th>Observe Band</th>
              <th>Vs Paper</th>
              <th>Score-To-Trade</th>
              <th>Avg Base</th>
              <th>Avg Score</th>
              <th>Range</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      `;
    }

    function countsByStrategy(threshold, scoreType) {
      const sourceRows = scoreType === "base" ? strategyBaseBuckets() : strategyBuckets();
      const counts = new Map();
      sourceRows.forEach((row) => {
        const score = Number(row.score_bucket);
        if (score < threshold) return;
        const key = strategyKey(row.strategy_id, row.asset_class);
        counts.set(key, (counts.get(key) || 0) + (Number(row.proposal_count) || 0));
      });
      return counts;
    }

    function allowedCountAtThreshold(threshold, scoreType) {
      const sourceRows = scoreType === "base" ? strategyBaseBuckets() : strategyBuckets();
      return sourceRows.reduce((total, row) => {
        const score = Number(row.score_bucket);
        if (score < threshold || !allowedStrategy(row.strategy_id)) return total;
        return total + (Number(row.proposal_count) || 0);
      }, 0);
    }

    function allowedStrategy(strategyId) {
      const allowed = Array.isArray(report?.config?.allowed_strategies)
        ? report.config.allowed_strategies
        : [];
      return allowed.map((value) => String(value).toLowerCase()).includes(String(strategyId || "").toLowerCase());
    }

    function strategyKey(strategyId, assetClass) {
      return `${strategyId || "unassigned"}::${assetClass || "unknown"}`;
    }

    function actualDailyStats() {
      const rows = Array.isArray(report?.health?.recent_daily_realized_pnl)
        ? report.health.recent_daily_realized_pnl
        : [];
      const totalClosed = rows.reduce((total, row) => total + (Number(row.closed_trades) || 0), 0);
      const realizedPnl = rows.reduce((total, row) => total + (Number(row.realized_pnl_usd) || 0), 0);
      const days = rows.length;
      return {
        days,
        totalClosed,
        realizedPnl,
        avgClosedPerDay: days > 0 ? totalClosed / days : 0
      };
    }

    function protectionState() {
      const paper = report?.protection?.paper || {};
      const cfo = report?.protection?.paper_cfo || {};
      const status = String(paper.system_status || paper.status || "").toLowerCase();
      const reason = String(paper.reason || cfo.reason || cfo.decision || "");
      const drawdown = finiteNumber(paper.equity_drawdown_usd, 0);
      const runtimeLimit = finiteNumber(
        paper.max_daily_drawdown_usd,
        finiteNumber(report?.config?.paper_max_daily_drawdown_usd, guardValue())
      );
      const blocked = status === "protected"
        || Boolean(paper.entries_blocked)
        || String(cfo.reason || "").toLowerCase() === "daily_drawdown_limit_reached";
      return {
        blocked,
        drawdown,
        runtimeLimit,
        reason
      };
    }

    function fitnessSummary() {
      const rows = Array.isArray(report?.health?.latest_fitness_snapshot)
        ? report.health.latest_fitness_snapshot
        : [];
      const scores = rows
        .map((row) => Number(row.composite_fitness_score))
        .filter((score) => Number.isFinite(score));
      const positive = scores.filter((score) => score > 0).length;
      const negative = scores.filter((score) => score < 0).length;
      return {
        positive,
        negative,
        best: scores.length ? Math.max(...scores) : null,
        worst: scores.length ? Math.min(...scores) : null
      };
    }

    function renderRecentTable() {
      const rows = Array.isArray(report?.observed?.recent) ? report.observed.recent : [];
      nodes.recentBadge.textContent = `${fmtInteger(rows.length)} rows`;
      if (!rows.length) {
        nodes.recentTable.innerHTML = `<p class="empty">No recent high-score proposals are available for this window.</p>`;
        return;
      }
      nodes.recentTable.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>Proposed</th>
              <th>Lane</th>
              <th>Strategy</th>
              <th>Symbol</th>
              <th>Status</th>
              <th>Base</th>
              <th>Score</th>
              <th>Fitness</th>
              <th>Target</th>
            </tr>
          </thead>
          <tbody>${rows.map((row) => `
            <tr>
              <td>${escapeHtml(fmtDateTime(row.proposed_at))}</td>
              <td>${escapeHtml(`${row.environment || "-"} / ${row.mode || "-"}`)}</td>
              <td><code>${escapeHtml(row.strategy_id || "unassigned")}</code></td>
              <td>${escapeHtml(row.symbol || "-")}</td>
              <td>${escapeHtml(row.allocation_status || "untracked")}</td>
              <td>${fmtNumber(row.base_signal_score, 2)}</td>
              <td>${fmtNumber(row.signal_score, 2)}</td>
              <td>${fmtNumber(row.fitness_composite_score, 2)}</td>
              <td>${fmtNumber(row.target_return_pct, 2)}%</td>
            </tr>
          `).join("")}</tbody>
        </table>
      `;
    }

    function renderEmpty() {
      nodes.cards.innerHTML = "";
      nodes.throughputPanel.innerHTML = "";
      nodes.chart.innerHTML = "";
      nodes.fitnessTable.innerHTML = "";
      nodes.strategyTable.innerHTML = "";
      nodes.recentTable.innerHTML = "";
    }

    function applyScoreEnvValues(values) {
      const score = finiteNumber(
        values.PAPER_MIN_SIGNAL_SCORE_TO_TRADE,
        currentPaperThreshold()
      );
      const observe = finiteNumber(
        values.PAPER_OBSERVE_ONLY_SIGNAL_SCORE_FLOOR,
        currentPaperObserveFloor()
      );
      setPairValue(fields.threshold, score);
      setPairValue(fields.observe, observe);
      nodes.scoreReadout.textContent = fmtNumber(score, 1);
      nodes.observeReadout.textContent = fmtNumber(observe, 1);
      scoreEnvLoaded = true;
      render();
    }

    async function loadScoreEnv() {
      setSaveStatus("Loading .env score values...", "");
      try {
        const response = await fetch("/api/score_numbers_env.php", {
          cache: "no-store",
          headers: { "Accept": "application/json" }
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
          throw new Error(payload.detail || "Could not load .env values.");
        }
        applyScoreEnvValues(payload.values || {});
        setSaveStatus(payload.writable ? "Loaded current .env score values." : ".env loaded but is not writable.", payload.writable ? "good" : "bad");
      } catch (error) {
        setSaveStatus(error instanceof Error ? error.message : "Could not load .env values.", "bad");
      }
    }

    async function saveScoreEnv() {
      const score = thresholdValue();
      const observe = observeValue();
      const confirmed = window.confirm(`Write score ${fmtNumber(score, 1)} and observe floor ${fmtNumber(observe, 1)} to paper and live .env keys? This can change future score-to-trade admission.`);
      if (!confirmed) return;

      nodes.saveEnv.disabled = true;
      setSaveStatus("Writing .env score values...", "");
      try {
        const values = {
          PAPER_MIN_SIGNAL_SCORE_TO_TRADE: score,
          LIVE_MIN_SIGNAL_SCORE_TO_TRADE: score,
          PAPER_OBSERVE_ONLY_SIGNAL_SCORE_FLOOR: observe,
          LIVE_OBSERVE_ONLY_SIGNAL_SCORE_FLOOR: observe
        };
        const response = await fetch("/api/score_numbers_env.php", {
          method: "POST",
          cache: "no-store",
          headers: {
            "Accept": "application/json",
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            ack: "update_score_numbers_env",
            values
          })
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
          throw new Error(payload.detail || "Could not write .env.");
        }
        applyScoreEnvValues(payload.after || values);
        setSaveStatus("Saved score values to .env. Future ticks will use them.", "good");
      } catch (error) {
        setSaveStatus(error instanceof Error ? error.message : "Could not write .env.", "bad");
      } finally {
        nodes.saveEnv.disabled = false;
      }
    }

    async function loadReport({ resetControls = false } = {}) {
      nodes.refresh.disabled = true;
      setStatus("Loading score evidence...", "");
      try {
        const days = fields.days.value || "90";
        const response = await fetch(`/api/score_impact.php?days=${encodeURIComponent(days)}`, {
          cache: "no-store",
          headers: { "Accept": "application/json" }
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
          throw new Error(payload.detail || payload.error || `HTTP ${response.status}`);
        }
        report = payload;
        if (resetControls && !scoreEnvLoaded) {
          setPairValue(fields.threshold, currentPaperThreshold());
          setPairValue(fields.observe, currentPaperObserveFloor());
          nodes.scoreReadout.textContent = fmtNumber(currentPaperThreshold(), 1);
          nodes.observeReadout.textContent = fmtNumber(currentPaperObserveFloor(), 1);
        }
        const configuredGuard = finiteNumber(report?.config?.paper_max_daily_drawdown_usd, guardValue());
        fields.guard.number.value = String(configuredGuard);
        fields.guard.range.value = String(clamp(configuredGuard, Number(fields.guard.range.min), Number(fields.guard.range.max)));
        nodes.guardReadout.textContent = fmtMoney(configuredGuard);
        syncTarget();
        setStatus(`Loaded ${fmtInteger(totalCount())} proposals.`, "good");
        render();
      } catch (error) {
        report = null;
        renderEmpty();
        setStatus(error instanceof Error ? error.message : "Could not load score evidence.", "bad");
      } finally {
        nodes.refresh.disabled = false;
      }
    }

    function setStatus(message, tone) {
      nodes.loadStatus.textContent = message;
      nodes.loadStatus.classList.toggle("bad", tone === "bad");
      nodes.loadStatus.classList.toggle("good", tone === "good");
    }

    function setSaveStatus(message, tone) {
      nodes.saveStatus.textContent = message;
      nodes.saveStatus.classList.toggle("bad", tone === "bad");
      nodes.saveStatus.classList.toggle("good", tone === "good");
    }

    function fmtInteger(value) {
      return (Number(value) || 0).toLocaleString(undefined, { maximumFractionDigits: 0 });
    }

    function signedInteger(value) {
      const number = Number(value) || 0;
      return `${number > 0 ? "+" : ""}${fmtInteger(number)}`;
    }

    function fmtNumber(value, decimals = 1) {
      if (value === null || value === undefined || value === "") return "-";
      const number = Number(value);
      if (!Number.isFinite(number)) return "-";
      return number.toLocaleString(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
      });
    }

    function fmtPct(value) {
      return `${fmtNumber(value * 100, 1)}%`;
    }

    function fmtMoney(value) {
      return `$${fmtNumber(value, 2)}`;
    }

    function finiteNumber(value, fallback = 0) {
      const number = Number(value);
      return Number.isFinite(number) ? number : fallback;
    }

    function part(value, total) {
      const numerator = Number(value) || 0;
      const denominator = Number(total) || 0;
      return denominator > 0 ? numerator / denominator : 0;
    }

    function fmtDateTime(value) {
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return "-";
      return date.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit"
      });
    }

    function escapeHtml(value) {
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    }

    fields.threshold.range.addEventListener("input", () => syncPair(fields.threshold, "range", nodes.scoreReadout, (value) => fmtNumber(value, 1)));
    fields.threshold.number.addEventListener("input", () => syncPair(fields.threshold, "number", nodes.scoreReadout, (value) => fmtNumber(value, 1)));
    fields.observe.range.addEventListener("input", () => syncPair(fields.observe, "range", nodes.observeReadout, (value) => fmtNumber(value, 1)));
    fields.observe.number.addEventListener("input", () => syncPair(fields.observe, "number", nodes.observeReadout, (value) => fmtNumber(value, 1)));
    fields.guard.range.addEventListener("input", () => syncPair(fields.guard, "range", nodes.guardReadout, fmtMoney));
    fields.guard.number.addEventListener("input", () => syncPair(fields.guard, "number", nodes.guardReadout, fmtMoney));
    fields.targetMin.range.addEventListener("input", () => syncTargetPair(fields.targetMin, "range"));
    fields.targetMin.number.addEventListener("input", () => syncTargetPair(fields.targetMin, "number"));
    fields.targetMax.range.addEventListener("input", () => syncTargetPair(fields.targetMax, "range"));
    fields.targetMax.number.addEventListener("input", () => syncTargetPair(fields.targetMax, "number"));
    fields.days.addEventListener("change", () => loadReport({ resetControls: false }));
    nodes.refresh.addEventListener("click", () => loadReport({ resetControls: false }));
    nodes.saveEnv.addEventListener("click", saveScoreEnv);

    async function boot() {
      await loadReport({ resetControls: true });
      await loadScoreEnv();
    }

    boot();
  </script>
</body>
</html>

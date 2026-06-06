<?php
declare(strict_types=1);

header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');

require __DIR__ . '/api/snapshot_cache.php';
require __DIR__ . '/navigation.php';

$initialSnapshotJson = slotNumbersInitialSnapshotJson();

function slotNumbersInitialSnapshotJson(): string
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
  <title>Centaur Simple Slot Numbers</title>
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
    input {
      font: inherit;
    }

    .shell {
      width: min(1120px, calc(100% - 32px));
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
      max-width: 720px;
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

    .grid {
      display: grid;
      grid-template-columns: minmax(300px, 0.82fr) minmax(0, 1.18fr);
      gap: 18px;
      align-items: start;
    }

    .grid > section {
      min-width: 0;
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

    .controls {
      display: grid;
      gap: 18px;
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

    input[type="number"] {
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

    .rule {
      margin: 0;
      border-top: 1px solid var(--line);
      background: rgba(238, 245, 241, 0.52);
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
      padding: 13px 16px 16px;
    }

    .results {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    .result {
      min-height: 142px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      padding: 16px;
      box-shadow: 0 8px 22px rgba(18, 31, 32, 0.05);
      min-width: 0;
    }

    .result.profit {
      border-color: rgba(37, 139, 87, 0.35);
    }

    .result.loss {
      border-color: rgba(201, 75, 95, 0.38);
    }

    .result.cost {
      border-color: rgba(201, 143, 19, 0.38);
    }

    .result.daily {
      grid-column: 1 / -1;
      min-height: 132px;
      border-color: rgba(15, 139, 141, 0.36);
      background: linear-gradient(180deg, #ffffff, #f8fcfb);
    }

    .result-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    .result-value {
      margin-top: 14px;
      font-size: clamp(30px, 4vw, 52px);
      font-weight: 950;
      line-height: 0.95;
      overflow-wrap: anywhere;
    }

    .result-detail {
      margin-top: 10px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.35;
    }

    .summary {
      margin-top: 18px;
      padding: 16px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfdfc;
      color: var(--ink);
      font-size: 18px;
      font-weight: 850;
      line-height: 1.45;
    }

    .muted {
      color: var(--muted);
      font-size: 13px;
      font-weight: 650;
    }

    .env-table {
      margin-top: 18px;
    }

    .reality-panel {
      margin-top: 18px;
    }

    .reality-actions {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.76);
    }

    .reality-grid {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 12px;
      padding: 16px;
    }

    .mini-result {
      min-width: 0;
      min-height: 106px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfdfc;
      padding: 12px;
    }

    .mini-value {
      margin-top: 10px;
      color: var(--ink);
      font-size: 28px;
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

    .reality-verdict {
      margin: 0 16px 16px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface-2);
      padding: 14px;
      color: var(--ink);
      font-weight: 800;
      line-height: 1.4;
    }

    .reality-verdict.good {
      border-color: rgba(37, 139, 87, 0.35);
      background: rgba(37, 139, 87, 0.08);
    }

    .reality-verdict.warn {
      border-color: rgba(201, 143, 19, 0.38);
      background: rgba(201, 143, 19, 0.09);
    }

    .reality-verdict.bad {
      border-color: rgba(201, 75, 95, 0.38);
      background: rgba(201, 75, 95, 0.08);
    }

    .env-actions {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 16px;
      border-top: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.76);
    }

    .save-status {
      color: var(--muted);
      font-size: 13px;
      font-weight: 750;
    }

    .save-status.good {
      color: var(--green);
    }

    .save-status.bad {
      color: var(--rose);
    }

    .table-wrap {
      max-width: 100%;
      overflow-x: auto;
    }

    table {
      width: 100%;
      border-collapse: collapse;
    }

    .env-table table {
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

    td:nth-child(2) {
      color: var(--ink);
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-weight: 850;
      white-space: nowrap;
    }

    code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-weight: 800;
    }

    @media (max-width: 900px) {
      .grid {
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

      .results {
        grid-template-columns: 1fr;
      }

      .reality-grid {
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
        <h1>Simple Slot Numbers</h1>
        <p class="lede">Pick the average winning slot. The page gives the simple sell-at-profit number and the loss number that keeps losses smaller than wins.</p>
      </div>
      <div class="toolbar centaur-menu-toolbar">
        <?php centaurRenderNavigation('/slot-economics.php'); ?>
      </div>
    </header>

    <section class="grid">
      <aside class="panel" aria-label="Simple slot controls">
        <div class="panel-head">
          <div class="panel-title">One Slider</div>
          <span class="badge">$10 slot default</span>
        </div>
        <div class="controls">
          <div class="control">
            <div class="control-top">
              <label for="avg-win">Avg Win Per Winning Slot</label>
              <span id="avg-win-readout" class="readout">0.50%</span>
            </div>
            <div class="number-row">
              <input id="avg-win" type="range" min="0.1" max="5" step="0.05" value="0.5">
              <input id="avg-win-number" type="number" min="0.1" max="20" step="0.05" value="0.5">
            </div>
          </div>

          <div class="control">
            <div class="control-top">
              <label for="slot-size">Slot Size</label>
              <span id="slot-size-readout" class="readout">$10.00</span>
            </div>
            <div class="number-row">
              <input id="slot-size" type="range" min="1" max="100" step="1" value="10">
              <input id="slot-size-number" type="number" min="1" max="10000" step="1" value="10">
            </div>
          </div>

          <div class="control">
            <div class="control-top">
              <label for="slots-per-day">Estimated Trades Per Day</label>
              <span id="slots-per-day-readout" class="readout">10</span>
            </div>
            <div class="number-row">
              <input id="slots-per-day" type="range" min="1" max="200" step="1" value="10">
              <input id="slots-per-day-number" type="number" min="1" max="500" step="1" value="10">
            </div>
          </div>

          <div class="control">
            <div class="control-top">
              <label for="losing-slots-per-day">Estimated Losing Trades Per Day</label>
              <span id="losing-slots-per-day-readout" class="readout">1</span>
            </div>
            <div class="number-row">
              <input id="losing-slots-per-day" type="range" min="0" max="200" step="1" value="1">
              <input id="losing-slots-per-day-number" type="number" min="0" max="500" step="1" value="1">
            </div>
          </div>
        </div>
        <p class="rule">Simple rule used here: sell winners at the slider value, and cap losses at half that value. The day estimate starts from actual paper fills, rounds any broker-ledger loss-equivalent fit to whole trades, then subtracts rough costs.</p>
      </aside>

      <section>
        <div class="results" aria-label="Calculated simple slot numbers">
          <article class="result daily">
            <div class="result-label">Estimated Profit Per Day</div>
            <div id="daily-profit" class="result-value">$0.00</div>
            <div id="daily-profit-detail" class="result-detail">10 slots/day, 9 winners, 1 loser, after rough costs</div>
          </article>

          <article class="result daily">
            <div class="result-label">Avg Win Needed For $0.50/day</div>
            <div id="daily-target-win" class="result-value">1.04%</div>
            <div id="daily-target-detail" class="result-detail">but one win covers one loss from about 1.52%</div>
          </article>

          <article class="result">
            <div class="result-label">Estimated Wins / Losses Per Day</div>
            <div id="estimated-day-shape" class="result-value">9 / 1</div>
            <div id="estimated-day-detail" class="result-detail">from actual data, editable above</div>
          </article>

          <article class="result">
            <div class="result-label">Actual Paper Wins / Losses Per Day</div>
            <div id="actual-day-shape" class="result-value">- / -</div>
            <div id="actual-day-detail" class="result-detail">latest closed paper data</div>
          </article>

          <article class="result profit">
            <div class="result-label">Sell For Small Profit At</div>
            <div id="profit-sell" class="result-value">0.50%</div>
            <div id="profit-detail" class="result-detail">$0.05 gross on a $10 slot</div>
          </article>

          <article class="result loss">
            <div class="result-label">Sell Before Loss Gets Bigger Than</div>
            <div id="loss-sell" class="result-value">0.25%</div>
            <div id="loss-detail" class="result-detail">$0.03 max loss on a $10 slot</div>
          </article>

          <article class="result">
            <div class="result-label">Wins Needed To Repair One Loss</div>
            <div id="repair-wins" class="result-value">6</div>
            <div id="repair-detail" class="result-detail">after rough costs</div>
          </article>

          <article class="result cost">
            <div class="result-label">Rough Cost Drag</div>
            <div id="cost-drag" class="result-value">0.38%</div>
            <div id="cost-detail" class="result-detail">about $0.04 on a $10 slot</div>
          </article>
        </div>

        <div id="summary" class="summary">
          With a 0.50% winning slot, the simple shape is profit at 0.50% and loss at 0.25%.
          <div id="one-for-one-note" class="muted">One win covers one loss from about 1.52% on a $10 slot.</div>
          <div id="cost-note" class="muted">At this size, rough costs are large compared with the target.</div>
        </div>

        <section class="panel reality-panel" aria-label="Dial evidence check">
          <div class="panel-head">
            <div class="panel-title">Dial Reality Check</div>
            <span class="badge">audit-only</span>
          </div>
          <div class="reality-actions">
            <button id="check-dials" class="button primary" type="button">Check Dials Against Evidence</button>
            <span id="dial-check-status" class="save-status">Uses stored exit-quality audits from future exits.</span>
          </div>
          <div class="reality-grid">
            <article class="mini-result">
              <div class="result-label">Touched Profit Target</div>
              <div id="target-touch-rate" class="mini-value">-</div>
              <div id="target-touch-detail" class="mini-detail">waiting for check</div>
            </article>
            <article class="mini-result">
              <div class="result-label">Sold At Target</div>
              <div id="target-exit-rate" class="mini-value">-</div>
              <div id="target-exit-detail" class="mini-detail">waiting for check</div>
            </article>
            <article class="mini-result">
              <div class="result-label">Loss Cap Breached</div>
              <div id="loss-breach-rate" class="mini-value">-</div>
              <div id="loss-breach-detail" class="mini-detail">waiting for check</div>
            </article>
          </div>
          <div id="dial-check-verdict" class="reality-verdict">Change the sliders, then run the check.</div>
        </section>

        <section class="panel env-table" aria-label="Environment values to set">
          <div class="panel-head">
            <div class="panel-title">Values To Put In .env</div>
            <span class="badge">read-only suggestion</span>
          </div>
          <div class="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>.env key</th>
                  <th>Value</th>
                  <th>What it controls</th>
                </tr>
              </thead>
              <tbody id="env-body"></tbody>
            </table>
          </div>
          <div class="env-actions">
            <button id="save-env" class="button danger" type="button">Write These Values To .env</button>
            <span id="save-status" class="save-status">Loads current .env values on page open.</span>
          </div>
          <p class="rule">These numbers are suggestions from the slider, not automatic changes. Crypto stop loss currently has a hard 1% floor in code, and volatility-breakout equity stops are ATR-based rather than a fixed percent.</p>
        </section>
      </section>
    </section>
  </main>

  <script>
    const embeddedSnapshot = <?php echo $initialSnapshotJson; ?>;

    const fields = {
      avgWin: bindNumber("avg-win"),
      slotSize: bindNumber("slot-size"),
      slotsPerDay: bindNumber("slots-per-day"),
      losingSlotsPerDay: bindNumber("losing-slots-per-day")
    };

    const nodes = {
      avgWinReadout: document.getElementById("avg-win-readout"),
      slotSizeReadout: document.getElementById("slot-size-readout"),
      slotsPerDayReadout: document.getElementById("slots-per-day-readout"),
      losingSlotsPerDayReadout: document.getElementById("losing-slots-per-day-readout"),
      dailyProfit: document.getElementById("daily-profit"),
      dailyProfitDetail: document.getElementById("daily-profit-detail"),
      dailyTargetWin: document.getElementById("daily-target-win"),
      dailyTargetDetail: document.getElementById("daily-target-detail"),
      estimatedDayShape: document.getElementById("estimated-day-shape"),
      estimatedDayDetail: document.getElementById("estimated-day-detail"),
      actualDayShape: document.getElementById("actual-day-shape"),
      actualDayDetail: document.getElementById("actual-day-detail"),
      profitSell: document.getElementById("profit-sell"),
      profitDetail: document.getElementById("profit-detail"),
      lossSell: document.getElementById("loss-sell"),
      lossDetail: document.getElementById("loss-detail"),
      repairWins: document.getElementById("repair-wins"),
      repairDetail: document.getElementById("repair-detail"),
      costDrag: document.getElementById("cost-drag"),
      costDetail: document.getElementById("cost-detail"),
      summary: document.getElementById("summary"),
      oneForOneNote: document.getElementById("one-for-one-note"),
      costNote: document.getElementById("cost-note"),
      envBody: document.getElementById("env-body"),
      saveEnv: document.getElementById("save-env"),
      saveStatus: document.getElementById("save-status"),
      checkDials: document.getElementById("check-dials"),
      dialCheckStatus: document.getElementById("dial-check-status"),
      targetTouchRate: document.getElementById("target-touch-rate"),
      targetTouchDetail: document.getElementById("target-touch-detail"),
      targetExitRate: document.getElementById("target-exit-rate"),
      targetExitDetail: document.getElementById("target-exit-detail"),
      lossBreachRate: document.getElementById("loss-breach-rate"),
      lossBreachDetail: document.getElementById("loss-breach-detail"),
      dialCheckVerdict: document.getElementById("dial-check-verdict")
    };

    let pendingEnvValues = {};
    let dayShapeSource = "historical closed-trade average";
    let lastDayTradeModel = null;
    let autoFitDayShape = true;

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

    function syncField(fieldName, source) {
      const field = fields[fieldName];
      const sourceNode = field[source];
      const targetNode = source === "range" ? field.number : field.range;
      const next = normalizeFieldValue(
        fieldName,
        clamp(sourceNode.value, Number(sourceNode.min), Number(sourceNode.max))
      );
      sourceNode.value = String(next);
      targetNode.value = String(clamp(next, Number(targetNode.min), Number(targetNode.max)));
    }

    function normalizeFieldValue(fieldName, value) {
      const source = Number(value);
      if (!Number.isFinite(source)) {
        return 0;
      }
      if (fieldName === "slotsPerDay" || fieldName === "losingSlotsPerDay") {
        return Math.round(source);
      }
      return source;
    }

    function valueOf(fieldName) {
      return Number(fields[fieldName].number.value);
    }

    function fmtCurrency(value) {
      return `$${value.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      })}`;
    }

    function fmtPct(value) {
      return `${value.toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      })}%`;
    }

    function render() {
      const avgWinPct = Math.max(0.01, valueOf("avgWin"));
      const slotSize = Math.max(0.01, valueOf("slotSize"));
      const slotsPerDay = Math.max(1, Math.round(valueOf("slotsPerDay")));
      const losingSlotsPerDay = Math.min(
        slotsPerDay,
        Math.round(Math.max(0, valueOf("losingSlotsPerDay")))
      );
      const winningSlotsPerDay = slotsPerDay - losingSlotsPerDay;
      const lossPct = avgWinPct / 2;
      const winUsd = slotSize * avgWinPct / 100;
      const lossUsd = slotSize * lossPct / 100;
      const costUsd = 0.03 + (slotSize * 0.0008);
      const costPct = costUsd / slotSize * 100;
      const netWinUsd = winUsd - costUsd;
      const lossWithCostUsd = lossUsd + costUsd;
      const repairWins = netWinUsd > 0 ? Math.ceil(lossWithCostUsd / netWinUsd) : Infinity;
      const oneForOneWinPct = ((4 * costUsd) / slotSize) * 100;
      const estimatedDailyProfitUsd = (
        (winningSlotsPerDay * netWinUsd)
        - (losingSlotsPerDay * lossWithCostUsd)
      );
      const dailyTargetUsd = 0.5;
      const dailyTargetDenominator = slotSize * (
        (winningSlotsPerDay / 100) - ((losingSlotsPerDay * 0.5) / 100)
      );
      const dailyTargetWinPct = (
        dailyTargetDenominator > 0
          ? (dailyTargetUsd + ((winningSlotsPerDay + losingSlotsPerDay) * costUsd))
            / dailyTargetDenominator
          : Infinity
      );
      const meanReversionFloorActualPct = 1;
      const meanReversionShadowStopPct = lossPct >= meanReversionFloorActualPct
        ? lossPct / 0.9
        : meanReversionFloorActualPct / 0.9;
      const cryptoStopPct = Math.max(lossPct, 1);

      nodes.avgWinReadout.textContent = fmtPct(avgWinPct);
      nodes.slotSizeReadout.textContent = fmtCurrency(slotSize);
      nodes.slotsPerDayReadout.textContent = fmtNumber(slotsPerDay, 0);
      nodes.losingSlotsPerDayReadout.textContent = fmtNumber(losingSlotsPerDay, 0);
      nodes.dailyProfit.textContent = fmtCurrency(estimatedDailyProfitUsd);
      nodes.dailyProfitDetail.textContent = `${fmtNumber(winningSlotsPerDay, 0)} ${plural(winningSlotsPerDay, "winner")} x ${fmtCurrency(netWinUsd)} net - ${fmtNumber(losingSlotsPerDay, 0)} ${plural(losingSlotsPerDay, "loser")} x ${fmtCurrency(lossWithCostUsd)} drag`;
      nodes.dailyTargetWin.textContent = Number.isFinite(dailyTargetWinPct) ? fmtPct(dailyTargetWinPct) : "-";
      nodes.dailyTargetDetail.textContent = `for ${fmtCurrency(dailyTargetUsd)}/day; one-win-covers-one-loss starts around ${fmtPct(oneForOneWinPct)}`;
      nodes.estimatedDayShape.textContent = `${fmtNumber(winningSlotsPerDay, 0)} / ${fmtNumber(losingSlotsPerDay, 0)}`;
      nodes.estimatedDayDetail.textContent = `${fmtNumber(slotsPerDay, 0)} total estimated trades/day; ${dayShapeSource}`;
      nodes.profitSell.textContent = fmtPct(avgWinPct);
      nodes.profitDetail.textContent = `${fmtCurrency(winUsd)} gross on a ${fmtCurrency(slotSize)} slot`;
      nodes.lossSell.textContent = fmtPct(lossPct);
      nodes.lossDetail.textContent = `${fmtCurrency(lossUsd)} max loss on a ${fmtCurrency(slotSize)} slot`;
      nodes.repairWins.textContent = Number.isFinite(repairWins) ? String(Math.max(1, repairWins)) : "-";
      nodes.repairDetail.textContent = netWinUsd > 0
        ? `${fmtCurrency(lossWithCostUsd)} one-loss drag divided by ${fmtCurrency(netWinUsd)} net per win`
        : "profit target is smaller than rough costs";
      nodes.costDrag.textContent = fmtPct(costPct);
      nodes.costDetail.textContent = `about ${fmtCurrency(costUsd)} on a ${fmtCurrency(slotSize)} slot`;
      nodes.summary.firstChild.textContent = `With a ${fmtPct(avgWinPct)} winning slot, the simple shape is profit at ${fmtPct(avgWinPct)} and loss at ${fmtPct(lossPct)}.`;
      nodes.oneForOneNote.textContent = `One win covers one loss from about ${fmtPct(oneForOneWinPct)} on a ${fmtCurrency(slotSize)} slot.`;
      nodes.costNote.textContent = costPct >= lossPct
        ? `The ${nodes.repairWins.textContent} means the profit target is probably too small for this slot size.`
        : `The ${nodes.repairWins.textContent} means that many winning slots are needed to recover one losing slot after rough costs.`;
      nodes.envBody.innerHTML = [
        [
          "PAPER_EXECUTION_DEFAULT_NOTIONAL_USD",
          fmtEnvNumber(Math.min(slotSize, 10)),
          slotSize > 10
            ? "Notional is capped at 10 from this page to avoid widening risk."
            : "Paper slot notional."
        ],
        [
          "LIVE_EXECUTION_DEFAULT_NOTIONAL_USD",
          fmtEnvNumber(Math.min(slotSize, 10)),
          slotSize > 10
            ? "Live follower notional is capped at 10 from this page."
            : "Live follower slot notional."
        ],
        [
          "PAPER_EXECUTION_PROFIT_CAPTURE_PCT",
          fmtEnvNumber(avgWinPct),
          "Paper sell-for-profit threshold."
        ],
        [
          "LIVE_EXECUTION_PROFIT_CAPTURE_PCT",
          fmtEnvNumber(avgWinPct),
          "Live follower sell-for-profit threshold."
        ],
        [
          "SHADOW_STOP_LOSS_PCT",
          fmtEnvNumber(meanReversionShadowStopPct),
          lossPct < meanReversionFloorActualPct
            ? `Mean reversion has a 1% code floor, so ${fmtPct(lossPct)} needs a code change. This value gives the minimum effective 1% stop.`
            : `Mean reversion uses 90% of this, giving about ${fmtPct(lossPct)} loss cap.`
        ],
        [
          "PAPER_CRYPTO_MOMENTUM_STOP_LOSS_PCT",
          fmtEnvNumber(cryptoStopPct),
          cryptoStopPct > lossPct
            ? "Crypto code floors this at 1%, so the slider loss cap is not reachable without a code change."
            : "Paper crypto stop-loss threshold."
        ],
        [
          "LIVE_CRYPTO_MOMENTUM_STOP_LOSS_PCT",
          fmtEnvNumber(cryptoStopPct),
          cryptoStopPct > lossPct
            ? "Live crypto follows the same 1% floor."
            : "Live crypto stop-loss threshold."
        ]
      ].map((row) => `
        <tr>
          <td><code>${escapeHtml(row[0])}</code></td>
          <td>${escapeHtml(row[1])}</td>
          <td>${escapeHtml(row[2])}</td>
        </tr>
      `).join("");
      pendingEnvValues = Object.fromEntries(
        Array.from(nodes.envBody.querySelectorAll("tr")).map((row) => {
          const cells = Array.from(row.children);
          return [cells[0].textContent.trim(), cells[1].textContent.trim()];
        })
      );
    }

    function fmtEnvNumber(value) {
      return Number(value.toFixed(4)).toString();
    }

    function escapeHtml(value) {
      return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
    }

    Object.entries(fields).forEach(([fieldName, field]) => {
      field.range.addEventListener("input", () => {
        syncField(fieldName, "range");
        handleFieldInput(fieldName);
      });
      field.number.addEventListener("input", () => {
        syncField(fieldName, "number");
        handleFieldInput(fieldName);
      });
    });

    nodes.saveEnv.addEventListener("click", saveEnvValues);
    nodes.checkDials.addEventListener("click", checkDialReality);

    function handleFieldInput(fieldName) {
      if ((fieldName === "avgWin" || fieldName === "slotSize") && autoFitDayShape) {
        applyLastDayTradeModel();
        return;
      }
      if (fieldName === "slotsPerDay" || fieldName === "losingSlotsPerDay") {
        autoFitDayShape = false;
        dayShapeSource = "manual day shape; not broker-P/L fitted";
      }
      render();
    }

    function applyActualDefaults() {
      const metrics = embeddedSnapshot && typeof embeddedSnapshot === "object"
        ? embeddedSnapshot.paper_trade_outcome_metrics || {}
        : {};
      const wins = Number(metrics.wins);
      const losses = Number(metrics.losses);
      const flats = Number(metrics.flats) || 0;
      const days = Math.max(Number(metrics.observed_days) || 0, 0);

      if (!Number.isFinite(wins) || !Number.isFinite(losses) || days <= 0) {
        return;
      }

      const tradesPerDay = (wins + losses + flats) / days;
      const lossesPerDay = losses / days;
      setField("slotsPerDay", Math.round(tradesPerDay));
      setField("losingSlotsPerDay", Math.round(lossesPerDay));
      dayShapeSource = `historical closed-trade average; rounded from ${fmtNumber(tradesPerDay, 1)} trades/day and ${fmtNumber(lossesPerDay, 1)} losses/day`;
    }

    async function loadEnvDefaults() {
      try {
        const response = await fetch("/api/slot_numbers_env.php", {
          cache: "no-store",
          headers: { "Accept": "application/json" }
        });
        const payload = await response.json();
        if (!payload.ok || !payload.values) {
          throw new Error(payload.detail || "Could not load .env values.");
        }
        const values = payload.values;
        const profitPct = envPercentToDisplay(values.PAPER_EXECUTION_PROFIT_CAPTURE_PCT);
        const slotSize = numberOrNull(values.PAPER_EXECUTION_DEFAULT_NOTIONAL_USD);
        if (profitPct !== null) {
          setField("avgWin", profitPct);
        }
        if (slotSize !== null) {
          setField("slotSize", slotSize);
        }
        setSaveStatus("Loaded current .env values.", "good");
        render();
      } catch (error) {
        setSaveStatus(error instanceof Error ? error.message : "Could not load .env values.", "bad");
      }
    }

    async function loadLastDayTradeDefaults() {
      try {
        const response = await fetch("/api/recent_trades.php?hours=24&broker_id=alpaca_paper", {
          cache: "no-store",
          headers: { "Accept": "application/json" }
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
          throw new Error(payload.detail || "Could not load last-day trades.");
        }
        const profitLockPayload = await loadProfitLockReviewPayload();
        const dayFit = resolveDayFit(payload, profitLockPayload);

        const fills = Number(payload.fills?.sampled);
        const closedWins = Number(payload.closed_trades?.wins);
        const closedLosses = Number(payload.closed_trades?.losses);
        const lossRate = Number(payload.closed_trades?.loss_rate);
        const brokerDayChange = Number(payload.broker_account?.day_change);
        if (!Number.isFinite(fills) || fills <= 0) {
          return;
        }

        lastDayTradeModel = {
          fills,
          closedWins,
          closedLosses,
          lossRate,
          brokerDayChange,
          fitDayChange: dayFit.dayChange,
          fitLabel: dayFit.label
        };
        autoFitDayShape = true;
        applyLastDayTradeModel();
      } catch (error) {
        dayShapeSource = "historical closed-trade average";
      }
    }

    async function loadProfitLockReviewPayload() {
      try {
        const response = await fetch("/api/profit_lock_review.php?hours=24&broker_id=alpaca_paper", {
          cache: "no-store",
          headers: { "Accept": "application/json" }
        });
        const payload = await response.json();
        return response.ok && payload.ok ? payload : null;
      } catch (error) {
        return null;
      }
    }

    function resolveDayFit(recentPayload, profitLockPayload) {
      const brokerDayChange = Number(recentPayload?.broker_account?.day_change);
      const finalDayChange = Number(profitLockPayload?.account_curve?.final?.day_change);
      const carryoverPnl = Number(profitLockPayload?.trade_review?.carryover_closes?.realized_pnl_usd);
      if (Number.isFinite(finalDayChange) && Number.isFinite(carryoverPnl)) {
        const freshDayChange = finalDayChange - carryoverPnl;
        return {
          dayChange: freshDayChange,
          label: `carryover-adjusted fresh P/L ${fmtCurrency(freshDayChange)} (broker ${fmtCurrency(finalDayChange)}, carryover ${fmtCurrency(carryoverPnl)})`
        };
      }
      if (Number.isFinite(brokerDayChange)) {
        return {
          dayChange: brokerDayChange,
          label: `broker day P/L ${fmtCurrency(brokerDayChange)}`
        };
      }
      return {
        dayChange: null,
        label: ""
      };
    }

    function applyLastDayTradeModel() {
      if (!lastDayTradeModel) {
        render();
        return;
      }
      const {
        fills,
        closedWins,
        closedLosses,
        lossRate,
        brokerDayChange,
        fitDayChange,
        fitLabel
      } = lastDayTradeModel;
      const dayChangeForFit = Number.isFinite(fitDayChange) ? fitDayChange : brokerDayChange;
      const avgWinPct = Math.max(0.01, valueOf("avgWin"));
      const slotSize = Math.max(0.01, valueOf("slotSize"));
      const lossPct = avgWinPct / 2;
      const winUsd = slotSize * avgWinPct / 100;
      const lossUsd = slotSize * lossPct / 100;
      const costUsd = 0.03 + (slotSize * 0.0008);
      const netWinUsd = winUsd - costUsd;
      const lossWithCostUsd = lossUsd + costUsd;
      const lossEquivalent = (
        Number.isFinite(dayChangeForFit) && netWinUsd + lossWithCostUsd > 0
          ? clamp(
              ((fills * netWinUsd) - dayChangeForFit) / (netWinUsd + lossWithCostUsd),
              0,
              fills
            )
          : fills * (Number.isFinite(lossRate) ? lossRate : 0.5)
      );
      setField("slotsPerDay", Math.round(fills));
      setField("losingSlotsPerDay", Math.round(lossEquivalent));
      dayShapeSource = Number.isFinite(dayChangeForFit)
        ? `last 24h fill model rounded from ${fmtNumber(lossEquivalent, 1)} loss-equivalent fills to ${fitLabel}`
        : `last 24h fill model rounded from ${fmtNumber(lossEquivalent, 1)} losses (${fmtNumber(fills, 0)} fills x ${fmtNumber((lossRate || 0.5) * 100, 1)}% closed loss rate)`;

      if (Number.isFinite(closedWins) && Number.isFinite(closedLosses)) {
        nodes.actualDayShape.textContent = `${fmtNumber(closedWins, 0)} / ${fmtNumber(closedLosses, 0)}`;
        nodes.actualDayDetail.textContent = `${fmtNumber(fills, 0)} fills; actual closed wins/losses, model rounds loss-equivalent fit`;
      }
      render();
    }

    function envPercentToDisplay(value) {
      const number = numberOrNull(value);
      if (number === null) return null;
      if (number > 0 && number < 0.1) {
        return number * 100;
      }
      return number;
    }

    function numberOrNull(value) {
      const number = Number(value);
      return Number.isFinite(number) ? number : null;
    }

    async function saveEnvValues() {
      const ok = window.confirm("Write the displayed risk/exit values to .env? This can change paper/live follower exit behaviour on future ticks.");
      if (!ok) {
        return;
      }
      nodes.saveEnv.disabled = true;
      setSaveStatus("Writing .env...", "");
      try {
        const response = await fetch("/api/slot_numbers_env.php", {
          method: "POST",
          cache: "no-store",
          headers: {
            "Accept": "application/json",
            "Content-Type": "application/json"
          },
          body: JSON.stringify({
            ack: "update_slot_numbers_env",
            values: pendingEnvValues
          })
        });
        const payload = await response.json();
        if (!payload.ok) {
          throw new Error(payload.detail || "Could not write .env.");
        }
        setSaveStatus("Saved to .env. Future ticks will use the new values.", "good");
      } catch (error) {
        setSaveStatus(error instanceof Error ? error.message : "Could not write .env.", "bad");
      } finally {
        nodes.saveEnv.disabled = false;
      }
    }

    async function checkDialReality() {
      const avgWinPct = Math.max(0.01, valueOf("avgWin"));
      const slotSize = Math.max(0.01, valueOf("slotSize"));
      const tradesPerDay = Math.max(1, Math.round(valueOf("slotsPerDay")));
      const lossesPerDay = Math.min(tradesPerDay, Math.round(Math.max(0, valueOf("losingSlotsPerDay"))));
      const lossCapPct = avgWinPct / 2;
      const params = new URLSearchParams({
        hours: "168",
        broker_id: "alpaca_paper",
        target_win_pct: String(avgWinPct),
        loss_cap_pct: String(lossCapPct),
        slot_size_usd: String(slotSize),
        trades_per_day: String(tradesPerDay),
        losses_per_day: String(lossesPerDay)
      });

      nodes.checkDials.disabled = true;
      setDialCheckStatus("Checking stored exit evidence...", "");
      try {
        const response = await fetch(`/api/slot_dial_reality.php?${params.toString()}`, {
          cache: "no-store",
          headers: { "Accept": "application/json" }
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
          throw new Error(payload.detail || payload.reason || "Could not check dials.");
        }
        renderDialReality(payload);
      } catch (error) {
        setDialCheckStatus(error instanceof Error ? error.message : "Could not check dials.", "bad");
      } finally {
        nodes.checkDials.disabled = false;
      }
    }

    function renderDialReality(payload) {
      const sample = payload.sample || {};
      const results = payload.results || {};
      const verdict = payload.verdict || {};
      const tracked = Number(sample.tracked_exit_quality_count) || 0;
      const sampled = Number(sample.sell_orders_sampled) || 0;
      const missing = Number(sample.missing_or_unobserved_audit_count) || 0;

      nodes.targetTouchRate.textContent = fmtPct((Number(results.target_touch_rate) || 0) * 100);
      nodes.targetTouchDetail.textContent = `${fmtNumber(Number(results.target_touch_count) || 0, 0)} of ${fmtNumber(tracked, 0)} tracked exits; projected ${fmtNumber(Number(results.projected_target_touches_per_day) || 0, 1)}/day`;
      nodes.targetExitRate.textContent = fmtPct((Number(results.exited_at_or_above_target_rate) || 0) * 100);
      nodes.targetExitDetail.textContent = `${fmtNumber(Number(results.exited_at_or_above_target_count) || 0, 0)} sold at/above target; ${fmtNumber(Number(results.faded_after_touch_count) || 0, 0)} faded after touching`;
      nodes.lossBreachRate.textContent = fmtPct((Number(results.loss_cap_breach_rate) || 0) * 100);
      nodes.lossBreachDetail.textContent = `${fmtNumber(Number(results.loss_cap_breach_count) || 0, 0)} breached; projected ${fmtNumber(Number(results.projected_loss_breaches_per_day) || 0, 1)}/day`;

      const action = String(verdict.action || "");
      const tone = action.includes("plausible")
        ? "good"
        : (action.includes("not_enough") ? "warn" : "bad");
      nodes.dialCheckVerdict.classList.toggle("good", tone === "good");
      nodes.dialCheckVerdict.classList.toggle("warn", tone === "warn");
      nodes.dialCheckVerdict.classList.toggle("bad", tone === "bad");
      nodes.dialCheckVerdict.textContent = `${verdict.summary || "Reality check complete."} Rough model P/L: ${fmtCurrency(Number(results.rough_projected_pnl_usd) || 0)}. Authority: ${verdict.authority || "none"}.`;
      setDialCheckStatus(`${fmtNumber(sampled, 0)} sells sampled, ${fmtNumber(tracked, 0)} tracked audits, ${fmtNumber(missing, 0)} not yet trackable.`, tone === "bad" ? "bad" : "good");
    }

    function setSaveStatus(message, tone) {
      nodes.saveStatus.textContent = message;
      nodes.saveStatus.classList.toggle("good", tone === "good");
      nodes.saveStatus.classList.toggle("bad", tone === "bad");
    }

    function setDialCheckStatus(message, tone) {
      nodes.dialCheckStatus.textContent = message;
      nodes.dialCheckStatus.classList.toggle("good", tone === "good");
      nodes.dialCheckStatus.classList.toggle("bad", tone === "bad");
    }

    function setField(fieldName, value) {
      const field = fields[fieldName];
      const numberMin = Number(field.number.min);
      const numberMax = Number(field.number.max);
      const next = normalizeFieldValue(fieldName, clamp(value, numberMin, numberMax));
      field.number.value = String(next);
      field.range.value = String(clamp(next, Number(field.range.min), Number(field.range.max)));
    }

    function renderActualDayShape() {
      const metrics = embeddedSnapshot && typeof embeddedSnapshot === "object"
        ? embeddedSnapshot.paper_trade_outcome_metrics || {}
        : {};
      const wins = Number(metrics.wins);
      const losses = Number(metrics.losses);
      const days = Math.max(Number(metrics.observed_days) || 0, 0);
      const closedTrades = Number(metrics.closed_trades) || 0;

      if (!Number.isFinite(wins) || !Number.isFinite(losses) || days <= 0 || closedTrades <= 0) {
        nodes.actualDayShape.textContent = "- / -";
        nodes.actualDayDetail.textContent = "no closed paper data available";
        return;
      }

      const winsPerDay = wins / days;
      const lossesPerDay = losses / days;
      nodes.actualDayShape.textContent = `${fmtNumber(winsPerDay, 1)} / ${fmtNumber(lossesPerDay, 1)}`;
      nodes.actualDayDetail.textContent = `${closedTrades} closed trades over ${fmtNumber(days, 1)} days`;
    }

    function fmtNumber(value, decimals = 1) {
      return value.toLocaleString(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
      });
    }

    function plural(count, word) {
      return count === 1 ? word : `${word}s`;
    }

    async function initialize() {
      applyActualDefaults();
      renderActualDayShape();
      render();
      await loadEnvDefaults();
      await loadLastDayTradeDefaults();
    }

    initialize();
  </script>
</body>
</html>

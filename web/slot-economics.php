<?php
declare(strict_types=1);

header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');

require __DIR__ . '/api/snapshot_cache.php';

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
      <nav class="toolbar" aria-label="Primary navigation">
        <a class="button primary" href="/slot-economics.php">Slot Numbers</a>
        <a class="button" href="/">Slot Compounding</a>
        <a class="button" href="/dashboard.php">Dashboard</a>
      </nav>
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
              <input id="slots-per-day" type="range" min="1" max="50" step="0.1" value="10">
              <input id="slots-per-day-number" type="number" min="1" max="500" step="0.1" value="10">
            </div>
          </div>

          <div class="control">
            <div class="control-top">
              <label for="losing-slots-per-day">Estimated Losses Per Day</label>
              <span id="losing-slots-per-day-readout" class="readout">1</span>
            </div>
            <div class="number-row">
              <input id="losing-slots-per-day" type="range" min="0" max="20" step="0.1" value="1">
              <input id="losing-slots-per-day-number" type="number" min="0" max="500" step="0.1" value="1">
            </div>
          </div>
        </div>
        <p class="rule">Simple rule used here: sell winners at the slider value, and cap losses at half that value. The day estimate starts from actual paper trades/day and losses/day when snapshot data is available, then subtracts rough costs.</p>
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
      saveStatus: document.getElementById("save-status")
    };

    let pendingEnvValues = {};

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
      targetNode.value = String(clamp(sourceNode.value, Number(targetNode.min), Number(targetNode.max)));
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
      const slotsPerDay = Math.max(0.1, valueOf("slotsPerDay"));
      const losingSlotsPerDay = Math.min(
        slotsPerDay,
        Math.max(0, valueOf("losingSlotsPerDay"))
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
      nodes.slotsPerDayReadout.textContent = fmtNumber(slotsPerDay, 1);
      nodes.losingSlotsPerDayReadout.textContent = fmtNumber(losingSlotsPerDay, 1);
      nodes.dailyProfit.textContent = fmtCurrency(estimatedDailyProfitUsd);
      nodes.dailyProfitDetail.textContent = `${fmtNumber(winningSlotsPerDay, 1)} ${plural(winningSlotsPerDay, "winner")} x ${fmtCurrency(netWinUsd)} net - ${fmtNumber(losingSlotsPerDay, 1)} ${plural(losingSlotsPerDay, "loser")} x ${fmtCurrency(lossWithCostUsd)} drag`;
      nodes.dailyTargetWin.textContent = Number.isFinite(dailyTargetWinPct) ? fmtPct(dailyTargetWinPct) : "-";
      nodes.dailyTargetDetail.textContent = `for ${fmtCurrency(dailyTargetUsd)}/day; one-win-covers-one-loss starts around ${fmtPct(oneForOneWinPct)}`;
      nodes.estimatedDayShape.textContent = `${fmtNumber(winningSlotsPerDay, 1)} / ${fmtNumber(losingSlotsPerDay, 1)}`;
      nodes.estimatedDayDetail.textContent = `${fmtNumber(slotsPerDay, 1)} total estimated trades/day`;
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
        render();
      });
      field.number.addEventListener("input", () => {
        syncField(fieldName, "number");
        render();
      });
    });

    nodes.saveEnv.addEventListener("click", saveEnvValues);

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
      setField("slotsPerDay", Number(tradesPerDay.toFixed(1)));
      setField("losingSlotsPerDay", Number(lossesPerDay.toFixed(1)));
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

    function setSaveStatus(message, tone) {
      nodes.saveStatus.textContent = message;
      nodes.saveStatus.classList.toggle("good", tone === "good");
      nodes.saveStatus.classList.toggle("bad", tone === "bad");
    }

    function setField(fieldName, value) {
      const field = fields[fieldName];
      const numberMin = Number(field.number.min);
      const numberMax = Number(field.number.max);
      const next = clamp(value, numberMin, numberMax);
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

    applyActualDefaults();
    renderActualDayShape();
    render();
    loadEnvDefaults();
  </script>
</body>
</html>

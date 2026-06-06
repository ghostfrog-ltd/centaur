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
  <title>Centaur Fitness Explainer</title>
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
      --gold: #b47d0b;
      --rose: #b93f56;
      --green: #258b57;
      --shadow: 0 14px 34px rgba(18, 31, 32, 0.07);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      background:
        linear-gradient(180deg, rgba(15, 139, 141, 0.08), rgba(244, 247, 245, 0) 32rem),
        var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    button { font: inherit; }

    .shell {
      width: min(1420px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0 36px;
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
      font-weight: 850;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    h1 {
      margin: 0;
      font-size: clamp(28px, 3vw, 42px);
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

    .button.primary {
      background: var(--teal);
      border-color: var(--teal);
      color: white;
    }

    .button:hover { border-color: rgba(15, 139, 141, 0.45); }

    .status {
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
      margin-bottom: 16px;
    }

    .cards {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }

    .card,
    .panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.94);
      box-shadow: var(--shadow);
    }

    .card {
      min-height: 110px;
      padding: 14px;
    }

    .card-label {
      margin: 0 0 8px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .card-value {
      margin: 0;
      font-size: 25px;
      font-weight: 850;
      line-height: 1.05;
    }

    .card-detail {
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }

    .grid {
      display: grid;
      grid-template-columns: minmax(0, 0.95fr) minmax(0, 1.25fr);
      gap: 14px;
      align-items: start;
    }

    .panel {
      padding: 16px;
      margin-bottom: 14px;
    }

    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }

    .panel-title {
      font-size: 16px;
      font-weight: 850;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      border-radius: 999px;
      background: var(--surface-2);
      color: var(--teal-dark);
      font-size: 12px;
      font-weight: 850;
      padding: 0 10px;
      white-space: nowrap;
    }

    .chain {
      display: grid;
      gap: 10px;
    }

    .chain-row {
      display: grid;
      grid-template-columns: 160px minmax(0, 1fr);
      gap: 12px;
      border-left: 4px solid rgba(15, 139, 141, 0.35);
      background: var(--surface-2);
      border-radius: 8px;
      padding: 12px;
    }

    .chain-stage {
      font-weight: 850;
      color: var(--teal-dark);
    }

    .chain-text {
      display: grid;
      gap: 4px;
      color: var(--ink);
      font-size: 14px;
      line-height: 1.38;
    }

    .muted { color: var(--muted); }

    .formula {
      display: grid;
      gap: 10px;
    }

    .formula-row {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfb;
      padding: 12px;
    }

    .formula-label {
      color: var(--gold);
      font-size: 12px;
      font-weight: 850;
      text-transform: uppercase;
      letter-spacing: 0.04em;
      margin-bottom: 6px;
    }

    .formula-code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
      line-height: 1.45;
      overflow-wrap: anywhere;
    }

    .table-wrap {
      overflow-x: auto;
      border: 1px solid var(--line);
      border-radius: 8px;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 980px;
      background: var(--surface);
    }

    th,
    td {
      border-bottom: 1px solid var(--line);
      padding: 10px;
      text-align: left;
      vertical-align: top;
      font-size: 13px;
      line-height: 1.35;
    }

    th {
      background: var(--surface-2);
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    tr:last-child td { border-bottom: 0; }

    .positive { color: var(--green); font-weight: 850; }
    .negative { color: var(--rose); font-weight: 850; }
    .neutral { color: var(--muted); font-weight: 850; }
    .favored { color: var(--green); font-weight: 850; }
    .weighted { color: var(--blue); font-weight: 850; }
    .suppressed { color: var(--rose); font-weight: 850; }
    .unproven { color: var(--gold); font-weight: 850; }

    .signals {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    .signal-list {
      display: grid;
      gap: 8px;
    }

    .signal-row {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #fbfcfb;
      padding: 10px;
      min-height: 74px;
    }

    .signal-top {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 5px;
      font-weight: 850;
    }

    .signal-detail {
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }

    .empty {
      color: var(--muted);
      margin: 0;
      font-weight: 700;
    }

    .rule {
      margin: 10px 0 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.45;
    }

    @media (max-width: 980px) {
      .topbar { align-items: flex-start; flex-direction: column; }
      .toolbar { justify-content: flex-start; }
      .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .grid,
      .signals { grid-template-columns: 1fr; }
      .chain-row { grid-template-columns: 1fr; }
    }

    @media (max-width: 620px) {
      .shell {
        width: min(100% - 22px, 1420px);
        padding-top: 18px;
      }
      .cards { grid-template-columns: 1fr; }
      .card-value { font-size: 22px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">Evidence And Allocation</p>
        <h1>Fitness Explainer</h1>
      </div>
      <div class="toolbar">
        <?php centaurRenderNavigation('/fitness-explainer.php'); ?>
        <button class="button primary" id="refresh" type="button">Refresh</button>
      </div>
    </header>

    <div class="status" id="status">Loading fitness evidence...</div>

    <section class="cards" aria-label="Fitness summary cards">
      <article class="card">
        <p class="card-label">Latest Tick</p>
        <p class="card-value" id="tick-id">-</p>
        <p class="card-detail" id="tick-detail">-</p>
      </article>
      <article class="card">
        <p class="card-label">Signals</p>
        <p class="card-value" id="signals-value">-</p>
        <p class="card-detail" id="signals-detail">-</p>
      </article>
      <article class="card">
        <p class="card-label">Suppression</p>
        <p class="card-value" id="suppression-value">-</p>
        <p class="card-detail" id="suppression-detail">-</p>
      </article>
      <article class="card">
        <p class="card-label">Fitness Rows</p>
        <p class="card-value" id="rows-value">-</p>
        <p class="card-detail" id="rows-detail">-</p>
      </article>
      <article class="card">
        <p class="card-label">Thresholds</p>
        <p class="card-value" id="threshold-value">-</p>
        <p class="card-detail" id="threshold-detail">-</p>
      </article>
    </section>

    <section class="grid">
      <div>
        <section class="panel" aria-label="Evidence chain">
          <div class="panel-head">
            <div class="panel-title">How The Data Comes Together</div>
            <span class="badge" id="chain-badge">0 stages</span>
          </div>
          <div class="chain" id="chain"></div>
        </section>

        <section class="panel" aria-label="Fitness formula">
          <div class="panel-head">
            <div class="panel-title">What Fitness Means</div>
            <span class="badge">read-only</span>
          </div>
          <div class="formula" id="formula"></div>
          <p class="rule" id="decision-rule"></p>
        </section>
      </div>

      <div>
        <section class="panel" aria-label="Current signal examples">
          <div class="panel-head">
            <div class="panel-title">Current Tick Allocation Examples</div>
            <span class="badge" id="signal-badge">0 examples</span>
          </div>
          <div class="signals">
            <div>
              <h2 class="card-label">Raw / surviving preview</h2>
              <div class="signal-list" id="raw-signals"></div>
            </div>
            <div>
              <h2 class="card-label">Suppressed preview</h2>
              <div class="signal-list" id="suppressed-signals"></div>
            </div>
          </div>
        </section>

        <section class="panel" aria-label="Latest fitness rows">
          <div class="panel-head">
            <div class="panel-title">Latest Strategy/Window Fitness</div>
            <span class="badge" id="fitness-badge">0 rows</span>
          </div>
          <div class="table-wrap" id="fitness-table"></div>
        </section>
      </div>
    </section>
  </main>

  <script>
    const nodes = {
      status: document.getElementById("status"),
      refresh: document.getElementById("refresh"),
      tickId: document.getElementById("tick-id"),
      tickDetail: document.getElementById("tick-detail"),
      signalsValue: document.getElementById("signals-value"),
      signalsDetail: document.getElementById("signals-detail"),
      suppressionValue: document.getElementById("suppression-value"),
      suppressionDetail: document.getElementById("suppression-detail"),
      rowsValue: document.getElementById("rows-value"),
      rowsDetail: document.getElementById("rows-detail"),
      thresholdValue: document.getElementById("threshold-value"),
      thresholdDetail: document.getElementById("threshold-detail"),
      chain: document.getElementById("chain"),
      chainBadge: document.getElementById("chain-badge"),
      formula: document.getElementById("formula"),
      decisionRule: document.getElementById("decision-rule"),
      signalBadge: document.getElementById("signal-badge"),
      rawSignals: document.getElementById("raw-signals"),
      suppressedSignals: document.getElementById("suppressed-signals"),
      fitnessBadge: document.getElementById("fitness-badge"),
      fitnessTable: document.getElementById("fitness-table")
    };

    let report = null;

    nodes.refresh.addEventListener("click", () => loadReport());
    loadReport();

    async function loadReport() {
      nodes.status.textContent = "Loading fitness evidence...";
      nodes.refresh.disabled = true;
      try {
        const response = await fetch("/api/fitness_explainer.php", { cache: "no-store" });
        const payload = await response.json();
        if (!response.ok || payload.ok === false) {
          throw new Error(payload.detail || payload.error || "Fitness explainer API failed.");
        }
        report = payload;
        render();
        nodes.status.textContent = `Updated ${fmtDateTime(payload.checked_at)} | backend ${escapeText(payload.backend || "-")}`;
      } catch (error) {
        nodes.status.textContent = `Unable to load fitness evidence: ${error.message}`;
      } finally {
        nodes.refresh.disabled = false;
      }
    }

    function render() {
      renderCards();
      renderChain();
      renderFormula();
      renderSignals();
      renderFitnessTable();
    }

    function renderCards() {
      const tick = report.latest_tick || {};
      const config = report.config || {};
      const summary = report.latest_fitness?.summary || {};
      nodes.tickId.textContent = tick.tick_id || "-";
      nodes.tickDetail.textContent = tick.ended_at ? `ended ${fmtDateTime(tick.ended_at)}` : "no completed tick timestamp";
      nodes.signalsValue.textContent = `${fmtInteger(tick.signals_out)} / ${fmtInteger(tick.signals_in)}`;
      nodes.signalsDetail.textContent = `out / in | favored ${fmtInteger(tick.favored)} | weighted ${fmtInteger(tick.weighted)} | unproven ${fmtInteger(tick.unproven)}`;
      nodes.suppressionValue.textContent = fmtInteger(tick.suppressed);
      nodes.suppressionDetail.textContent = `score-to-trade ${fmtInteger(tick.score_to_trade)} | active gate remains CFO/risk after fitness`;
      nodes.rowsValue.textContent = fmtInteger(summary.rows);
      nodes.rowsDetail.textContent = `${fmtInteger(summary.favored)} favored | ${fmtInteger(summary.weighted)} weighted | ${fmtInteger(summary.suppressed)} suppressed`;
      nodes.thresholdValue.textContent = `${fmtNumber(config.strategy_allocation_suppress_threshold, 2)} / ${fmtNumber(config.strategy_allocation_favor_threshold, 2)}`;
      nodes.thresholdDetail.textContent = `equity suppress / favor | crypto suppress ${fmtNumber(config.strategy_allocation_crypto_suppress_threshold, 2)} | min checkpoints ${fmtInteger(config.strategy_allocation_min_checkpoints)}`;
    }

    function renderChain() {
      const chain = Array.isArray(report.evidence_chain) ? report.evidence_chain : [];
      nodes.chainBadge.textContent = `${fmtInteger(chain.length)} stages`;
      nodes.chain.innerHTML = chain.map((item) => `
        <div class="chain-row">
          <div class="chain-stage">${escapeHtml(item.stage || "-")}</div>
          <div class="chain-text">
            <div>${escapeHtml(item.data || "-")}</div>
            <div class="muted">${escapeHtml(item.role || "-")}</div>
          </div>
        </div>
      `).join("") || `<p class="empty">No evidence-chain metadata available.</p>`;
    }

    function renderFormula() {
      const formula = report.formula || {};
      const rows = [
        ["Checkpoint fitness", formula.checkpoint_fitness],
        ["Composite fitness", formula.composite_fitness],
        ["Sample weight", formula.sample_weight],
        ["Allocation bonus", formula.allocation_bonus]
      ];
      nodes.formula.innerHTML = rows.map(([label, text]) => `
        <div class="formula-row">
          <div class="formula-label">${escapeHtml(label)}</div>
          <div class="formula-code">${escapeHtml(text || "-")}</div>
        </div>
      `).join("");
      nodes.decisionRule.textContent = report.decision_rule || "";
    }

    function renderSignals() {
      const tick = report.latest_tick || {};
      const raw = Array.isArray(tick.raw_signal_preview) ? tick.raw_signal_preview : [];
      const suppressed = Array.isArray(tick.suppressed_signal_preview) ? tick.suppressed_signal_preview : [];
      nodes.signalBadge.textContent = `${fmtInteger(raw.length + suppressed.length)} examples`;
      nodes.rawSignals.innerHTML = raw.map(signalCard).join("") || `<p class="empty">No raw/surviving signal preview in latest tick.</p>`;
      nodes.suppressedSignals.innerHTML = suppressed.map(signalCard).join("") || `<p class="empty">No suppressed signal preview in latest tick.</p>`;
    }

    function signalCard(item) {
      const status = String(item.allocation_status || "unproven").toLowerCase();
      return `
        <div class="signal-row">
          <div class="signal-top">
            <span>${escapeHtml(item.symbol || "-")} | ${escapeHtml(item.strategy_id || "-")}</span>
            <span class="${bandClass(status)}">${escapeHtml(status)}</span>
          </div>
          <div class="signal-detail">
            score ${fmtNumber(item.base_signal_score, 2)} -> ${fmtNumber(item.signal_score, 2)}
            | fit ${fmtNumber(item.fitness_composite_score, 2)}
            | samples ${fmtInteger(item.fitness_checkpoints_evaluated)}
            | ${escapeHtml(item.allocation_note || "No allocation note.")}
          </div>
        </div>
      `;
    }

    function renderFitnessTable() {
      const rows = Array.isArray(report.latest_fitness?.rows) ? report.latest_fitness.rows : [];
      nodes.fitnessBadge.textContent = `${fmtInteger(rows.length)} rows`;
      if (!rows.length) {
        nodes.fitnessTable.innerHTML = `<p class="empty" style="padding:12px;">No latest fitness snapshot rows are available.</p>`;
        return;
      }
      nodes.fitnessTable.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>Rank</th>
              <th>Strategy</th>
              <th>Window</th>
              <th>Asset</th>
              <th>Samples</th>
              <th>Win / Stop</th>
              <th>Avg Return</th>
              <th>Composite</th>
              <th>Band</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            ${rows.map((row) => {
              const composite = Number(row.composite_fitness_score);
              const compositeClass = composite > 0 ? "positive" : (composite < 0 ? "negative" : "neutral");
              const band = String(row.fitness_band || "unproven").toLowerCase();
              return `
                <tr>
                  <td>${fmtInteger(row.fitness_rank)}</td>
                  <td>${escapeHtml(row.strategy_id || "-")}</td>
                  <td>${escapeHtml(row.checkpoint_code || "-")}</td>
                  <td>${escapeHtml(row.asset_class || "-")}</td>
                  <td>${fmtInteger(row.checkpoints_evaluated)}</td>
                  <td>${fmtPct(row.win_rate)} / ${fmtPct(row.stop_hit_rate)}</td>
                  <td>${fmtSignedPct(row.avg_realized_return_pct)}</td>
                  <td class="${compositeClass}">${fmtNumber(row.composite_fitness_score, 2)}</td>
                  <td class="${bandClass(band)}">${escapeHtml(band)}</td>
                  <td>${escapeHtml(row.fitness_reason || "-")}</td>
                </tr>
              `;
            }).join("")}
          </tbody>
        </table>
      `;
    }

    function bandClass(value) {
      if (value === "favored") return "favored";
      if (value === "weighted") return "weighted";
      if (value === "suppressed") return "suppressed";
      if (value === "score_to_trade") return "weighted";
      return "unproven";
    }

    function fmtInteger(value) {
      const number = Number(value || 0);
      return Number.isFinite(number) ? Math.round(number).toLocaleString() : "0";
    }

    function fmtNumber(value, decimals = 2) {
      const number = Number(value);
      return Number.isFinite(number) ? number.toFixed(decimals) : "-";
    }

    function fmtPct(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return "-";
      return `${(number * 100).toFixed(1)}%`;
    }

    function fmtSignedPct(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return "-";
      const sign = number >= 0 ? "+" : "";
      return `${sign}${number.toFixed(2)}%`;
    }

    function fmtDateTime(value) {
      if (!value) return "-";
      const date = new Date(value);
      return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
    }

    function escapeText(value) {
      return String(value ?? "");
    }

    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        "\"": "&quot;",
        "'": "&#039;"
      }[char]));
    }
  </script>
</body>
</html>

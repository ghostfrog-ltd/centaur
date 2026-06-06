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
  <title>Centaur Last Day Trades</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f7f5;
      --surface: #ffffff;
      --surface-2: #edf4f0;
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

    * { box-sizing: border-box; }

    body {
      margin: 0;
      background:
        linear-gradient(180deg, rgba(15, 139, 141, 0.08), rgba(244, 247, 245, 0) 34rem),
        var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    button, input, select { font: inherit; }

    .shell {
      width: min(1460px, calc(100% - 32px));
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

    h1, h2, h3, p { margin: 0; }

    h1 {
      font-size: clamp(28px, 3vw, 44px);
      line-height: 1.02;
      letter-spacing: 0;
    }

    .subtle {
      color: var(--muted);
      font-size: 14px;
      line-height: 1.45;
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
      border-color: var(--teal);
      background: var(--teal);
      color: #ffffff;
    }

    .control-row {
      display: grid;
      grid-template-columns: repeat(2, minmax(160px, 220px));
      gap: 10px;
      align-items: center;
    }

    select {
      min-height: 40px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #ffffff;
      color: var(--ink);
      font-weight: 750;
      padding: 6px 10px;
    }

    .metric-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
    }

    .metric-card, .panel, .warning-card {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.92);
      box-shadow: var(--shadow);
    }

    .metric-card {
      min-width: 0;
      padding: 15px;
    }

    .metric-label {
      color: var(--muted);
      font-size: 13px;
      font-weight: 760;
    }

    .metric-value {
      margin-top: 10px;
      font-size: 25px;
      font-weight: 850;
      line-height: 1.1;
      overflow-wrap: anywhere;
    }

    .metric-detail {
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }

    .tone-positive { color: var(--green); }
    .tone-negative { color: var(--rose); }
    .tone-review { color: var(--gold); }

    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1.28fr) minmax(360px, 0.82fr);
      gap: 18px;
      align-items: start;
      margin-top: 18px;
    }

    .stack {
      display: grid;
      gap: 18px;
      min-width: 0;
    }

    .panel { min-width: 0; overflow: hidden; }

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

    .panel-body { padding: 16px; }

    .chart-grid {
      display: grid;
      grid-template-columns: minmax(220px, 0.7fr) minmax(0, 1.3fr);
      gap: 18px;
      align-items: center;
    }

    .donut {
      width: min(240px, 100%);
      aspect-ratio: 1;
      border-radius: 50%;
      background: conic-gradient(var(--green) 0deg, var(--green) 0deg, var(--rose) 0deg, var(--rose) 0deg, var(--line) 0deg);
      display: grid;
      place-items: center;
      margin: 0 auto;
    }

    .donut-core {
      display: grid;
      place-items: center;
      width: 62%;
      aspect-ratio: 1;
      border-radius: 50%;
      background: var(--surface);
      text-align: center;
      padding: 12px;
    }

    .donut-number {
      font-size: 28px;
      font-weight: 900;
      line-height: 1;
    }

    .bar-list, .warning-list, .control-stack {
      display: grid;
      gap: 10px;
    }

    .bar-row {
      display: grid;
      grid-template-columns: minmax(90px, 150px) minmax(0, 1fr) 86px;
      gap: 10px;
      align-items: center;
      color: var(--muted);
      font-size: 13px;
      font-weight: 750;
    }

    .bar-track {
      height: 12px;
      border-radius: 999px;
      background: var(--surface-2);
      overflow: hidden;
    }

    .bar-fill {
      width: 0;
      height: 100%;
      border-radius: inherit;
      background: var(--teal);
    }

    .bar-fill.buy { background: var(--blue); }
    .bar-fill.sell { background: var(--gold); }
    .bar-fill.win { background: var(--green); }
    .bar-fill.loss { background: var(--rose); }

    .warning-card {
      box-shadow: none;
      background: var(--surface-2);
      padding: 13px;
    }

    .warning-level {
      color: var(--muted);
      font-size: 11px;
      font-weight: 850;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    .warning-title {
      margin-top: 7px;
      font-size: 14px;
      font-weight: 850;
    }

    .warning-detail {
      margin-top: 7px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.42;
    }

    .table-wrap { overflow-x: auto; }

    table {
      width: 100%;
      min-width: 760px;
      border-collapse: collapse;
    }

    th {
      padding: 11px 13px;
      background: var(--surface-2);
      color: var(--muted);
      font-size: 11px;
      font-weight: 850;
      letter-spacing: 0.06em;
      text-align: left;
      text-transform: uppercase;
      white-space: nowrap;
    }

    td {
      padding: 11px 13px;
      border-top: 1px solid var(--line);
      color: #263336;
      font-size: 13px;
      vertical-align: top;
    }

    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
    }

    .what-if-grid {
      display: grid;
      grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.1fr);
      gap: 18px;
    }

    .control {
      display: grid;
      gap: 7px;
    }

    .control-top {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 10px;
      color: var(--muted);
      font-size: 13px;
      font-weight: 760;
    }

    input[type="range"] {
      width: 100%;
      accent-color: var(--teal);
    }

    .scenario-cards {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    .scenario-card {
      min-width: 0;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface-2);
      padding: 13px;
    }

    .scenario-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
    }

    .scenario-value {
      margin-top: 8px;
      font-size: 21px;
      font-weight: 900;
      overflow-wrap: anywhere;
    }

    @media (max-width: 1180px) {
      .metric-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
      .layout, .what-if-grid { grid-template-columns: 1fr; }
    }

    @media (max-width: 760px) {
      .shell {
        width: min(100% - 24px, 1460px);
        padding-top: 18px;
      }

      .topbar {
        align-items: stretch;
        flex-direction: column;
      }

      .toolbar { justify-content: flex-start; }
      .control-row, .metric-grid, .chart-grid, .scenario-cards { grid-template-columns: 1fr; }
      .bar-row { grid-template-columns: 92px minmax(0, 1fr) 64px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">Project Centaur</p>
        <h1>Last Day Trades</h1>
        <p id="checked-at" class="subtle" style="margin-top: 10px;">Loading Alpaca paper fills...</p>
      </div>
      <div class="centaur-menu-toolbar toolbar">
        <div class="control-row">
          <select id="hours-select" aria-label="Window">
            <option value="24">Last 24h</option>
            <option value="48">Last 48h</option>
            <option value="72">Last 72h</option>
            <option value="168">Last 7d</option>
          </select>
          <select id="broker-select" aria-label="Broker">
            <option value="alpaca_paper">Alpaca Paper</option>
            <option value="alpaca_live">Alpaca Live</option>
            <option value="trading212_paper">Trading 212 Paper</option>
          </select>
        </div>
        <button id="refresh-button" class="button primary" type="button">Refresh</button>
        <?php centaurRenderNavigation('/recent-trades.php'); ?>
      </div>
    </header>

    <section id="metric-cards" class="metric-grid"></section>

    <section class="layout">
      <div class="stack">
        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">Win/Loss and Buy/Sell</h2>
          </div>
          <div class="panel-body chart-grid">
            <div id="win-donut" class="donut"><div class="donut-core"><div><div id="win-donut-number" class="donut-number">-</div><p class="subtle">win rate</p></div></div></div>
            <div id="count-bars" class="bar-list"></div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">What If</h2>
          </div>
          <div class="panel-body what-if-grid">
            <div id="what-if-controls" class="control-stack"></div>
            <div>
              <div id="scenario-cards" class="scenario-cards"></div>
              <div id="scenario-bars" class="bar-list" style="margin-top: 14px;"></div>
            </div>
          </div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">Symbols</h2>
          </div>
          <div id="symbol-table" class="table-wrap"></div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">Recent Closed Trades</h2>
          </div>
          <div id="closed-table" class="table-wrap"></div>
        </div>
      </div>

      <div class="stack">
        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">Diagnostics</h2>
          </div>
          <div id="diagnostics" class="panel-body warning-list"></div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">Strategies</h2>
          </div>
          <div id="strategy-table" class="table-wrap"></div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">Recent Fills</h2>
          </div>
          <div id="fills-table" class="table-wrap"></div>
        </div>
      </div>
    </section>
  </main>

  <script>
    const state = {
      report: null,
      scenario: {
        trades: 0,
        winRatePct: 0,
        avgWinPct: 0,
        avgLossPct: 0,
        avgBuyValue: 10,
        sells: 0,
      },
    };

    const metricCards = document.getElementById("metric-cards");
    const checkedAt = document.getElementById("checked-at");
    const hoursSelect = document.getElementById("hours-select");
    const brokerSelect = document.getElementById("broker-select");
    const refreshButton = document.getElementById("refresh-button");
    const winDonut = document.getElementById("win-donut");
    const winDonutNumber = document.getElementById("win-donut-number");
    const countBars = document.getElementById("count-bars");
    const diagnostics = document.getElementById("diagnostics");
    const symbolTable = document.getElementById("symbol-table");
    const strategyTable = document.getElementById("strategy-table");
    const closedTable = document.getElementById("closed-table");
    const fillsTable = document.getElementById("fills-table");
    const whatIfControls = document.getElementById("what-if-controls");
    const scenarioCards = document.getElementById("scenario-cards");
    const scenarioBars = document.getElementById("scenario-bars");

    function numberOrNull(value) {
      if (value === null || value === undefined || value === "") return null;
      const number = Number(value);
      return Number.isFinite(number) ? number : null;
    }

    function fmtInt(value) {
      const number = numberOrNull(value);
      return number === null ? "-" : Math.round(number).toLocaleString();
    }

    function fmtPct(value, decimals = 1) {
      const number = numberOrNull(value);
      return number === null ? "-" : `${(number * 100).toFixed(decimals)}%`;
    }

    function fmtPctPoints(value, decimals = 2) {
      const number = numberOrNull(value);
      return number === null ? "-" : `${number.toFixed(decimals)}%`;
    }

    function fmtMoney(value) {
      const number = numberOrNull(value);
      if (number === null) return "-";
      return `$${number >= 0 ? "+" : ""}${number.toFixed(2)}`;
    }

    function fmtMoneyPlain(value) {
      const number = numberOrNull(value);
      return number === null ? "-" : `$${number.toFixed(2)}`;
    }

    function fmtDate(value) {
      if (!value) return "-";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return date.toLocaleString([], { dateStyle: "short", timeStyle: "medium" });
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function toneClass(value) {
      const number = numberOrNull(value);
      if (number === null || number === 0) return "";
      return number > 0 ? "tone-positive" : "tone-negative";
    }

    function barRow(label, value, max, className = "") {
      const numeric = Math.max(0, numberOrNull(value) ?? 0);
      const width = max > 0 ? Math.min(100, (numeric / max) * 100) : 0;
      return `
        <div class="bar-row">
          <div>${escapeHtml(label)}</div>
          <div class="bar-track"><div class="bar-fill ${escapeHtml(className)}" style="width: ${width.toFixed(2)}%;"></div></div>
          <div class="mono">${escapeHtml(fmtInt(numeric))}</div>
        </div>
      `;
    }

    function renderMetrics(report) {
      const fills = report.fills || {};
      const closed = report.closed_trades || {};
      const account = report.broker_account || {};
      const reconciliation = report.reconciliation || {};
      const lastBuy = fills.last_buy || null;
      const lastSell = fills.last_sell || null;
      const brokerDayChange = numberOrNull(reconciliation.broker_day_change);
      const openUnrealized = numberOrNull(reconciliation.open_position_unrealized_pl);
      const difference = numberOrNull(reconciliation.difference_after_open_unrealized);
      const cards = [
        ["Broker Day P/L", brokerDayChange === null ? "-" : fmtMoney(brokerDayChange), account.has_snapshot ? `${fmtPctPoints(account.day_change_pct)} broker day change` : "No broker snapshot", brokerDayChange],
        ["Closed Trade P/L", fmtMoney(closed.realized_pnl_usd), `${fmtPctPoints(closed.avg_return_pct)} avg closed return`, closed.realized_pnl_usd],
        ["Open U/P&L", openUnrealized === null ? "-" : fmtMoney(openUnrealized), difference === null ? "Broker reconciliation pending" : `${fmtMoney(difference)} remaining difference`, openUnrealized],
        ["Fills", fills.sampled, `${fmtInt(fills.buy_count)} buys / ${fmtInt(fills.sell_count)} sells`],
        ["Closed", closed.count, `${fmtInt(closed.wins)} wins / ${fmtInt(closed.losses)} losses`],
        ["Win Rate", fmtPct(closed.win_rate), `${fmtPct(closed.loss_rate)} loss rate`],
        ["Loss Rate", fmtPct(closed.loss_rate), `${fmtInt(closed.losses)} losing closed trades`],
        ["Last Buy", lastBuy ? fmtDate(lastBuy.activity_at) : "-", lastBuy ? `${lastBuy.symbol} ${fmtMoneyPlain(lastBuy.notional_usd)}` : "No buy in window"],
        ["Last Sell", lastSell ? fmtDate(lastSell.activity_at) : "-", lastSell ? `${lastSell.symbol} ${fmtMoneyPlain(lastSell.notional_usd)}` : "No sell in window"],
      ];
      metricCards.innerHTML = cards.map(([label, value, detail, toneValue]) => `
        <article class="metric-card">
          <div class="metric-label">${escapeHtml(label)}</div>
          <div class="metric-value ${toneValue === undefined ? "" : toneClass(toneValue)}">${escapeHtml(value)}</div>
          <div class="metric-detail">${escapeHtml(detail)}</div>
        </article>
      `).join("");
    }

    function renderCharts(report) {
      const fills = report.fills || {};
      const closed = report.closed_trades || {};
      const winRate = numberOrNull(closed.win_rate) ?? 0;
      const lossRate = numberOrNull(closed.loss_rate) ?? 0;
      const winDeg = Math.max(0, Math.min(360, winRate * 360));
      const lossDeg = Math.max(0, Math.min(360 - winDeg, lossRate * 360));
      winDonut.style.background = `conic-gradient(var(--green) 0deg ${winDeg}deg, var(--rose) ${winDeg}deg ${winDeg + lossDeg}deg, var(--line) ${winDeg + lossDeg}deg 360deg)`;
      winDonutNumber.textContent = fmtPct(winRate, 1);
      const maxCount = Math.max(1, fills.buy_count || 0, fills.sell_count || 0, closed.wins || 0, closed.losses || 0, closed.flats || 0);
      countBars.innerHTML = [
        barRow("Buys", fills.buy_count || 0, maxCount, "buy"),
        barRow("Sells", fills.sell_count || 0, maxCount, "sell"),
        barRow("Wins", closed.wins || 0, maxCount, "win"),
        barRow("Losses", closed.losses || 0, maxCount, "loss"),
        barRow("Flats", closed.flats || 0, maxCount, ""),
      ].join("");
    }

    function renderDiagnostics(report) {
      const rows = Array.isArray(report.diagnostics) ? report.diagnostics : [];
      if (!rows.length) {
        diagnostics.innerHTML = `<p class="subtle">No diagnostics recorded.</p>`;
        return;
      }
      diagnostics.innerHTML = rows.map((row) => `
        <article class="warning-card">
          <div class="warning-level">${escapeHtml(row.level || "info")}</div>
          <div class="warning-title">${escapeHtml(row.title || "Diagnostic")}</div>
          <div class="warning-detail">${escapeHtml(row.detail || "")}</div>
        </article>
      `).join("");
    }

    function renderTable(target, columns, rows, emptyLabel) {
      if (!Array.isArray(rows) || !rows.length) {
        target.innerHTML = `<div class="panel-body"><p class="subtle">${escapeHtml(emptyLabel)}</p></div>`;
        return;
      }
      const head = columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("");
      const body = rows.map((row) => `
        <tr>${columns.map((column) => `<td class="${column.mono ? "mono" : ""}">${column.render(row)}</td>`).join("")}</tr>
      `).join("");
      target.innerHTML = `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
    }

    function renderBreakdowns(report) {
      const groupColumns = [
        { label: "Name", mono: true, render: (row) => escapeHtml(row.symbol || row.strategy_id || "unassigned") },
        { label: "Buys", render: (row) => escapeHtml(fmtInt(row.buy_count)) },
        { label: "Sells", render: (row) => escapeHtml(fmtInt(row.sell_count)) },
        { label: "Closed", render: (row) => escapeHtml(fmtInt(row.closed_trades)) },
        { label: "Win %", render: (row) => escapeHtml(fmtPct(row.win_rate)) },
        { label: "P/L", render: (row) => `<span class="${toneClass(row.realized_pnl_usd)}">${escapeHtml(fmtMoney(row.realized_pnl_usd))}</span>` },
      ];
      renderTable(symbolTable, groupColumns, report.by_symbol || [], "No symbol activity in this window.");
      renderTable(strategyTable, groupColumns, report.by_strategy || [], "No strategy activity in this window.");

      renderTable(closedTable, [
        { label: "Exit", mono: true, render: (row) => escapeHtml(fmtDate(row.exit_at)) },
        { label: "Symbol", mono: true, render: (row) => escapeHtml(row.symbol || "-") },
        { label: "Strategy", mono: true, render: (row) => escapeHtml(row.strategy_id || "-") },
        { label: "Return", render: (row) => `<span class="${toneClass(row.return_pct)}">${escapeHtml(fmtPctPoints(row.return_pct))}</span>` },
        { label: "P/L", render: (row) => `<span class="${toneClass(row.pnl_usd)}">${escapeHtml(fmtMoney(row.pnl_usd))}</span>` },
        { label: "Buy/Sell", render: (row) => escapeHtml(`${fmtMoneyPlain(row.buy_value_usd)} -> ${fmtMoneyPlain(row.sell_value_usd)}`) },
      ], report.recent_closed_trades || [], "No closed trades in this window.");

      renderTable(fillsTable, [
        { label: "Time", mono: true, render: (row) => escapeHtml(fmtDate(row.activity_at)) },
        { label: "Side", render: (row) => escapeHtml(row.side || "-") },
        { label: "Symbol", mono: true, render: (row) => escapeHtml(row.symbol || "-") },
        { label: "Strategy", mono: true, render: (row) => escapeHtml(row.strategy_id || "-") },
        { label: "Qty", render: (row) => escapeHtml(row.filled_qty ?? "-") },
        { label: "Price", render: (row) => escapeHtml(fmtMoneyPlain(row.filled_avg_price)) },
        { label: "Notional", render: (row) => escapeHtml(fmtMoneyPlain(row.notional_usd)) },
      ], report.recent_fills || [], "No fills in this window.");
    }

    function initialiseScenario(report) {
      const fills = report.fills || {};
      const closed = report.closed_trades || {};
      const closedCount = Math.max(0, Number(closed.count) || 0);
      const avgBuyValue = closedCount > 0
        ? (Number(closed.total_buy_value_usd) || 0) / closedCount
        : ((Number(fills.buy_notional_usd) || 0) / Math.max(1, Number(fills.buy_count) || 0));
      state.scenario = {
        trades: closedCount,
        winRatePct: (Number(closed.win_rate) || 0) * 100,
        avgWinPct: Number(closed.avg_win_pct) || 0,
        avgLossPct: Number(closed.avg_loss_pct) || 0,
        avgBuyValue: avgBuyValue > 0 ? avgBuyValue : 10,
        sells: Number(fills.sell_count) || 0,
      };
      renderWhatIfControls(report);
      renderScenario(report);
    }

    function controlHtml(key, label, value, min, max, step, suffix = "") {
      return `
        <label class="control">
          <span class="control-top"><span>${escapeHtml(label)}</span><span id="${key}-readout">${escapeHtml(Number(value).toFixed(step < 1 ? 2 : 0))}${escapeHtml(suffix)}</span></span>
          <input type="range" min="${min}" max="${max}" step="${step}" value="${escapeHtml(value)}" data-scenario-key="${escapeHtml(key)}">
        </label>
      `;
    }

    function renderWhatIfControls(report) {
      const fills = report.fills || {};
      const closed = report.closed_trades || {};
      const maxTrades = Math.max(10, (Number(closed.count) || 0) * 3, (Number(fills.buy_count) || 0) * 2);
      const maxSells = Math.max(10, (Number(fills.buy_count) || 0) * 3, (Number(fills.sell_count) || 0) * 3);
      whatIfControls.innerHTML = [
        controlHtml("trades", "Closed trades", state.scenario.trades, 0, maxTrades, 1),
        controlHtml("winRatePct", "Win rate", state.scenario.winRatePct, 0, 100, 0.5, "%"),
        controlHtml("avgWinPct", "Average win", state.scenario.avgWinPct, 0, Math.max(5, state.scenario.avgWinPct * 3), 0.05, "%"),
        controlHtml("avgLossPct", "Average loss", state.scenario.avgLossPct, 0, Math.max(5, state.scenario.avgLossPct * 3), 0.05, "%"),
        controlHtml("avgBuyValue", "Average buy value", state.scenario.avgBuyValue, 1, Math.max(50, state.scenario.avgBuyValue * 3), 0.25),
        controlHtml("sells", "Filled sells", state.scenario.sells, 0, maxSells, 1),
      ].join("");
      whatIfControls.querySelectorAll("[data-scenario-key]").forEach((input) => {
        input.addEventListener("input", () => {
          const key = input.dataset.scenarioKey;
          state.scenario[key] = Number(input.value);
          const readout = document.getElementById(`${key}-readout`);
          const suffix = key.includes("Pct") ? "%" : "";
          readout.textContent = `${Number(input.value).toFixed(Number(input.step) < 1 ? 2 : 0)}${suffix}`;
          renderScenario(report);
        });
      });
    }

    function projectedPnl(scenario) {
      const trades = Math.max(0, Number(scenario.trades) || 0);
      const winRate = Math.max(0, Math.min(1, (Number(scenario.winRatePct) || 0) / 100));
      const avgWin = Math.max(0, Number(scenario.avgWinPct) || 0) / 100;
      const avgLoss = Math.max(0, Number(scenario.avgLossPct) || 0) / 100;
      const avgBuyValue = Math.max(0, Number(scenario.avgBuyValue) || 0);
      return trades * avgBuyValue * ((winRate * avgWin) - ((1 - winRate) * avgLoss));
    }

    function renderScenario(report) {
      const fills = report.fills || {};
      const closed = report.closed_trades || {};
      const basePnl = Number(closed.realized_pnl_usd) || 0;
      const nextPnl = projectedPnl(state.scenario);
      const delta = nextPnl - basePnl;
      const buyCount = Number(fills.buy_count) || 0;
      const projectedSellRatio = buyCount > 0 ? state.scenario.sells / buyCount : 0;
      const expectedWins = Math.round(state.scenario.trades * (state.scenario.winRatePct / 100));
      const expectedLosses = Math.max(0, Math.round(state.scenario.trades - expectedWins));
      scenarioCards.innerHTML = [
        ["Projected Closed P/L", fmtMoney(nextPnl), toneClass(nextPnl)],
        ["Change vs Closed", fmtMoney(delta), toneClass(delta)],
        ["Expected Wins", `${fmtInt(expectedWins)} / ${fmtInt(state.scenario.trades)}`, ""],
        ["Sell/Buy Ratio", buyCount > 0 ? `${(projectedSellRatio * 100).toFixed(1)}%` : "-", projectedSellRatio < 0.35 && buyCount >= 3 ? "tone-review" : ""],
      ].map(([label, value, tone]) => `
        <article class="scenario-card">
          <div class="scenario-label">${escapeHtml(label)}</div>
          <div class="scenario-value ${tone}">${escapeHtml(value)}</div>
        </article>
      `).join("");

      const maxScenario = Math.max(1, state.scenario.trades, expectedWins, expectedLosses, state.scenario.sells, buyCount);
      scenarioBars.innerHTML = [
        barRow("Trades", state.scenario.trades, maxScenario, ""),
        barRow("Wins", expectedWins, maxScenario, "win"),
        barRow("Losses", expectedLosses, maxScenario, "loss"),
        barRow("Buys", buyCount, maxScenario, "buy"),
        barRow("Sells", state.scenario.sells, maxScenario, "sell"),
      ].join("");
    }

    async function loadReport() {
      refreshButton.disabled = true;
      checkedAt.textContent = "Loading latest execution report...";
      const url = `/api/recent_trades.php?${new URLSearchParams({ hours: hoursSelect.value, broker_id: brokerSelect.value })}`;
      try {
        const response = await fetch(url, { cache: "no-store" });
        const report = await response.json();
        if (!response.ok || report.ok === false) {
          throw new Error(report.detail || report.reason || "Recent trade report unavailable");
        }
        state.report = report;
        checkedAt.textContent = `${report.window?.label || "Recent execution window"} | ${fmtDate(report.window?.start_at)} to ${fmtDate(report.window?.end_at)} | ${report.broker_id}`;
        renderMetrics(report);
        renderCharts(report);
        renderDiagnostics(report);
        renderBreakdowns(report);
        initialiseScenario(report);
      } catch (error) {
        checkedAt.textContent = `Unable to load recent trades: ${error.message}`;
        metricCards.innerHTML = "";
        countBars.innerHTML = "";
        diagnostics.innerHTML = `<article class="warning-card"><div class="warning-level">error</div><div class="warning-title">Report unavailable</div><div class="warning-detail">${escapeHtml(error.message)}</div></article>`;
      } finally {
        refreshButton.disabled = false;
      }
    }

    refreshButton.addEventListener("click", loadReport);
    hoursSelect.addEventListener("change", loadReport);
    brokerSelect.addEventListener("change", loadReport);
    loadReport();
  </script>
</body>
</html>

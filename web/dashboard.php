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
  <title>Project Centaur Dashboard</title>
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

    button {
      font: inherit;
    }

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

    h1 {
      margin: 0;
      font-size: clamp(28px, 3vw, 44px);
      line-height: 1.02;
      letter-spacing: 0;
    }

    h2,
    h3,
    p {
      margin: 0;
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

    .button:hover {
      border-color: rgba(15, 139, 141, 0.45);
    }

    .button.primary {
      background: var(--teal);
      border-color: var(--teal);
      color: white;
    }

    .metric-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(156px, 1fr));
      gap: 14px;
    }

    .metric-card,
    .panel,
    .subpanel,
    .alert-card {
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
      margin-top: 11px;
      color: var(--ink);
      font-size: 24px;
      font-weight: 850;
      line-height: 1.1;
      overflow-wrap: anywhere;
    }

    .metric-value.is-compact {
      font-size: 20px;
      line-height: 1.15;
    }

    .metric-detail {
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
      overflow-wrap: anywhere;
    }

    .tone-positive {
      color: var(--green);
    }

    .tone-negative {
      color: var(--rose);
    }

    .dashboard-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(320px, 0.9fr);
      gap: 18px;
      align-items: start;
      margin-top: 18px;
    }

    .stack {
      display: grid;
      gap: 18px;
      min-width: 0;
    }

    .panel {
      min-width: 0;
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

    .panel-body {
      padding: 16px;
    }

    .account-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }

    .subpanel {
      box-shadow: none;
      background: var(--surface-2);
      padding: 14px;
    }

    .subpanel-title {
      color: var(--ink);
      font-size: 14px;
      font-weight: 850;
    }

    .detail-list {
      display: grid;
      gap: 8px;
      margin: 12px 0 0;
      padding: 0;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.4;
      list-style: none;
    }

    .list-stack {
      display: grid;
      gap: 8px;
    }

    .list-row {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface-2);
      padding: 10px 12px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.42;
      overflow-wrap: anywhere;
    }

    .mono {
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      font-size: 12px;
    }

    .table-wrap {
      overflow-x: auto;
    }

    .data-table {
      width: 100%;
      min-width: 760px;
      border-collapse: collapse;
    }

    .data-table th {
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

    .data-table td {
      padding: 11px 13px;
      border-top: 1px solid var(--line);
      color: #263336;
      font-size: 13px;
      vertical-align: top;
    }

    .signal-sections {
      display: grid;
      gap: 14px;
    }

    .alert-card {
      box-shadow: none;
      background: var(--surface-2);
      padding: 14px;
    }

    .alert-level {
      color: var(--muted);
      font-size: 11px;
      font-weight: 850;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    .alert-title {
      margin-top: 8px;
      color: var(--ink);
      font-size: 14px;
      font-weight: 800;
    }

    .alert-meta,
    .alert-detail {
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.42;
    }

    @media (max-width: 1180px) {
      .metric-grid {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }

      .dashboard-grid {
        grid-template-columns: 1fr;
      }
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

      .toolbar {
        justify-content: flex-start;
      }

      .metric-grid,
      .account-grid {
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
        <h1>Operator Dashboard</h1>
        <p id="checked-at" class="subtle" style="margin-top: 10px;">Loading latest snapshot...</p>
      </div>
      <div class="centaur-menu-toolbar toolbar">
        <button id="refresh-button" class="button primary" type="button">Refresh</button>
        <?php centaurRenderNavigation('/dashboard.php'); ?>
      </div>
    </header>

    <section id="metric-cards" class="metric-grid"></section>

    <section class="dashboard-grid">
      <div class="stack">
        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">Account lanes</h2>
          </div>
          <div id="account-panel" class="panel-body"></div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">Paper open positions</h2>
          </div>
          <div id="positions-table" class="table-wrap"></div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">Recent paper orders</h2>
          </div>
          <div id="orders-table" class="table-wrap"></div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">Recent shadow proposals</h2>
          </div>
          <div id="proposals-table" class="table-wrap"></div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">Signal pipeline</h2>
          </div>
          <div id="signal-panels" class="panel-body signal-sections"></div>
        </div>
      </div>

      <div class="stack">
        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">Trade diagnostics</h2>
          </div>
          <div id="trade-diagnostics" class="panel-body list-stack"></div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">Centaur activity</h2>
          </div>
          <div id="activity-panel" class="panel-body list-stack"></div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">GA threshold advice</h2>
          </div>
          <div id="threshold-panel" class="panel-body list-stack"></div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">Holding-window fitness</h2>
          </div>
          <div id="holding-window-panel" class="panel-body list-stack"></div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">Broker accounts</h2>
          </div>
          <div id="broker-panel" class="panel-body list-stack"></div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">Live readiness</h2>
          </div>
          <div id="live-panel" class="panel-body list-stack"></div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">API cost</h2>
          </div>
          <div id="cost-panel" class="panel-body list-stack"></div>
        </div>

        <div class="panel">
          <div class="panel-head">
            <h2 class="panel-title">Alerts</h2>
          </div>
          <div id="alerts-panel" class="panel-body list-stack"></div>
        </div>
      </div>
    </section>
  </main>

  <script>
    const snapshotUrl = "/snapshot/";
    const refreshIntervalMs = 15000;

    const cardContainer = document.getElementById("metric-cards");
    const checkedAtNode = document.getElementById("checked-at");

    const accountPanel = document.getElementById("account-panel");
    const positionsTable = document.getElementById("positions-table");
    const ordersTable = document.getElementById("orders-table");
    const proposalsTable = document.getElementById("proposals-table");
    const signalPanels = document.getElementById("signal-panels");
    const tradeDiagnostics = document.getElementById("trade-diagnostics");
    const activityPanel = document.getElementById("activity-panel");
    const thresholdPanel = document.getElementById("threshold-panel");
    const holdingWindowPanel = document.getElementById("holding-window-panel");
    const brokerPanel = document.getElementById("broker-panel");
    const livePanel = document.getElementById("live-panel");
    const costPanel = document.getElementById("cost-panel");
    const alertsPanel = document.getElementById("alerts-panel");

    function fmtNumber(value, decimals = 2) {
      if (value === null || value === undefined || value === "") return "-";
      const number = Number(value);
      if (Number.isNaN(number)) return "-";
      return number.toFixed(decimals);
    }

    function fmtCurrency(value, decimals = 2) {
      if (value === null || value === undefined || value === "") return "-";
      const number = Number(value);
      if (Number.isNaN(number)) return "-";
      return `$${number.toFixed(decimals)}`;
    }

    function fmtSignedCurrency(value) {
      if (value === null || value === undefined || value === "") return "-";
      const number = Number(value);
      if (Number.isNaN(number)) return "-";
      return `$${number >= 0 ? "+" : ""}${number.toFixed(2)}`;
    }

    function fmtSignedPct(value) {
      if (value === null || value === undefined || value === "") return "-";
      const number = Number(value);
      if (Number.isNaN(number)) return "-";
      return `${number >= 0 ? "+" : ""}${number.toFixed(2)}%`;
    }

    function numberOrNull(value) {
      if (value === null || value === undefined || value === "") return null;
      const number = Number(value);
      return Number.isFinite(number) ? number : null;
    }

    function currencySymbol(currency) {
      return String(currency || "USD").trim().toUpperCase() === "GBP" ? "\u00a3" : "$";
    }

    function fmtCurrencyFor(value, currency = "USD", decimals = 2) {
      const number = numberOrNull(value);
      if (number === null) return "-";
      return `${currencySymbol(currency)}${number.toFixed(decimals)}`;
    }

    function fmtSignedCurrencyFor(value, currency = "USD") {
      const number = numberOrNull(value);
      if (number === null) return "-";
      return `${currencySymbol(currency)}${number >= 0 ? "+" : ""}${number.toFixed(2)}`;
    }

    function brokerAccounts(snapshot) {
      return Array.isArray(snapshot?.broker_accounts) ? snapshot.broker_accounts.filter(Boolean) : [];
    }

    function findBrokerAccount(snapshot, brokerId) {
      const expected = String(brokerId || "").trim().toLowerCase();
      if (!expected) return null;
      return brokerAccounts(snapshot).find((row) => String(row.broker_id || "").trim().toLowerCase() === expected) || null;
    }

    function brokerDayChange(account) {
      const equity = numberOrNull(account?.equity);
      const lastEquity = numberOrNull(account?.last_equity);
      if (equity === null || lastEquity === null) return null;
      return Number((equity - lastEquity).toFixed(6));
    }

    function brokerDayChangePct(account) {
      const change = brokerDayChange(account);
      const lastEquity = numberOrNull(account?.last_equity);
      if (change === null || !lastEquity) return null;
      return Number(((change / lastEquity) * 100).toFixed(6));
    }

    function toneClass(value) {
      const number = numberOrNull(value);
      if (number === null || number === 0) return "";
      return number > 0 ? "tone-positive" : "tone-negative";
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function renderList(target, items, emptyLabel = "Nothing recorded yet.") {
      const rows = Array.isArray(items) ? items.filter(Boolean) : [];
      if (!rows.length) {
        target.innerHTML = `<p class="subtle">${escapeHtml(emptyLabel)}</p>`;
        return;
      }
      target.innerHTML = rows.map((item) => `
        <div class="list-row">
          <span class="mono">${escapeHtml(item)}</span>
        </div>
      `).join("");
    }

    function renderTable(target, columns, rows, emptyLabel) {
      if (!Array.isArray(rows) || !rows.length) {
        target.innerHTML = `<div class="panel-body"><p class="subtle">${escapeHtml(emptyLabel)}</p></div>`;
        return;
      }
      const head = columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("");
      const body = rows.map((row) => `
        <tr>
          ${columns.map((column) => `<td class="${column.mono ? "mono" : ""}">${column.render(row)}</td>`).join("")}
        </tr>
      `).join("");
      target.innerHTML = `<table class="data-table">${`<thead><tr>${head}</tr></thead><tbody>${body}</tbody>`}</table>`;
    }

    function buildMetricCards(snapshot) {
      const latestTick = snapshot.latest_tick || {};
      const tickState = latestTick.state_snapshot_json || {};
      const marketGate = tickState.market_gate || {};
      const riskCfo = tickState.risk_cfo || {};
      const blockers = (snapshot.centaur_activity || {}).blockers || {};
      const account = snapshot.account_overview || {};
      const liveOverview = snapshot.live_execution_overview || {};
      const liveAccount = findBrokerAccount(snapshot, liveOverview.broker_id || "alpaca_live");
      const liveDayChange = brokerDayChange(liveAccount);
      const liveCurrency = liveAccount?.currency || "USD";
      const paperOpen = numberOrNull(account.open_positions_count) || 0;
      const paperSlots = numberOrNull(account.effective_max_open_positions)
        ?? numberOrNull(account.base_max_open_positions)
        ?? 10;

      const cards = [
        { label: "Latest tick", value: String(latestTick.status || "none").toUpperCase(), detail: latestTick.started_at || "-" },
        { label: "Market", value: marketGate.market_open ? "OPEN" : "CLOSED", detail: marketGate.reason || "-" },
        { label: "CFO", value: riskCfo.decision || "-", detail: riskCfo.reason || "-" },
        {
          label: "Paper day P/L",
          value: fmtSignedCurrency(account.day_change_usd),
          detail: `Alpaca Paper ${fmtSignedPct(account.day_change_pct)}`,
          tone: toneClass(account.day_change_usd)
        },
        {
          label: "Live day P/L",
          value: liveAccount ? fmtSignedCurrencyFor(liveDayChange, liveCurrency) : "-",
          detail: liveAccount
            ? `${liveAccount.broker_label || "Alpaca Live"} ${fmtSignedPct(brokerDayChangePct(liveAccount))}`
            : `${liveOverview.status || "not available"} follower snapshot`,
          tone: toneClass(liveDayChange)
        },
        { label: "Paper positions", value: String(paperOpen), detail: `slots ${paperOpen}/${paperSlots}` },
        { label: "Primary blocker", value: blockers.primary_stage || "-", detail: blockers.cfo_reason || "-" }
      ];

      cardContainer.innerHTML = cards.map((card) => `
        <article class="metric-card">
          <div class="metric-label">${escapeHtml(card.label)}</div>
          <div class="metric-value ${String(card.value || "").length > 12 ? "is-compact" : ""} ${card.tone || ""}">${escapeHtml(card.value)}</div>
          <div class="metric-detail">${escapeHtml(card.detail || "-")}</div>
        </article>
      `).join("");
    }

    function buildAccountPanel(snapshot) {
      const paper = snapshot.account_overview || {};
      const liveOverview = snapshot.live_execution_overview || {};
      const liveAccount = findBrokerAccount(snapshot, liveOverview.broker_id || "alpaca_live");
      const trading212Paper = findBrokerAccount(snapshot, "trading212_paper");
      const blocks = [];

      if (Object.keys(paper).length) {
        const paperOpen = numberOrNull(paper.open_positions_count) || 0;
        const paperSlots = numberOrNull(paper.effective_max_open_positions)
          ?? numberOrNull(paper.base_max_open_positions)
          ?? 10;
        blocks.push({
          title: "Alpaca Paper",
          rows: [
            `Paper execution lane | status ${paper.status || "-"}`,
            `Equity ${fmtCurrency(paper.equity)} | cash ${fmtCurrency(paper.cash)}`,
            `Day change ${fmtSignedCurrency(paper.day_change_usd)} (${fmtSignedPct(paper.day_change_pct)})`,
            `Open unrealized ${fmtSignedCurrency(paper.open_position_unrealized_pl_usd)}`,
            `Capital committed ${fmtCurrency(paper.capital_committed_usd)} | free ${fmtCurrency(paper.capital_free_usd)}`,
            `Positions ${paperOpen}/${paperSlots} | earned slots ${paper.earned_slots || 0}`
          ]
        });
      }

      if (liveAccount) {
        const liveCurrency = liveAccount.currency || "USD";
        blocks.push({
          title: liveAccount.broker_label || "Alpaca Live",
          rows: [
            `Approved same-as-paper follower | ${liveOverview.enabled ? "enabled" : "disabled"} | status ${liveOverview.status || liveAccount.status || "-"}`,
            `Equity ${fmtCurrencyFor(liveAccount.equity, liveCurrency)} | cash ${fmtCurrencyFor(liveAccount.cash, liveCurrency)}`,
            `Day change ${fmtSignedCurrencyFor(brokerDayChange(liveAccount), liveCurrency)} (${fmtSignedPct(brokerDayChangePct(liveAccount))})`,
            `Open unrealized ${fmtSignedCurrencyFor(liveAccount.open_position_unrealized_pl, liveCurrency)}`,
            `Position value ${fmtCurrencyFor(liveAccount.position_market_value, liveCurrency)} | envelope ${fmtCurrency(liveOverview.envelope_max_usd)}`,
            `Entry blockers ${(liveOverview.equity_entry_blockers || []).join(", ") || "none"}`
          ]
        });
      }

      if (trading212Paper) {
        const currency = trading212Paper.currency || "GBP";
        blocks.push({
          title: trading212Paper.broker_label || "Trading 212 Paper",
          rows: [
            `Separate paper equity lane | status ${trading212Paper.status || "-"}`,
            `Equity ${fmtCurrencyFor(trading212Paper.equity, currency)} | cash ${fmtCurrencyFor(trading212Paper.cash, currency)}`,
            `Day change ${fmtSignedCurrencyFor(brokerDayChange(trading212Paper), currency)} (${fmtSignedPct(brokerDayChangePct(trading212Paper))})`,
            `Open unrealized ${fmtSignedCurrencyFor(trading212Paper.open_position_unrealized_pl, currency)}`,
            `Captured ${trading212Paper.captured_at || "-"}`
          ]
        });
      }

      if (!blocks.length) {
        accountPanel.innerHTML = `<p class="subtle">No account snapshots available yet.</p>`;
        return;
      }

      accountPanel.innerHTML = blocks.map((block) => `
        <div class="subpanel">
          <h3 class="subpanel-title">${escapeHtml(block.title)}</h3>
          <ul class="detail-list">
            ${block.rows.map((row) => `<li>${escapeHtml(row)}</li>`).join("")}
          </ul>
        </div>
      `).join("");
      accountPanel.className = "panel-body account-grid";
    }

    function buildSignalPanels(activity) {
      const sections = [
        { title: "Raw signals", rows: activity.raw_signal_preview || [], empty: "No raw signals captured on this tick." },
        { title: "Suppressed signals", rows: activity.suppressed_signal_preview || [], empty: "No suppressed signals captured on this tick." },
        { title: "Surviving signals", rows: activity.surviving_signal_preview || [], empty: "No surviving signals on this tick." }
      ];

      signalPanels.innerHTML = sections.map((section) => {
        if (!section.rows.length) {
          return `<section class="subpanel"><h3 class="subpanel-title">${escapeHtml(section.title)}</h3><p class="subtle" style="margin-top: 12px;">${escapeHtml(section.empty)}</p></section>`;
        }
        return `
          <section class="subpanel">
            <h3 class="subpanel-title">${escapeHtml(section.title)}</h3>
            <div class="table-wrap" style="margin-top: 12px;">
              <table class="data-table">
                <thead>
                  <tr>
                    <th>Strategy</th>
                    <th>Symbol</th>
                    <th>Status</th>
                    <th>Score</th>
                    <th>Fitness</th>
                    <th>Target</th>
                  </tr>
                </thead>
                <tbody>
                  ${section.rows.slice(0, 8).map((row) => `
                    <tr>
                      <td>${escapeHtml(row.strategy_id || "-")}</td>
                      <td class="mono">${escapeHtml((row.symbol || "-").toUpperCase())}</td>
                      <td>${escapeHtml(row.allocation_status || "-")}</td>
                      <td>${fmtNumber(row.signal_score, 2)}</td>
                      <td>${fmtNumber(row.fitness_composite_score, 2)}</td>
                      <td>${fmtNumber(row.target_return_pct, 2)}%</td>
                    </tr>
                  `).join("")}
                </tbody>
              </table>
            </div>
          </section>
        `;
      }).join("");
    }

    async function loadSnapshot() {
      checkedAtNode.textContent = "Refreshing...";
      const response = await fetch(snapshotUrl, { cache: "no-store" });
      if (!response.ok) {
        throw new Error(`Snapshot request failed: ${response.status}`);
      }
      return response.json();
    }

    function renderSnapshot(snapshot) {
      checkedAtNode.textContent = `Checked ${snapshot.checked_at || "-"} | auto refresh every 15s`;
      buildMetricCards(snapshot);
      buildAccountPanel(snapshot);

      renderTable(
        positionsTable,
        [
          { label: "Symbol", mono: true, render: (row) => escapeHtml(row.symbol || "-") },
          { label: "Qty", render: (row) => fmtNumber(row.qty, 4) },
          { label: "Value", render: (row) => fmtCurrency(row.market_value_usd) },
          { label: "Entry", render: (row) => fmtCurrency(row.avg_entry_price, 4) },
          { label: "Current", render: (row) => fmtCurrency(row.current_price, 4) },
          { label: "Unrealized", render: (row) => `${fmtSignedCurrency(row.unrealized_pl_usd)} (${fmtSignedPct(row.unrealized_pl_pct)})` },
          { label: "Stop", render: (row) => fmtCurrency(row.stop_loss_price, 4) },
          { label: "Target", render: (row) => fmtCurrency(row.target_price, 4) },
          { label: "Policy", render: (row) => escapeHtml(row.managed_exit_policy || "-") },
          { label: "Exit", render: (row) => escapeHtml(row.exit_state || "-") }
        ],
        snapshot.open_positions || [],
        "No open positions."
      );

      renderTable(
        ordersTable,
        [
          { label: "When", render: (row) => escapeHtml(row.submitted_at || row.captured_at || "-") },
          { label: "Symbol", mono: true, render: (row) => escapeHtml(row.symbol || "-") },
          { label: "Status", render: (row) => escapeHtml(row.status || "-") },
          { label: "Side", render: (row) => escapeHtml(row.side || "-") },
          { label: "Notional", render: (row) => fmtCurrency(row.notional_usd) },
          { label: "Strategy", render: (row) => escapeHtml(row.strategy_id || "-") }
        ],
        snapshot.recent_orders || [],
        "No recent paper orders."
      );

      renderTable(
        proposalsTable,
        [
          { label: "When", render: (row) => escapeHtml(row.proposed_at || "-") },
          { label: "Symbol", mono: true, render: (row) => escapeHtml(row.symbol || "-") },
          { label: "Status", render: (row) => escapeHtml(row.status || "-") },
          { label: "Strategy", render: (row) => escapeHtml(row.strategy_id || "-") },
          { label: "Score", render: (row) => fmtNumber(row.signal_score ?? row.opportunity_score, 3) }
        ],
        snapshot.recent_proposals || [],
        "No recent shadow proposals."
      );

      buildSignalPanels(snapshot.centaur_activity || {});
      renderList(tradeDiagnostics, snapshot.trade_diagnostics || [], "No diagnostics recorded yet.");

      const activity = snapshot.centaur_activity || {};
      const scan = activity.scan || {};
      const flow = activity.flow || {};
      const blockers = activity.blockers || {};
      renderList(
        activityPanel,
        [
          `Scan | mode=${scan.mode || "-"} | candidates=${scan.candidates_found || 0} | selected=${scan.selected_candidates || 0} | bars=${scan.bars_available || 0} | top=${scan.top_symbol || "-"}`,
          `Flow | raw=${flow.raw_signals || 0} | survived=${flow.surviving_signals || 0} | suppressed=${flow.suppressed_signals || 0} | proposals=${flow.proposals_created || 0} | cfo=${flow.cfo_reason || "-"}`,
          `Blockers | stage=${blockers.primary_stage || "-"} | market=${blockers.market_reason || "-"} | cfo=${blockers.cfo_reason || "-"}`
        ],
        "No activity snapshot yet."
      );

      const thresholdAdvice = snapshot.threshold_advice || {};
      const thresholdGene = thresholdAdvice.gene || {};
      const thresholdTest = thresholdAdvice.test || {};
      const thresholdAll = thresholdAdvice.all || {};
      const adaptiveThreshold = thresholdAdvice.adaptive_state || {};
      renderList(
        thresholdPanel,
        [
          `Action ${thresholdAdvice.action || "-"} | current ${fmtNumber(thresholdAdvice.current_threshold, 2)} | recommended ${fmtNumber(thresholdAdvice.recommended_threshold, 2)} | confidence ${thresholdAdvice.confidence || "-"}`,
          `Adaptive ${thresholdAdvice.adaptive_enabled ? "on" : "off"} | effective ${fmtNumber(adaptiveThreshold.effective_threshold, 2)} | rails ${fmtNumber(adaptiveThreshold.ceiling, 2)}..${fmtNumber(adaptiveThreshold.floor, 2)} | band +/-${fmtNumber(adaptiveThreshold.band_width, 2)} | updated ${adaptiveThreshold.updated_at || "-"}`,
          `Evidence | ticks ${thresholdAdvice.tick_count || 0} | train ${thresholdAdvice.train_tick_count || 0} | test ${thresholdAdvice.test_tick_count || 0} | test score ${fmtNumber(thresholdTest.score, 2)}`,
          `Policy | base ${fmtNumber(thresholdGene.base_threshold, 2)} | target ${thresholdGene.target_low || "-"}-${thresholdGene.target_high || "-"} per tick | ending ${fmtNumber(thresholdAll.ending_threshold, 2)}`,
          `Trade-aware | avg tradeable ${fmtNumber(thresholdAll.avg_tradeable_survivors, 2)}/tick | avg tradeable fit ${fmtNumber(thresholdAll.avg_tradeable_fitness, 2)} | non-tradeable survivors ${thresholdAll.non_tradeable_survivors || 0}`,
          thresholdAdvice.reason || "-",
          adaptiveThreshold.reason || ""
        ],
        "No GA threshold advice available yet."
      );

      const holdingAdvice = snapshot.holding_window_advice || {};
      const holdingRecommendation = holdingAdvice.recommendation || {};
      const holdingSamples = holdingAdvice.sample_counts || {};
      const holdingAll = holdingAdvice.fixed_windows_all || {};
      const holding7d = holdingAdvice.fixed_windows_7d || {};
      const holdingPolicy = holdingAdvice.policy_stats_all || {};
      const metricText = (metric) => {
        metric = metric || {};
        if (!metric.n) return "n=0";
        return `n=${metric.n} avg=${fmtNumber(metric.avg_return_pct, 2)}% win=${fmtNumber(Number(metric.win_rate || 0) * 100, 1)}% score=${fmtNumber(metric.score, 2)}`;
      };
      renderList(
        holdingWindowPanel,
        [
          `Strategy ${holdingAdvice.strategy_id || "-"} | current ${holdingAdvice.current_window || "-"} | action ${holdingRecommendation.action || "-"} | confidence ${holdingRecommendation.confidence || "-"}`,
          `Candidate ${holdingRecommendation.candidate_policy || "-"}`,
          `Samples | all ${holdingSamples.complete_15m_1h_1d || 0} | 30d ${holdingSamples.complete_15m_1h_1d_30d || 0} | 7d ${holdingSamples.complete_15m_1h_7d || 0}`,
          `All-time | 15m ${metricText(holdingAll["15m"])} | 1h ${metricText(holdingAll["1h"])} | 1d ${metricText(holdingAll["1d"])}`,
          `Recent 7d | 15m ${metricText(holding7d["15m"])} | 1h ${metricText(holding7d["1h"])}`,
          `Dynamic | 1h profit else 1d ${metricText(holdingPolicy.take_1h_profit_else_1d)}`,
          holdingRecommendation.reason || "-"
        ],
        "No holding-window fitness advice available yet."
      );

      renderList(
        brokerPanel,
        brokerAccounts(snapshot).map((account) => {
          const currency = account.currency || "USD";
          const roles = Array.isArray(account.roles) && account.roles.length ? account.roles.join(",") : "no active role";
          return `${account.broker_label || account.broker_id || "-"} | ${account.status || "-"} | ${roles} | equity ${fmtCurrencyFor(account.equity, currency)} | open P/L ${fmtSignedCurrencyFor(account.open_position_unrealized_pl, currency)} | snapshot ${account.has_snapshot ? account.captured_at || "yes" : "missing"}`;
        }),
        "No broker snapshots recorded yet."
      );
      const liveOverview = snapshot.live_execution_overview || {};
      renderList(
        livePanel,
        [
          `Status ${liveOverview.status || "-"} | enabled=${liveOverview.enabled ? "yes" : "no"} | broker=${liveOverview.broker_id || "-"}`,
          `Envelope | slot=${fmtCurrency(liveOverview.slot_size_usd)} | max_positions=${liveOverview.max_open_positions || "-"} | max_orders_per_tick=${liveOverview.max_orders_per_tick || "-"}`,
          `Protection | drawdown=${fmtCurrency(liveOverview.max_daily_drawdown_usd)} | kill_switch=${liveOverview.kill_switch_on ? "on" : "off"} | activation_ack=${liveOverview.activation_ack_present ? "yes" : "no"}`,
          `Equity entries | PDT basis=${fmtCurrency(liveOverview.pdt_basis_equity_usd)} | min=${fmtCurrency(liveOverview.pdt_min_equity_usd)} | blockers=${(liveOverview.equity_entry_blockers || []).join(", ") || "none"}`,
          liveOverview.note || ""
        ],
        "No live-readiness state available."
      );

      const cost = snapshot.cost_overview || {};
      const today = cost.today || {};
      const yesterday = cost.yesterday || {};
      renderList(
        costPanel,
        [
          `Pricing | configured=${cost.pricing_configured ? "yes" : "no"} | gemini_pricing=${cost.gemini_pricing_configured ? "yes" : "no"} | usd_to_gbp=${fmtNumber(cost.usd_to_gbp, 4)}`,
          `Today | est=${fmtCurrency(today.estimated_cost_usd, 4)} | requests=${today.request_count || 0}`,
          `Yesterday | est=${fmtCurrency(yesterday.estimated_cost_usd, 4)} | requests=${yesterday.request_count || 0}`,
          ...((cost.notes || []).slice(0, 3))
        ],
        "No cost data recorded yet."
      );

      const alerts = Array.isArray(snapshot.alerts) ? snapshot.alerts : [];
      if (!alerts.length) {
        alertsPanel.innerHTML = `<p class="subtle">No current alerts.</p>`;
      } else {
        alertsPanel.innerHTML = alerts.slice(0, 8).map((alert) => `
          <article class="alert-card">
            <div class="alert-level">${escapeHtml(alert.level || "info")}</div>
            <div class="alert-title">${escapeHtml(alert.summary || "-")}</div>
            <div class="alert-meta">${escapeHtml(alert.at || "-")}</div>
            <div class="alert-detail">${escapeHtml(alert.detail || "-")}</div>
          </article>
        `).join("");
      }
    }

    async function refreshSnapshot() {
      try {
        const snapshot = await loadSnapshot();
        renderSnapshot(snapshot);
      } catch (error) {
        checkedAtNode.textContent = `Dashboard refresh failed: ${error.message}`;
      }
    }

    document.getElementById("refresh-button").addEventListener("click", refreshSnapshot);
    refreshSnapshot();
    window.setInterval(refreshSnapshot, refreshIntervalMs);
  </script>
</body>
</html>

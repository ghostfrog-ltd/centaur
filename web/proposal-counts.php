<?php
declare(strict_types=1);

header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Centaur Proposal Counts</title>
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
      --gold: #b47d0b;
      --rose: #b93f56;
      --shadow: 0 14px 34px rgba(18, 31, 32, 0.07);
    }

    * { box-sizing: border-box; }

    body {
      margin: 0;
      background:
        linear-gradient(180deg, rgba(15, 139, 141, 0.08), rgba(244, 247, 245, 0) 30rem),
        var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    button, select { font: inherit; }

    .shell {
      width: min(1480px, calc(100% - 32px));
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

    .controls {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 10px;
      margin-bottom: 16px;
    }

    select {
      min-height: 40px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      color: var(--ink);
      padding: 0 34px 0 12px;
      font-weight: 750;
    }

    .status {
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }

    .cards {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 18px;
    }

    .card,
    .panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.92);
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .card {
      min-height: 112px;
      padding: 14px;
    }

    .card-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    .card-value {
      margin-top: 12px;
      font-size: clamp(24px, 2.4vw, 34px);
      font-weight: 900;
      line-height: 1;
    }

    .card-detail {
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }

    .panel + .panel { margin-top: 18px; }

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

    .table-wrap {
      max-height: 620px;
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
      z-index: 1;
      background: #f8fbf9;
      color: var(--muted);
      font-size: 11px;
      font-weight: 850;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    th:first-child,
    td:first-child,
    th:nth-child(2),
    td:nth-child(2),
    th:nth-child(3),
    td:nth-child(3),
    th:nth-child(4),
    td:nth-child(4),
    th:nth-child(5),
    td:nth-child(5) {
      text-align: left;
    }

    .empty,
    .error {
      margin: 0;
      padding: 18px;
      color: var(--muted);
      font-size: 14px;
    }

    .error { color: var(--rose); }

    @media (max-width: 980px) {
      .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .topbar { align-items: stretch; flex-direction: column; }
      .toolbar { justify-content: stretch; }
      .button { flex: 1 1 auto; }
    }

    @media (max-width: 620px) {
      .shell { width: min(100% - 24px, 1480px); padding-top: 16px; }
      .cards { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">Project Centaur</p>
        <h1>Proposal Counts</h1>
      </div>
      <nav class="toolbar" aria-label="Primary navigation">
        <a class="button primary" href="/proposal-counts.php">Proposal Counts</a>
        <a class="button" href="/">Slot Compounding</a>
        <a class="button" href="/flow.php">Flow Map</a>
        <a class="button" href="/glossary.php">Glossary</a>
        <a class="button" href="/dashboard.php">Dashboard</a>
      </nav>
    </header>

    <section class="controls" aria-label="Proposal count controls">
      <label for="days">Window</label>
      <select id="days">
        <option value="7">Last 7 days</option>
        <option value="30">Last 30 days</option>
        <option value="90" selected>Last 90 days</option>
        <option value="180">Last 180 days</option>
        <option value="366">Last 366 days</option>
      </select>
      <button id="refresh" class="button" type="button">Refresh</button>
      <span id="status" class="status">Loading proposal counts...</span>
    </section>

    <section id="cards" class="cards" aria-label="Proposal count summary"></section>

    <section class="panel">
      <div class="panel-head">
        <div class="panel-title">Generated Proposals By Day, Lane, Environment, Strategy</div>
        <span id="generated-badge" class="badge">0 rows</span>
      </div>
      <div id="generated-table" class="table-wrap"></div>
    </section>

    <section class="panel">
      <div class="panel-head">
        <div class="panel-title">Proposal-Linked Broker Lanes</div>
        <span id="execution-badge" class="badge">0 rows</span>
      </div>
      <div id="execution-table" class="table-wrap"></div>
    </section>
  </main>

  <script>
    const daysSelect = document.getElementById("days");
    const refreshButton = document.getElementById("refresh");
    const statusNode = document.getElementById("status");
    const cardsNode = document.getElementById("cards");
    const generatedTable = document.getElementById("generated-table");
    const executionTable = document.getElementById("execution-table");
    const generatedBadge = document.getElementById("generated-badge");
    const executionBadge = document.getElementById("execution-badge");

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function fmtNumber(value, decimals = 0) {
      if (value === null || value === undefined || value === "") return "-";
      const number = Number(value);
      if (!Number.isFinite(number)) return "-";
      return number.toLocaleString(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals
      });
    }

    function fmtDateTime(value) {
      if (!value) return "-";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return date.toLocaleString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit"
      });
    }

    function uniqueStrategies(...sections) {
      const names = new Set();
      sections.forEach((section) => {
        (section?.strategies || []).forEach((strategy) => names.add(strategy));
      });
      return Array.from(names).sort((a, b) => a.localeCompare(b));
    }

    function renderCards(report) {
      const generated = report.generated || {};
      const executions = report.proposal_linked_executions || {};
      const generatedStrategies = Object.keys(generated.strategy_totals || {}).length;
      const executionStrategies = Object.keys(executions.strategy_totals || {}).length;
      const cards = [
        {
          label: "Generated",
          value: fmtNumber(generated.total_count || 0),
          detail: `${generatedStrategies} strategies`
        },
        {
          label: "Broker linked",
          value: fmtNumber(executions.total_count || 0),
          detail: `${fmtNumber(executions.order_count || 0)} order rows`
        },
        {
          label: "Window",
          value: `${fmtNumber(report.days || 0)}d`,
          detail: `${report.runtime?.environment || "-"} / ${report.runtime?.mode || "-"}`
        },
        {
          label: "Checked",
          value: fmtDateTime(report.checked_at),
          detail: report.backend || "-"
        }
      ];
      cardsNode.innerHTML = cards.map((card) => `
        <article class="card">
          <div class="card-label">${escapeHtml(card.label)}</div>
          <div class="card-value">${escapeHtml(card.value)}</div>
          <div class="card-detail">${escapeHtml(card.detail)}</div>
        </article>
      `).join("");
    }

    function renderCountTable(target, badge, section, strategies, emptyLabel, includeOrders = false) {
      const rows = Array.isArray(section?.rows) ? section.rows : [];
      badge.textContent = `${fmtNumber(rows.length)} rows`;
      if (!rows.length) {
        target.innerHTML = `<p class="empty">${escapeHtml(emptyLabel)}</p>`;
        return;
      }

      const strategyHeaders = strategies.map((strategy) => `<th>${escapeHtml(shortStrategy(strategy))}</th>`).join("");
      const orderHeader = includeOrders ? "<th>Orders</th>" : "";
      const body = rows.map((row) => {
        const counts = row.strategy_counts || {};
        const strategyCells = strategies.map((strategy) => `<td>${fmtNumber(counts[strategy] || 0)}</td>`).join("");
        const orderCell = includeOrders ? `<td>${fmtNumber(row.order_count || 0)}</td>` : "";
        return `
          <tr>
            <td>${escapeHtml(row.proposal_date || "-")}</td>
            <td>${escapeHtml(row.lane || "-")}</td>
            <td>${escapeHtml(row.environment || "-")}</td>
            <td>${escapeHtml(row.mode || "-")}</td>
            <td>${escapeHtml(row.allocation_status || "untracked")}</td>
            ${strategyCells}
            <td>${fmtNumber(row.total_count || 0)}</td>
            ${orderCell}
            <td>${fmtNumber(row.avg_base_signal_score, 2)}</td>
            <td>${fmtNumber(row.avg_signal_score, 2)}</td>
            <td>${fmtNumber(row.avg_fitness_composite_score, 2)}</td>
            <td>${fmtNumber(row.min_signal_score, 2)}</td>
            <td>${fmtNumber(row.max_signal_score, 2)}</td>
          </tr>
        `;
      }).join("");

      target.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>Day</th>
              <th>Lane</th>
              <th>Environment</th>
              <th>Mode</th>
              <th>Fitness status</th>
              ${strategyHeaders}
              <th>Total</th>
              ${orderHeader}
              <th>Avg base</th>
              <th>Avg score</th>
              <th>Avg fitness</th>
              <th>Min</th>
              <th>Max</th>
            </tr>
          </thead>
          <tbody>${body}</tbody>
        </table>
      `;
    }

    function shortStrategy(strategy) {
      return String(strategy || "unassigned")
        .replace("mean_reversion.", "mr.")
        .replace("crypto_momentum.", "cm.")
        .replace("momentum.", "mom.");
    }

    async function loadProposalCounts() {
      const days = daysSelect.value || "90";
      statusNode.textContent = "Loading proposal counts...";
      refreshButton.disabled = true;
      try {
        const response = await fetch(`/api/proposal_counts.php?days=${encodeURIComponent(days)}`, {
          headers: { "Accept": "application/json" },
          cache: "no-store"
        });
        const report = await response.json();
        if (!response.ok || !report.ok) {
          throw new Error(report.detail || report.error || `HTTP ${response.status}`);
        }
        const strategies = uniqueStrategies(report.generated, report.proposal_linked_executions);
        renderCards(report);
        renderCountTable(
          generatedTable,
          generatedBadge,
          report.generated,
          strategies,
          "No generated proposal rows found for this window."
        );
        renderCountTable(
          executionTable,
          executionBadge,
          report.proposal_linked_executions,
          strategies,
          "No proposal-linked broker lane rows found for this window.",
          true
        );
        statusNode.textContent = `Checked ${fmtDateTime(report.checked_at)}`;
      } catch (error) {
        statusNode.textContent = `Load failed: ${error.message}`;
        generatedTable.innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
        executionTable.innerHTML = "";
      } finally {
        refreshButton.disabled = false;
      }
    }

    refreshButton.addEventListener("click", loadProposalCounts);
    daysSelect.addEventListener("change", loadProposalCounts);
    loadProposalCounts();
  </script>
</body>
</html>

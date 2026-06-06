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
  <title>Centaur Profit Lock Review</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f7f5;
      --surface: #ffffff;
      --surface-2: #eef4f0;
      --ink: #172022;
      --muted: #667276;
      --line: #d7e1dc;
      --teal: #0f8b8d;
      --teal-dark: #096669;
      --green: #258b57;
      --rose: #c94b5f;
      --gold: #c98f13;
      --blue: #3867d6;
      --shadow: 0 16px 40px rgba(18, 31, 32, 0.08);
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      background:
        linear-gradient(180deg, rgba(15, 139, 141, 0.08), rgba(245, 247, 245, 0) 34rem),
        var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    button, select { font: inherit; }
    h1, h2, h3, p { margin: 0; }
    .shell {
      width: min(1480px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0 36px;
    }
    .topbar {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
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
      font-size: clamp(30px, 3vw, 48px);
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
    .control-row {
      display: grid;
      grid-template-columns: repeat(2, minmax(160px, 220px));
      gap: 10px;
    }
    select, .button {
      min-height: 42px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      color: var(--ink);
      font-weight: 750;
      padding: 0 14px;
      box-shadow: 0 6px 18px rgba(18, 31, 32, 0.05);
    }
    .button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }
    .button.primary {
      border-color: var(--teal);
      background: var(--teal);
      color: #ffffff;
    }
    .grid {
      display: grid;
      grid-template-columns: minmax(0, 1.55fr) minmax(360px, 0.85fr);
      gap: 18px;
    }
    .cards {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 18px;
    }
    .card, .panel {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface);
      box-shadow: var(--shadow);
    }
    .card {
      min-height: 136px;
      padding: 16px;
    }
    .card-label, .mini-label, th {
      color: var(--muted);
      font-size: 12px;
      font-weight: 850;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }
    .card-value {
      margin-top: 8px;
      font-size: clamp(28px, 3vw, 42px);
      line-height: 1;
      font-weight: 850;
      letter-spacing: 0;
    }
    .card-detail {
      margin-top: 8px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.35;
    }
    .positive { color: var(--green); }
    .negative { color: var(--rose); }
    .warning { color: var(--gold); }
    .blue { color: var(--blue); }
    .panel { overflow: hidden; }
    .panel + .panel { margin-top: 18px; }
    .panel-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 16px;
      border-bottom: 1px solid var(--line);
    }
    .panel-title {
      font-size: 18px;
      font-weight: 850;
    }
    .panel-body { padding: 16px; }
    .chart {
      height: 220px;
      display: grid;
      grid-template-columns: repeat(var(--bars, 12), minmax(8px, 1fr));
      align-items: end;
      gap: 4px;
      padding: 12px 0 0;
      border-bottom: 1px solid var(--line);
    }
    .bar {
      min-height: 2px;
      border-radius: 5px 5px 0 0;
      background: var(--teal);
      opacity: 0.84;
    }
    .bar.peak { background: var(--green); }
    .bar.after-peak { background: var(--gold); }
    .two-up {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    .mini-card {
      min-height: 106px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface-2);
      padding: 14px;
    }
    .mini-value {
      margin-top: 8px;
      font-size: 24px;
      font-weight: 850;
      line-height: 1.1;
    }
    .mini-detail {
      margin-top: 6px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.35;
    }
    .table-wrap { overflow-x: auto; }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 760px;
    }
    th, td {
      padding: 12px 14px;
      text-align: left;
      border-bottom: 1px solid var(--line);
      white-space: nowrap;
      font-size: 14px;
    }
    td code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 13px;
    }
    .list {
      display: grid;
      gap: 10px;
    }
    .notice {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: var(--surface-2);
      padding: 13px;
    }
    .notice strong {
      display: block;
      margin-bottom: 4px;
    }
    .status {
      margin-top: 12px;
      color: var(--muted);
      font-size: 13px;
    }
    .empty {
      color: var(--muted);
      padding: 12px 0;
    }
    @media (max-width: 1120px) {
      .grid, .cards { grid-template-columns: 1fr; }
      .two-up { grid-template-columns: 1fr; }
    }
    @media (max-width: 720px) {
      .shell { width: min(100% - 20px, 1480px); padding-top: 14px; }
      .topbar { display: block; }
      .toolbar { justify-content: flex-start; margin-top: 14px; }
      .control-row { grid-template-columns: 1fr; }
      h1 { font-size: 34px; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div>
        <p class="eyebrow">Project Centaur</p>
        <h1>Profit Lock Review</h1>
        <p id="subtitle" class="subtle">Read-only peak, giveback, carryover, and exit-quality evidence.</p>
      </div>
      <div class="toolbar">
        <div class="control-row">
          <select id="hours" aria-label="Review window">
            <option value="24" selected>Last 24h</option>
            <option value="48">Last 48h</option>
            <option value="72">Last 72h</option>
            <option value="168">Last 7d</option>
          </select>
          <select id="broker" aria-label="Broker">
            <option value="alpaca_paper" selected>Alpaca Paper</option>
            <option value="alpaca_live">Alpaca Live</option>
          </select>
        </div>
        <button id="refresh" class="button primary" type="button">Refresh</button>
        <?php centaurRenderNavigation('/profit-lock-review.php'); ?>
      </div>
    </header>

    <section id="cards" class="cards" aria-label="Profit lock summary"></section>

    <section class="grid">
      <div>
        <section class="panel" aria-label="Account curve">
          <div class="panel-head">
            <div class="panel-title">Account Curve</div>
            <span id="curve-badge" class="subtle">loading</span>
          </div>
          <div class="panel-body">
            <div id="curve-chart" class="chart"></div>
            <p id="curve-note" class="status">Loading account snapshots...</p>
          </div>
        </section>

        <section class="panel" aria-label="Trades open at peak">
          <div class="panel-head">
            <div class="panel-title">Trades Open At Peak</div>
            <span id="peak-trades-badge" class="subtle">0 rows</span>
          </div>
          <div id="peak-trades" class="table-wrap"></div>
        </section>

        <section class="panel" aria-label="Carryover closes">
          <div class="panel-head">
            <div class="panel-title">Carryover Closes</div>
            <span id="carryover-badge" class="subtle">0 rows</span>
          </div>
          <div id="carryover" class="table-wrap"></div>
        </section>
      </div>

      <aside>
        <section class="panel" aria-label="What-if locks">
          <div class="panel-head">
            <div class="panel-title">What If Locks</div>
            <span class="subtle">observe-only</span>
          </div>
          <div id="locks" class="panel-body list"></div>
        </section>

        <section class="panel" aria-label="System learning">
          <div class="panel-head">
            <div class="panel-title">System Learning</div>
            <span class="subtle">machine-readable</span>
          </div>
          <div id="learning" class="panel-body list"></div>
        </section>

        <section class="panel" aria-label="Recommendations">
          <div class="panel-head">
            <div class="panel-title">Recommendations</div>
            <span class="subtle">no auto-change</span>
          </div>
          <div id="recommendations" class="panel-body list"></div>
        </section>

        <section class="panel" aria-label="Diagnostics">
          <div class="panel-head">
            <div class="panel-title">Diagnostics</div>
            <span class="subtle">read-only</span>
          </div>
          <div id="diagnostics" class="panel-body list"></div>
        </section>
      </aside>
    </section>

    <p id="status" class="status">Loading...</p>
  </main>

  <script>
    const nodes = {
      hours: document.getElementById("hours"),
      broker: document.getElementById("broker"),
      refresh: document.getElementById("refresh"),
      subtitle: document.getElementById("subtitle"),
      cards: document.getElementById("cards"),
      curveBadge: document.getElementById("curve-badge"),
      chart: document.getElementById("curve-chart"),
      curveNote: document.getElementById("curve-note"),
      peakTradesBadge: document.getElementById("peak-trades-badge"),
      peakTrades: document.getElementById("peak-trades"),
      carryoverBadge: document.getElementById("carryover-badge"),
      carryover: document.getElementById("carryover"),
      locks: document.getElementById("locks"),
      learning: document.getElementById("learning"),
      recommendations: document.getElementById("recommendations"),
      diagnostics: document.getElementById("diagnostics"),
      status: document.getElementById("status")
    };

    let report = null;

    function fmtMoney(value) {
      const number = Number(value);
      if (!Number.isFinite(number)) return "-";
      const sign = number >= 0 ? "+" : "-";
      return `${sign}$${Math.abs(number).toFixed(2)}`;
    }

    function fmtNumber(value, decimals = 1) {
      const number = Number(value);
      return Number.isFinite(number) ? number.toFixed(decimals) : "-";
    }

    function fmtPct(value) {
      const number = Number(value);
      return Number.isFinite(number) ? `${number.toFixed(2)}%` : "-";
    }

    function fmtDate(value) {
      if (!value) return "-";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return String(value);
      return new Intl.DateTimeFormat(undefined, {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit"
      }).format(date);
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function toneForMoney(value) {
      const number = Number(value);
      if (!Number.isFinite(number) || number === 0) return "";
      return number > 0 ? "positive" : "negative";
    }

    function render() {
      if (!report) return;
      const curve = report.account_curve || {};
      const peak = curve.peak || {};
      const final = curve.final || {};
      const tradeReview = report.trade_review || {};
      const openAtPeak = tradeReview.open_at_peak || {};
      const carryover = tradeReview.carryover_closes || {};
      const sameWindow = tradeReview.same_window_closes || {};
      const peakChange = Number(peak.day_change);
      const finalChange = Number(final.day_change);
      const giveback = Number(curve.giveback_usd);
      const peakTime = fmtDate(peak.captured_at);

      nodes.subtitle.textContent = `${report.window?.label || "Review window"} | ${fmtDate(report.window?.start_at)} to ${fmtDate(report.window?.end_at)} | ${report.broker_id || "-"}`;
      nodes.cards.innerHTML = [
        {
          label: "Peak Day P/L",
          value: fmtMoney(peakChange),
          detail: `High-water at ${peakTime}`,
          cls: toneForMoney(peakChange)
        },
        {
          label: "Final Day P/L",
          value: fmtMoney(finalChange),
          detail: `Latest account snapshot at ${fmtDate(final.captured_at)}`,
          cls: toneForMoney(finalChange)
        },
        {
          label: "Profit Given Back",
          value: fmtMoney(-giveback),
          detail: `${fmtPct(curve.giveback_pct_of_peak)} of positive peak`,
          cls: giveback > 0 ? "warning" : "positive"
        },
        {
          label: "Open At Peak",
          value: String(openAtPeak.count || 0),
          detail: `${openAtPeak.red_after_peak_count || 0} red later / ${openAtPeak.weak_or_flat_after_peak_count || 0} weak green`,
          cls: (openAtPeak.red_after_peak_count || 0) > 0 ? "negative" : "blue"
        },
        {
          label: "Same-Window P/L",
          value: fmtMoney(sameWindow.realized_pnl_usd),
          detail: `${sameWindow.count || 0} closed trades, ${fmtPct((sameWindow.win_rate || 0) * 100)} win rate`,
          cls: toneForMoney(sameWindow.realized_pnl_usd)
        },
        {
          label: "Carryover P/L",
          value: fmtMoney(carryover.realized_pnl_usd),
          detail: `${carryover.count || 0} closes from before the window`,
          cls: toneForMoney(carryover.realized_pnl_usd)
        },
        {
          label: "Profit Capture",
          value: `${fmtNumber(report.config?.paper_profit_capture_pct, 2)}%`,
          detail: "Current paper setting, shown for review only",
          cls: "blue"
        },
        {
          label: "Snapshots",
          value: String(curve.displayed_points || curve.sampled || 0),
          detail: `${curve.sampled || 0} sampled, current broker-day baseline`,
          cls: "blue"
        }
      ].map((card) => `
        <article class="card">
          <div class="card-label">${escapeHtml(card.label)}</div>
          <div class="card-value ${card.cls}">${escapeHtml(card.value)}</div>
          <div class="card-detail">${escapeHtml(card.detail)}</div>
        </article>
      `).join("");

      renderCurve();
      renderPeakTrades();
      renderCarryover();
      renderLocks();
      renderLearning();
      renderNotices(nodes.recommendations, report.recommendations || []);
      renderNotices(nodes.diagnostics, report.diagnostics || []);
      nodes.status.textContent = report.scope_note || "Read-only report.";
    }

    function renderCurve() {
      const points = (report.account_curve?.points || []).filter((point) => Number.isFinite(Number(point.day_change)));
      nodes.curveBadge.textContent = `${points.length} current-day points`;
      if (!points.length) {
        nodes.chart.innerHTML = "";
        nodes.curveNote.textContent = "No account curve points are available.";
        return;
      }
      const peakAt = report.account_curve?.peak?.captured_at || "";
      const maxAbs = Math.max(0.01, ...points.map((point) => Math.abs(Number(point.day_change))));
      const sampled = samplePoints(points, 64);
      nodes.chart.style.setProperty("--bars", String(sampled.length));
      nodes.chart.innerHTML = sampled.map((point) => {
        const value = Number(point.day_change);
        const height = Math.max(2, Math.abs(value) / maxAbs * 100);
        const isPeak = point.captured_at === peakAt;
        const isAfterPeak = peakAt && point.captured_at > peakAt;
        const cls = isPeak ? "peak" : (isAfterPeak ? "after-peak" : "");
        return `<div class="bar ${cls}" title="${escapeHtml(fmtDate(point.captured_at))}: ${escapeHtml(fmtMoney(value))}" style="height:${height}%"></div>`;
      }).join("");
      nodes.curveNote.textContent = `Green is high-water. Gold is after high-water giveback. Peak ${fmtMoney(report.account_curve?.peak?.day_change)} ended at ${fmtMoney(report.account_curve?.final?.day_change)}.`;
    }

    function samplePoints(points, maxCount) {
      if (points.length <= maxCount) return points;
      const sampled = [];
      const step = (points.length - 1) / (maxCount - 1);
      for (let index = 0; index < maxCount; index += 1) {
        sampled.push(points[Math.round(index * step)]);
      }
      return sampled;
    }

    function renderPeakTrades() {
      const rows = report.trade_review?.open_at_peak?.rows || [];
      nodes.peakTradesBadge.textContent = `${rows.length} rows`;
      renderTradeTable(nodes.peakTrades, rows, true);
    }

    function renderCarryover() {
      const rows = report.trade_review?.carryover_rows || [];
      nodes.carryoverBadge.textContent = `${rows.length} rows`;
      renderTradeTable(nodes.carryover, rows, false);
    }

    function renderTradeTable(target, rows, includeAfterPeak) {
      if (!rows.length) {
        target.innerHTML = `<p class="empty">No rows in this category.</p>`;
        return;
      }
      target.innerHTML = `
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Strategy</th>
              <th>Entry</th>
              <th>Exit</th>
              <th>P/L</th>
              <th>Return</th>
              <th>Hold</th>
              ${includeAfterPeak ? "<th>After Peak</th>" : ""}
              <th>Outcome</th>
            </tr>
          </thead>
          <tbody>${rows.map((row) => `
            <tr>
              <td>${escapeHtml(row.symbol || "-")}</td>
              <td><code>${escapeHtml(row.strategy_id || "unassigned")}</code></td>
              <td>${escapeHtml(fmtDate(row.entry_at))}</td>
              <td>${escapeHtml(fmtDate(row.exit_at))}</td>
              <td class="${toneForMoney(row.pnl_usd)}">${escapeHtml(fmtMoney(row.pnl_usd))}</td>
              <td class="${toneForMoney(row.return_pct)}">${escapeHtml(fmtPct(row.return_pct))}</td>
              <td>${escapeHtml(fmtNumber(row.hold_minutes, 0))}m</td>
              ${includeAfterPeak ? `<td>${escapeHtml(fmtNumber(row.minutes_after_peak, 0))}m</td>` : ""}
              <td>${escapeHtml(String(row.outcome || "-").replaceAll("_", " "))}</td>
            </tr>
          `).join("")}</tbody>
        </table>
      `;
    }

    function renderLocks() {
      const floors = report.counterfactuals?.profit_floor_locks || [];
      const trails = report.counterfactuals?.trailing_giveback_locks || [];
      const items = [
        ...floors.map((row) => ({
          title: `Keep ${fmtMoney(row.floor_usd)} floor`,
          detail: row.would_trigger
            ? `Would trigger. Approx saved vs final: ${fmtMoney(row.saved_vs_final_usd)}.`
            : "Would not trigger in this window."
        })),
        ...trails.map((row) => ({
          title: `Trail after ${fmtMoney(row.giveback_usd)} giveback`,
          detail: row.would_trigger
            ? `Trigger ${fmtDate(row.trigger_at)} at ${fmtMoney(row.trigger_day_change_usd)}; saved ${fmtMoney(row.saved_vs_final_usd)}.`
            : "Would not trigger in this window."
        }))
      ];
      renderNotices(nodes.locks, items);
    }

    function renderLearning() {
      const advice = report.learning_advice || {};
      const evidence = advice.evidence || {};
      const candidate = advice.candidate_settings || {};
      const current = advice.current_settings || {};
      const items = [
        {
          title: `Action: ${advice.action || "hold"}`,
          detail: `${advice.reason || ""} Confidence: ${advice.confidence || "low"}. Authority: ${advice.execution_authority || "none"}.`
        },
        {
          title: "Candidate settings to test",
          detail: `Profit floor ${fmtMoney(candidate.account_profit_floor_usd)}, trailing giveback ${fmtMoney(candidate.account_trailing_giveback_usd)}, profit capture ${fmtPct(candidate.paper_profit_capture_pct)} vs current ${fmtPct(current.paper_profit_capture_pct)}.`
        },
        {
          title: "Evidence it used",
          detail: `Peak ${fmtMoney(evidence.peak_day_change_usd)}, final ${fmtMoney(evidence.final_day_change_usd)}, giveback ${fmtMoney(-Math.abs(Number(evidence.account_giveback_usd || 0)))}, same-window ${fmtMoney(evidence.same_window_pnl_usd)}, carryover ${fmtMoney(evidence.carryover_pnl_usd)}.`
        },
        {
          title: "Promotion gates",
          detail: (advice.promotion_gates || []).join(" ")
        }
      ];
      renderNotices(nodes.learning, items);
    }

    function renderNotices(target, rows) {
      if (!rows.length) {
        target.innerHTML = `<p class="empty">No rows available.</p>`;
        return;
      }
      target.innerHTML = rows.map((row) => {
        const title = row.title || row.action || row.name || "Review";
        const detail = row.detail || row.note || "";
        const status = row.status || row.level || "";
        return `
          <div class="notice">
            <strong>${escapeHtml(title.replaceAll("_", " "))}${status ? ` · ${escapeHtml(status.replaceAll("_", " "))}` : ""}</strong>
            <p class="subtle">${escapeHtml(detail)}</p>
          </div>
        `;
      }).join("");
    }

    async function loadReport() {
      nodes.refresh.disabled = true;
      nodes.status.textContent = "Loading profit-lock review...";
      try {
        const params = new URLSearchParams({
          hours: nodes.hours.value,
          broker_id: nodes.broker.value
        });
        const response = await fetch(`/api/profit_lock_review.php?${params.toString()}`, {
          cache: "no-store",
          headers: { "Accept": "application/json" }
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
          throw new Error(payload.detail || payload.reason || `HTTP ${response.status}`);
        }
        report = payload;
        render();
      } catch (error) {
        report = null;
        nodes.cards.innerHTML = "";
        nodes.chart.innerHTML = "";
        nodes.peakTrades.innerHTML = `<p class="empty">Could not load report.</p>`;
        nodes.carryover.innerHTML = "";
        nodes.locks.innerHTML = "";
        nodes.learning.innerHTML = "";
        nodes.recommendations.innerHTML = "";
        nodes.diagnostics.innerHTML = "";
        nodes.status.textContent = error instanceof Error ? error.message : "Could not load report.";
      } finally {
        nodes.refresh.disabled = false;
      }
    }

    nodes.refresh.addEventListener("click", loadReport);
    nodes.hours.addEventListener("change", loadReport);
    nodes.broker.addEventListener("change", loadReport);
    loadReport();
  </script>
</body>
</html>

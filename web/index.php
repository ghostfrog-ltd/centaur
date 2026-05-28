<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Project Centaur Dashboard</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-stone-100 text-stone-900">
  <main class="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
    <header class="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
      <div>
        <p class="text-sm font-medium uppercase tracking-wide text-amber-700">Project Centaur</p>
        <h1 class="text-3xl font-semibold tracking-tight">Operator Dashboard</h1>
        <p id="checked-at" class="mt-2 text-sm text-stone-500">Loading latest snapshot...</p>
      </div>
      <div class="flex flex-wrap gap-2">
        <button id="refresh-button" class="inline-flex items-center rounded-md border border-stone-300 bg-white px-4 py-2 text-sm font-medium text-stone-700 shadow-sm hover:bg-stone-50">Refresh</button>
        <a href="/api/snapshot.php" class="inline-flex items-center rounded-md border border-stone-300 bg-white px-4 py-2 text-sm font-medium text-stone-700 shadow-sm hover:bg-stone-50">Snapshot JSON</a>
      </div>
    </header>

    <section id="metric-cards" class="grid gap-4 sm:grid-cols-2 xl:grid-cols-6"></section>

    <section class="mt-6 grid gap-6 xl:grid-cols-[1.3fr_0.9fr]">
      <div class="space-y-6">
        <div class="rounded-lg border border-stone-200 bg-white shadow-sm">
          <div class="border-b border-stone-200 px-4 py-3">
            <h2 class="text-base font-semibold">Account</h2>
          </div>
          <div id="account-panel" class="grid gap-4 p-4 md:grid-cols-2"></div>
        </div>

        <div class="rounded-lg border border-stone-200 bg-white shadow-sm">
          <div class="border-b border-stone-200 px-4 py-3">
            <h2 class="text-base font-semibold">Open positions</h2>
          </div>
          <div id="positions-table" class="overflow-x-auto"></div>
        </div>

        <div class="rounded-lg border border-stone-200 bg-white shadow-sm">
          <div class="border-b border-stone-200 px-4 py-3">
            <h2 class="text-base font-semibold">Recent paper orders</h2>
          </div>
          <div id="orders-table" class="overflow-x-auto"></div>
        </div>

        <div class="rounded-lg border border-stone-200 bg-white shadow-sm">
          <div class="border-b border-stone-200 px-4 py-3">
            <h2 class="text-base font-semibold">Recent shadow proposals</h2>
          </div>
          <div id="proposals-table" class="overflow-x-auto"></div>
        </div>

        <div class="rounded-lg border border-stone-200 bg-white shadow-sm">
          <div class="border-b border-stone-200 px-4 py-3">
            <h2 class="text-base font-semibold">Signal pipeline</h2>
          </div>
          <div id="signal-panels" class="space-y-4 p-4"></div>
        </div>
      </div>

      <div class="space-y-6">
        <div class="rounded-lg border border-stone-200 bg-white shadow-sm">
          <div class="border-b border-stone-200 px-4 py-3">
            <h2 class="text-base font-semibold">Trade diagnostics</h2>
          </div>
          <div id="trade-diagnostics" class="space-y-2 p-4"></div>
        </div>

        <div class="rounded-lg border border-stone-200 bg-white shadow-sm">
          <div class="border-b border-stone-200 px-4 py-3">
            <h2 class="text-base font-semibold">Centaur activity</h2>
          </div>
          <div id="activity-panel" class="space-y-2 p-4"></div>
        </div>

        <div class="rounded-lg border border-stone-200 bg-white shadow-sm">
          <div class="border-b border-stone-200 px-4 py-3">
            <h2 class="text-base font-semibold">GA threshold advice</h2>
          </div>
          <div id="threshold-panel" class="space-y-2 p-4"></div>
        </div>

        <div class="rounded-lg border border-stone-200 bg-white shadow-sm">
          <div class="border-b border-stone-200 px-4 py-3">
            <h2 class="text-base font-semibold">Holding-window fitness</h2>
          </div>
          <div id="holding-window-panel" class="space-y-2 p-4"></div>
        </div>

        <div class="rounded-lg border border-stone-200 bg-white shadow-sm">
          <div class="border-b border-stone-200 px-4 py-3">
            <h2 class="text-base font-semibold">Broker accounts</h2>
          </div>
          <div id="broker-panel" class="space-y-2 p-4"></div>
        </div>

        <div class="rounded-lg border border-stone-200 bg-white shadow-sm">
          <div class="border-b border-stone-200 px-4 py-3">
            <h2 class="text-base font-semibold">Live readiness</h2>
          </div>
          <div id="live-panel" class="space-y-2 p-4"></div>
        </div>

        <div class="rounded-lg border border-stone-200 bg-white shadow-sm">
          <div class="border-b border-stone-200 px-4 py-3">
            <h2 class="text-base font-semibold">API cost</h2>
          </div>
          <div id="cost-panel" class="space-y-2 p-4"></div>
        </div>

        <div class="rounded-lg border border-stone-200 bg-white shadow-sm">
          <div class="border-b border-stone-200 px-4 py-3">
            <h2 class="text-base font-semibold">Alerts</h2>
          </div>
          <div id="alerts-panel" class="space-y-3 p-4"></div>
        </div>
      </div>
    </section>
  </main>

  <script>
    const snapshotUrl = "/api/snapshot.php";
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
        target.innerHTML = `<p class="text-sm text-stone-500">${escapeHtml(emptyLabel)}</p>`;
        return;
      }
      target.innerHTML = rows.map((item) => `
        <div class="rounded-md border border-stone-200 bg-stone-50 px-3 py-2 text-sm text-stone-700">
          <span class="font-mono text-[12px]">${escapeHtml(item)}</span>
        </div>
      `).join("");
    }

    function renderTable(target, columns, rows, emptyLabel) {
      if (!Array.isArray(rows) || !rows.length) {
        target.innerHTML = `<p class="p-4 text-sm text-stone-500">${escapeHtml(emptyLabel)}</p>`;
        return;
      }
      const head = columns.map((column) => `<th class="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-stone-500">${escapeHtml(column.label)}</th>`).join("");
      const body = rows.map((row) => `
        <tr class="border-t border-stone-200">
          ${columns.map((column) => `<td class="px-4 py-3 text-sm text-stone-700 ${column.mono ? "font-mono text-[12px]" : ""}">${column.render(row)}</td>`).join("")}
        </tr>
      `).join("");
      target.innerHTML = `<table class="min-w-full">${`<thead class="bg-stone-50"><tr>${head}</tr></thead><tbody>${body}</tbody>`}</table>`;
    }

    function buildMetricCards(snapshot) {
      const latestTick = snapshot.latest_tick || {};
      const tickState = latestTick.state_snapshot_json || {};
      const marketGate = tickState.market_gate || {};
      const riskCfo = tickState.risk_cfo || {};
      const blockers = (snapshot.centaur_activity || {}).blockers || {};
      const account = snapshot.account_overview || {};

      const cards = [
        { label: "Latest tick", value: String(latestTick.status || "none").toUpperCase(), detail: latestTick.started_at || "-" },
        { label: "Market", value: marketGate.market_open ? "OPEN" : "CLOSED", detail: marketGate.reason || "-" },
        { label: "CFO", value: riskCfo.decision || "-", detail: riskCfo.reason || "-" },
        { label: "Day P/L", value: fmtSignedCurrency(account.day_change_usd), detail: fmtSignedPct(account.day_change_pct), tone: Number(account.day_change_usd) > 0 ? "text-emerald-600" : Number(account.day_change_usd) < 0 ? "text-rose-600" : "" },
        { label: "Open positions", value: String(account.open_positions_count || 0), detail: `slots ${account.open_positions_count || 0}/10` },
        { label: "Primary blocker", value: blockers.primary_stage || "-", detail: blockers.cfo_reason || "-" }
      ];

      cardContainer.innerHTML = cards.map((card) => `
        <article class="rounded-lg border border-stone-200 bg-white p-4 shadow-sm">
          <div class="text-sm text-stone-500">${escapeHtml(card.label)}</div>
          <div class="mt-3 text-2xl font-semibold ${card.tone || ""}">${escapeHtml(card.value)}</div>
          <div class="mt-2 text-sm text-stone-500">${escapeHtml(card.detail || "-")}</div>
        </article>
      `).join("");
    }

    function buildAccountPanel(account) {
      const blocks = [
        {
          title: "Balances",
          rows: [
            `Equity ${fmtCurrency(account.equity)}`,
            `Cash ${fmtCurrency(account.cash)}`,
            `Buying power ${fmtCurrency(account.buying_power)}`,
            `Position value ${fmtCurrency(account.position_market_value_usd)}`
          ]
        },
        {
          title: "Capital and P/L",
          rows: [
            `Day change ${fmtSignedCurrency(account.day_change_usd)} (${fmtSignedPct(account.day_change_pct)})`,
            `Open unrealized ${fmtSignedCurrency(account.open_position_unrealized_pl_usd)}`,
            `Committed ${fmtCurrency(account.capital_committed_usd)}`,
            `Free ${fmtCurrency(account.capital_free_usd)}`
          ]
        }
      ];

      accountPanel.innerHTML = blocks.map((block) => `
        <div class="rounded-md border border-stone-200 bg-stone-50 p-4">
          <h3 class="text-sm font-semibold text-stone-800">${escapeHtml(block.title)}</h3>
          <ul class="mt-3 space-y-2 text-sm text-stone-600">
            ${block.rows.map((row) => `<li>${escapeHtml(row)}</li>`).join("")}
          </ul>
        </div>
      `).join("");
    }

    function buildSignalPanels(activity) {
      const sections = [
        { title: "Raw signals", rows: activity.raw_signal_preview || [], empty: "No raw signals captured on this tick." },
        { title: "Suppressed signals", rows: activity.suppressed_signal_preview || [], empty: "No suppressed signals captured on this tick." },
        { title: "Surviving signals", rows: activity.surviving_signal_preview || [], empty: "No surviving signals on this tick." }
      ];

      signalPanels.innerHTML = sections.map((section) => {
        if (!section.rows.length) {
          return `<section class="rounded-md border border-stone-200 bg-stone-50 p-4"><h3 class="text-sm font-semibold">${escapeHtml(section.title)}</h3><p class="mt-3 text-sm text-stone-500">${escapeHtml(section.empty)}</p></section>`;
        }
        return `
          <section class="rounded-md border border-stone-200 bg-stone-50 p-4">
            <h3 class="text-sm font-semibold">${escapeHtml(section.title)}</h3>
            <div class="mt-3 overflow-x-auto">
              <table class="min-w-full">
                <thead>
                  <tr>
                    <th class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-stone-500">Strategy</th>
                    <th class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-stone-500">Symbol</th>
                    <th class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-stone-500">Status</th>
                    <th class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-stone-500">Score</th>
                    <th class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-stone-500">Fitness</th>
                    <th class="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-stone-500">Target</th>
                  </tr>
                </thead>
                <tbody>
                  ${section.rows.slice(0, 8).map((row) => `
                    <tr class="border-t border-stone-200">
                      <td class="px-3 py-2 text-sm text-stone-700">${escapeHtml(row.strategy_id || "-")}</td>
                      <td class="px-3 py-2 font-mono text-[12px] text-stone-700">${escapeHtml((row.symbol || "-").toUpperCase())}</td>
                      <td class="px-3 py-2 text-sm text-stone-700">${escapeHtml(row.allocation_status || "-")}</td>
                      <td class="px-3 py-2 text-sm text-stone-700">${fmtNumber(row.signal_score, 2)}</td>
                      <td class="px-3 py-2 text-sm text-stone-700">${fmtNumber(row.fitness_composite_score, 2)}</td>
                      <td class="px-3 py-2 text-sm text-stone-700">${fmtNumber(row.target_return_pct, 2)}%</td>
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
      buildAccountPanel(snapshot.account_overview || {});

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

      renderList(brokerPanel, snapshot.broker_accounts || [], "No broker snapshots recorded yet.");
      renderList(livePanel, snapshot.live_execution_overview || [], "No live-readiness state available.");

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
        alertsPanel.innerHTML = `<p class="text-sm text-stone-500">No current alerts.</p>`;
      } else {
        alertsPanel.innerHTML = alerts.slice(0, 8).map((alert) => `
          <article class="rounded-md border border-stone-200 bg-stone-50 p-4">
            <div class="text-xs font-semibold uppercase tracking-wide text-stone-500">${escapeHtml(alert.level || "info")}</div>
            <div class="mt-2 text-sm font-medium text-stone-800">${escapeHtml(alert.summary || "-")}</div>
            <div class="mt-2 text-xs text-stone-500">${escapeHtml(alert.at || "-")}</div>
            <div class="mt-2 text-sm text-stone-600">${escapeHtml(alert.detail || "-")}</div>
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

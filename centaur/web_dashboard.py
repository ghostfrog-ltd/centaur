from __future__ import annotations

from datetime import datetime
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from typing import Any
from urllib.parse import urlparse

from .config import RuntimeConfig, load_runtime_config
from .status import StatusReporter

APP_BUILD = "2026-05-07-web-dashboard"


def run_web_dashboard(
    *,
    host: str = "127.0.0.1",
    port: int = 8788,
    config: RuntimeConfig | None = None,
) -> None:
    runtime_config = config or load_runtime_config()
    reporter = StatusReporter(config=runtime_config)

    class DashboardHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                snapshot = reporter.snapshot(include_visuals=False, include_logs=False)
                html = _render_dashboard_html(snapshot=snapshot, config=runtime_config)
                self._send_html(html)
                return

            if parsed.path == "/api/snapshot":
                snapshot = reporter.snapshot(include_visuals=False, include_logs=False)
                self._send_json(_json_safe(snapshot))
                return

            if parsed.path == "/healthz":
                self._send_json(
                    {
                        "ok": True,
                        "service": "centaur-web-dashboard",
                        "build": APP_BUILD,
                        "checked_at": datetime.now().astimezone().isoformat(),
                    }
                )
                return

            self.send_error(HTTPStatus.NOT_FOUND, "Not found")

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send_html(self, body: str) -> None:
            payload = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(self, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, default=str, indent=2).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer((host, port), DashboardHandler)
    print(
        (
            "Centaur web dashboard running"
            f" | build={APP_BUILD}"
            f" | url=http://{host}:{port}"
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Centaur web dashboard stopped", flush=True)
    finally:
        server.server_close()


def _render_dashboard_html(*, snapshot: dict[str, Any], config: RuntimeConfig) -> str:
    now = snapshot.get("checked_at")
    latest_tick = _as_dict(snapshot.get("latest_tick"))
    account = _as_dict(snapshot.get("account_overview"))
    centaur_activity = _as_dict(snapshot.get("centaur_activity"))
    flow = _as_dict(centaur_activity.get("flow"))
    blockers = _as_dict(centaur_activity.get("blockers"))
    market_gate = _as_dict(_as_dict(latest_tick.get("state_snapshot_json")).get("market_gate"))
    risk_cfo = _as_dict(_as_dict(latest_tick.get("state_snapshot_json")).get("risk_cfo"))

    cards = [
        _metric_card(
            label="Latest tick",
            value=str(latest_tick.get("status", "none") or "none").upper(),
            detail=_fmt_dt(latest_tick.get("started_at")),
        ),
        _metric_card(
            label="Market",
            value="OPEN" if market_gate.get("market_open") else "CLOSED",
            detail=str(market_gate.get("reason", "-") or "-"),
        ),
        _metric_card(
            label="CFO",
            value=str(risk_cfo.get("decision", "-") or "-"),
            detail=str(risk_cfo.get("reason", "-") or "-"),
        ),
        _metric_card(
            label="Day P/L",
            value=_fmt_signed_currency(account.get("day_change_usd")),
            detail=_fmt_signed_pct(account.get("day_change_pct")),
            tone=_tone_from_number(account.get("day_change_usd")),
        ),
        _metric_card(
            label="Open positions",
            value=str(int(account.get("open_positions_count", 0) or 0)),
            detail=(
                f"slots {int(account.get('open_positions_count', 0) or 0)}"
                f"/{int(account.get('effective_max_open_positions', config.paper_execution_max_open_positions) or config.paper_execution_max_open_positions)}"
            ),
        ),
        _metric_card(
            label="Primary blocker",
            value=str(blockers.get("primary_stage", "-") or "-"),
            detail=str(blockers.get("cfo_reason", "-") or "-"),
        ),
    ]

    activity_tables = [
        _signal_preview_table(
            title="Raw signals",
            rows=_as_list(centaur_activity.get("raw_signal_preview")),
            empty_label="No raw signals captured on this tick.",
        ),
        _signal_preview_table(
            title="Suppressed signals",
            rows=_as_list(centaur_activity.get("suppressed_signal_preview")),
            empty_label="No suppressed signals captured on this tick.",
        ),
        _signal_preview_table(
            title="Surviving signals",
            rows=_as_list(centaur_activity.get("surviving_signal_preview")),
            empty_label="No surviving signals on this tick.",
        ),
    ]

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="15">
    <title>Project Centaur Dashboard</title>
    <style>
      :root {{
        color-scheme: light;
        --bg: #f6f3ee;
        --panel: #fffdf8;
        --ink: #1e2328;
        --muted: #6c6a66;
        --line: #e4ddd2;
        --accent: #c9961a;
        --good: #1f8f58;
        --bad: #c24f4f;
        --warn: #9a6700;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        background: var(--bg);
        color: var(--ink);
      }}
      a {{ color: inherit; }}
      .shell {{ max-width: 1500px; margin: 0 auto; padding: 24px; }}
      .header {{
        display: flex; flex-wrap: wrap; gap: 16px; align-items: flex-end; justify-content: space-between;
        margin-bottom: 18px;
      }}
      .title {{ margin: 0; font-size: 34px; line-height: 1.05; }}
      .subtle {{ color: var(--muted); font-size: 14px; }}
      .actions {{ display: flex; gap: 10px; align-items: center; }}
      .button {{
        display: inline-flex; align-items: center; justify-content: center;
        padding: 10px 14px; border-radius: 8px; border: 1px solid var(--line);
        background: var(--panel); text-decoration: none; font-size: 14px; font-weight: 600;
      }}
      .grid-cards {{
        display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; margin-bottom: 18px;
      }}
      .card, .panel {{
        background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
      }}
      .card {{ padding: 16px; min-height: 110px; }}
      .card-label {{ color: var(--muted); font-size: 13px; margin-bottom: 10px; }}
      .card-value {{ font-size: 26px; font-weight: 700; line-height: 1.1; }}
      .card-value.good {{ color: var(--good); }}
      .card-value.bad {{ color: var(--bad); }}
      .card-detail {{ color: var(--muted); font-size: 13px; margin-top: 8px; }}
      .layout {{
        display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(360px, 0.95fr); gap: 16px;
      }}
      .stack {{ display: grid; gap: 16px; }}
      .panel-header {{
        padding: 14px 16px; border-bottom: 1px solid var(--line);
        display: flex; align-items: center; justify-content: space-between; gap: 12px;
      }}
      .panel-title {{ font-size: 16px; font-weight: 700; }}
      .panel-body {{ padding: 16px; }}
      .list {{ display: grid; gap: 10px; }}
      .list-item {{
        padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: rgba(255,255,255,0.55);
      }}
      .diag {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12.5px; white-space: pre-wrap; }}
      .summary-grid {{
        display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px;
      }}
      .summary-block {{
        border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: rgba(255,255,255,0.55);
      }}
      .summary-block h3 {{ margin: 0 0 10px; font-size: 14px; }}
      .summary-block ul {{ margin: 0; padding-left: 18px; }}
      .summary-block li {{ margin: 0 0 6px; }}
      table {{ width: 100%; border-collapse: collapse; }}
      th, td {{
        padding: 10px 12px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top;
        font-size: 13px;
      }}
      th {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.04em; }}
      .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }}
      .pill {{
        display: inline-flex; align-items: center; border-radius: 999px; padding: 4px 9px;
        background: #f3ede2; color: #6d5d3e; font-size: 12px; font-weight: 700;
      }}
      .pill.good {{ background: #e7f6ee; color: #1f8f58; }}
      .pill.bad {{ background: #fbeaea; color: #c24f4f; }}
      .spark-wrap {{ margin-top: 10px; }}
      .footer {{
        margin-top: 18px; color: var(--muted); font-size: 12px; display: flex; flex-wrap: wrap; gap: 12px;
      }}
      @media (max-width: 1280px) {{
        .grid-cards {{ grid-template-columns: repeat(3, minmax(0, 1fr)); }}
        .layout {{ grid-template-columns: 1fr; }}
      }}
      @media (max-width: 760px) {{
        .shell {{ padding: 16px; }}
        .title {{ font-size: 28px; }}
        .grid-cards {{ grid-template-columns: 1fr; }}
        .summary-grid {{ grid-template-columns: 1fr; }}
      }}
    </style>
  </head>
  <body>
    <main class="shell">
      <section class="header">
        <div>
          <p class="subtle">Project Centaur live monitor</p>
          <h1 class="title">Web Dashboard</h1>
          <p class="subtle">Checked {_html(_fmt_dt(now))} | build={_html(APP_BUILD)} | auto refresh every 15s</p>
        </div>
        <div class="actions">
          <a class="button" href="/">Refresh</a>
          <a class="button" href="/api/snapshot">Snapshot JSON</a>
          <a class="button" href="/healthz">Health</a>
        </div>
      </section>

      <section class="grid-cards">
        {''.join(cards)}
      </section>

      <section class="layout">
        <div class="stack">
          {_panel(
              title="Account",
              body=_account_panel(account),
              eyebrow=_pill_from_number(account.get("day_change_usd"), label="day move")
          )}
          {_panel(
              title="Open positions",
              body=_positions_table(_as_list(snapshot.get("open_positions"))),
              eyebrow=_pill(str(int(account.get("open_positions_count", 0) or 0)) + " open")
          )}
          {_panel(
              title="Recent paper orders",
              body=_orders_table(_as_list(snapshot.get("recent_orders"))),
          )}
          {_panel(
              title="Recent shadow proposals",
              body=_proposals_table(_as_list(snapshot.get("recent_proposals"))),
          )}
          {_panel(
              title="Signal pipeline",
              body=''.join(activity_tables),
              eyebrow=_pill(
                  f"raw {int(flow.get('raw_signals', 0) or 0)} | survived {int(flow.get('surviving_signals', 0) or 0)} | proposals {int(flow.get('proposals_created', 0) or 0)}"
              )
          )}
        </div>

        <div class="stack">
          {_panel(
              title="Trade diagnostics",
              body=_bullet_list(_as_list(snapshot.get("trade_diagnostics")), mono=True),
          )}
          {_panel(
              title="Centaur activity",
              body=_bullet_list(_render_activity_summary(centaur_activity), mono=True),
          )}
          {_panel(
              title="Holding-window fitness",
              body=_bullet_list(_render_holding_window_summary(_as_dict(snapshot.get("holding_window_advice"))), mono=True),
          )}
          {_panel(
              title="Broker accounts",
              body=_bullet_list(_as_list(snapshot.get("broker_accounts"))),
          )}
          {_panel(
              title="Live readiness",
              body=_bullet_list(_as_list(snapshot.get("live_execution_overview"))),
          )}
          {_panel(
              title="API cost",
              body=_bullet_list(_render_cost_snapshot(_as_dict(snapshot.get("cost_overview")))),
          )}
          {_panel(
              title="Alerts",
              body=_alerts_panel(_as_list(snapshot.get("alerts"))),
          )}
        </div>
      </section>

      <footer class="footer">
        <span>Paper mode {'enabled' if config.paper_execution_enabled else 'disabled'}</span>
        <span>Kill switch {'on' if config.paper_execution_kill_switch else 'off'}</span>
        <span>Max open positions {int(account.get('effective_max_open_positions', config.paper_execution_max_open_positions) or config.paper_execution_max_open_positions)}</span>
        <span>Order cap per tick {config.paper_execution_max_orders_per_tick}</span>
        <span>Allowed strategies {_html(', '.join(config.paper_execution_allowed_strategies) or 'none')}</span>
      </footer>
    </main>
  </body>
</html>"""


def _account_panel(account: dict[str, Any]) -> str:
    if not account:
        return "<p class='subtle'>No account snapshot yet.</p>"

    blocks = [
        (
            "Balances",
            [
                f"Equity {_fmt_currency(account.get('equity'))}",
                f"Cash {_fmt_currency(account.get('cash'))}",
                f"Buying power {_fmt_currency(account.get('buying_power'))}",
                f"Position value {_fmt_currency(account.get('position_market_value_usd'))}",
            ],
        ),
        (
            "P/L and capital",
            [
                f"Day change {_fmt_signed_currency(account.get('day_change_usd'))} {_fmt_signed_pct(account.get('day_change_pct'))}",
                f"Open unrealized {_fmt_signed_currency(account.get('open_position_unrealized_pl_usd'))}",
                f"Committed {_fmt_currency(account.get('capital_committed_usd'))}",
                f"Free {_fmt_currency(account.get('capital_free_usd'))}",
            ],
        ),
    ]
    body = []
    for title, rows in blocks:
        body.append("<div class='summary-block'>")
        body.append(f"<h3>{_html(title)}</h3>")
        body.append("<ul>")
        for row in rows:
            body.append(f"<li>{_html(row)}</li>")
        body.append("</ul></div>")
    return f"<div class='summary-grid'>{''.join(body)}</div>"


def _positions_table(rows: list[Any]) -> str:
    typed_rows = [row for row in rows if isinstance(row, dict)]
    if not typed_rows:
        return "<p class='subtle'>No open positions.</p>"

    body = []
    for row in typed_rows:
        body.append(
            "<tr>"
            f"<td class='mono'>{_html(str(row.get('symbol', '-') or '-'))}</td>"
            f"<td>{_fmt_number(row.get('qty'), 4)}</td>"
            f"<td>{_fmt_currency(row.get('market_value_usd'))}</td>"
            f"<td>{_fmt_currency(row.get('avg_entry_price'), 4)}</td>"
            f"<td>{_fmt_currency(row.get('current_price'), 4)}</td>"
            f"<td>{_fmt_signed_currency(row.get('unrealized_pl_usd'))} {_fmt_signed_pct(row.get('unrealized_pl_pct'))}</td>"
            f"<td>{_fmt_currency(row.get('stop_loss_price'), 4)}</td>"
            f"<td>{_fmt_currency(row.get('target_price'), 4)}</td>"
            f"<td>{_html(str(row.get('managed_exit_policy', '-') or '-'))}</td>"
            f"<td>{_html(str(row.get('exit_state', '-') or '-'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>Symbol</th><th>Qty</th><th>Value</th><th>Entry</th><th>Current</th><th>Unrealized</th><th>Stop</th><th>Target</th><th>Policy</th><th>Exit</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _orders_table(rows: list[Any]) -> str:
    typed_rows = [row for row in rows if isinstance(row, dict)]
    if not typed_rows:
        return "<p class='subtle'>No recent paper orders.</p>"

    body = []
    for row in typed_rows:
        body.append(
            "<tr>"
            f"<td>{_html(_fmt_dt(row.get('submitted_at') or row.get('captured_at')))}</td>"
            f"<td class='mono'>{_html(str(row.get('symbol', '-') or '-'))}</td>"
            f"<td>{_html(str(row.get('status', '-') or '-'))}</td>"
            f"<td>{_html(str(row.get('side', '-') or '-'))}</td>"
            f"<td>{_fmt_currency(row.get('notional_usd'))}</td>"
            f"<td>{_html(str(row.get('strategy_id', '-') or '-'))}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>When</th><th>Symbol</th><th>Status</th><th>Side</th><th>Notional</th><th>Strategy</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _proposals_table(rows: list[Any]) -> str:
    typed_rows = [row for row in rows if isinstance(row, dict)]
    if not typed_rows:
        return "<p class='subtle'>No recent shadow proposals.</p>"

    body = []
    for row in typed_rows:
        score = row.get("signal_score")
        if score is None:
            score = row.get("opportunity_score")
        body.append(
            "<tr>"
            f"<td>{_html(_fmt_dt(row.get('proposed_at')))}</td>"
            f"<td class='mono'>{_html(str(row.get('symbol', '-') or '-'))}</td>"
            f"<td>{_html(str(row.get('status', '-') or '-'))}</td>"
            f"<td>{_html(str(row.get('strategy_id', '-') or '-'))}</td>"
            f"<td>{_fmt_number(score, 3)}</td>"
            "</tr>"
        )
    return (
        "<table><thead><tr>"
        "<th>When</th><th>Symbol</th><th>Status</th><th>Strategy</th><th>Score</th>"
        "</tr></thead><tbody>"
        + "".join(body)
        + "</tbody></table>"
    )


def _signal_preview_table(*, title: str, rows: list[Any], empty_label: str) -> str:
    typed_rows = [row for row in rows if isinstance(row, dict)]
    if not typed_rows:
        return _panel(title=title, body=f"<p class='subtle'>{_html(empty_label)}</p>", nested=True)

    body = []
    for row in typed_rows[:8]:
        body.append(
            "<tr>"
            f"<td>{_html(str(row.get('strategy_id', '-') or '-'))}</td>"
            f"<td class='mono'>{_html(str(row.get('symbol', '-') or '-').upper())}</td>"
            f"<td>{_html(str(row.get('allocation_status', '-') or '-'))}</td>"
            f"<td>{_fmt_number(row.get('signal_score'), 2)}</td>"
            f"<td>{_fmt_number(row.get('fitness_composite_score'), 2)}</td>"
            f"<td>{_fmt_number(row.get('target_return_pct'), 2)}%</td>"
            "</tr>"
        )
    return _panel(
        title=title,
        body=(
            "<table><thead><tr>"
            "<th>Strategy</th><th>Symbol</th><th>Status</th><th>Score</th><th>Fitness</th><th>Target</th>"
            "</tr></thead><tbody>"
            + "".join(body)
            + "</tbody></table>"
        ),
        nested=True,
    )


def _render_activity_summary(activity: dict[str, Any]) -> list[str]:
    if not activity:
        return ["No activity snapshot yet."]

    scan = _as_dict(activity.get("scan"))
    flow = _as_dict(activity.get("flow"))
    blockers = _as_dict(activity.get("blockers"))
    return [
        (
            "Scan"
            f" | mode={scan.get('mode', '-')}"
            f" | candidates={int(scan.get('candidates_found', 0) or 0)}"
            f" | selected={int(scan.get('selected_candidates', 0) or 0)}"
            f" | bars={int(scan.get('bars_available', 0) or 0)}"
            f" | top={scan.get('top_symbol', '-')}"
        ),
        (
            "Flow"
            f" | raw={int(flow.get('raw_signals', 0) or 0)}"
            f" | survived={int(flow.get('surviving_signals', 0) or 0)}"
            f" | suppressed={int(flow.get('suppressed_signals', 0) or 0)}"
            f" | proposals={int(flow.get('proposals_created', 0) or 0)}"
            f" | cfo={flow.get('cfo_reason', '-')}"
        ),
        (
            "Blockers"
            f" | stage={blockers.get('primary_stage', '-')}"
            f" | market={blockers.get('market_reason', '-')}"
            f" | cfo={blockers.get('cfo_reason', '-')}"
            f" | rejects={_reason_counts_text(blockers.get('rejection_reason_counts'))}"
            f" | exits={_reason_counts_text(blockers.get('exit_skip_reason_counts'))}"
        ),
    ]


def _render_holding_window_summary(advice: dict[str, Any]) -> list[str]:
    if not advice:
        return ["No holding-window fitness advice available."]
    if str(advice.get("status", "unknown")) != "ok":
        return [f"status={advice.get('status', 'unknown')} | reason={advice.get('reason', '-')}"]

    recommendation = _as_dict(advice.get("recommendation"))
    sample_counts = _as_dict(advice.get("sample_counts"))
    fixed_all = _as_dict(advice.get("fixed_windows_all"))
    fixed_long_all = _as_dict(advice.get("fixed_windows_long_all"))
    fixed_7d = _as_dict(advice.get("fixed_windows_7d"))
    policy_all = _as_dict(advice.get("policy_stats_all"))
    rows = [
        (
            f"strategy={advice.get('strategy_id', '-')}"
            f" | current={advice.get('current_window', '-')}"
            f" | action={recommendation.get('action', '-')}"
            f" | confidence={recommendation.get('confidence', '-')}"
        ),
        f"candidate={recommendation.get('candidate_policy', '-')}",
        (
            "samples"
            f" | all={sample_counts.get('complete_15m_1h_1d', 0)}"
            f" | 30d={sample_counts.get('complete_15m_1h_1d_30d', 0)}"
            f" | 1h/1d/7d={sample_counts.get('complete_1h_1d_7d', 0)}"
            f" | 7d={sample_counts.get('complete_15m_1h_7d', 0)}"
        ),
        (
            "all-time"
            f" | 15m {_holding_metric_text(_as_dict(fixed_all.get('15m')))}"
            f" | 1h {_holding_metric_text(_as_dict(fixed_all.get('1h')))}"
            f" | 1d {_holding_metric_text(_as_dict(fixed_all.get('1d')))}"
        ),
        (
            "recent 7d"
            f" | 15m {_holding_metric_text(_as_dict(fixed_7d.get('15m')))}"
            f" | 1h {_holding_metric_text(_as_dict(fixed_7d.get('1h')))}"
        ),
        f"dynamic | 1h_profit_else_1d {_holding_metric_text(_as_dict(policy_all.get('take_1h_profit_else_1d')))}",
        str(recommendation.get("reason", "-")),
    ]
    if int(sample_counts.get("complete_1h_1d_7d", 0) or 0) > 0:
        rows.insert(
            4,
            (
                "long hold"
                f" | 1h {_holding_metric_text(_as_dict(fixed_long_all.get('1h')))}"
                f" | 1d {_holding_metric_text(_as_dict(fixed_long_all.get('1d')))}"
                f" | 7d {_holding_metric_text(_as_dict(fixed_long_all.get('7d')))}"
            ),
        )
    return rows


def _holding_metric_text(metrics: dict[str, Any]) -> str:
    if not metrics or int(metrics.get("n", 0) or 0) <= 0:
        return "n=0"
    return (
        f"n={metrics.get('n', 0)}"
        f"/avg={_fmt_number(metrics.get('avg_return_pct'), 2)}%"
        f"/win={float(metrics.get('win_rate', 0) or 0) * 100:.1f}%"
        f"/score={_fmt_number(metrics.get('score'), 2)}"
    )


def _render_cost_snapshot(overview: dict[str, Any]) -> list[str]:
    if not overview:
        return ["No cost snapshot available."]

    today = _as_dict(overview.get("today"))
    yesterday = _as_dict(overview.get("yesterday"))
    lines = [
        (
            "Pricing"
            f" | configured={'yes' if overview.get('pricing_configured') else 'no'}"
            f" | gemini_pricing={'yes' if overview.get('gemini_pricing_configured') else 'no'}"
            f" | usd_to_gbp={_fmt_number(overview.get('usd_to_gbp'), 4)}"
        ),
        (
            "Today"
            f" | est={_fmt_currency(today.get('estimated_cost_usd'), 4)}"
            f" | requests={int(today.get('request_count', 0) or 0)}"
        ),
        (
            "Yesterday"
            f" | est={_fmt_currency(yesterday.get('estimated_cost_usd'), 4)}"
            f" | requests={int(yesterday.get('request_count', 0) or 0)}"
        ),
    ]
    notes = [str(note) for note in _as_list(overview.get("notes")) if note]
    return lines + notes[:3]


def _alerts_panel(rows: list[Any]) -> str:
    typed_rows = [row for row in rows if isinstance(row, dict)]
    if not typed_rows:
        return "<p class='subtle'>No current alerts.</p>"

    parts = ["<div class='list'>"]
    for row in typed_rows[:8]:
        level = str(row.get("level", "info") or "info").lower()
        pill = _pill(level.upper(), tone="bad" if level in {"error", "critical"} else "good" if level == "ok" else "neutral")
        parts.append(
            "<div class='list-item'>"
            f"{pill}"
            f"<div style='margin-top:10px;font-weight:600'>{_html(str(row.get('summary', '-') or '-'))}</div>"
            f"<div class='subtle' style='margin-top:6px'>{_html(_fmt_dt(row.get('at')))}</div>"
            f"<div class='subtle' style='margin-top:6px'>{_html(str(row.get('detail', '-') or '-'))}</div>"
            "</div>"
        )
    parts.append("</div>")
    return "".join(parts)


def _bullet_list(items: list[Any], *, mono: bool = False) -> str:
    values = [str(item) for item in items if item not in (None, "")]
    if not values:
        return "<p class='subtle'>Nothing recorded here yet.</p>"
    class_name = "list-item diag" if mono else "list-item"
    return "<div class='list'>" + "".join(
        f"<div class='{class_name}'>{_html(value)}</div>" for value in values
    ) + "</div>"


def _panel(*, title: str, body: str, eyebrow: str = "", nested: bool = False) -> str:
    panel_class = "panel" if not nested else "summary-block"
    header = (
        f"<div class='panel-header'><div class='panel-title'>{_html(title)}</div>{eyebrow}</div>"
        if not nested
        else f"<h3>{_html(title)}</h3>"
    )
    body_class = "panel-body" if not nested else ""
    return f"<section class='{panel_class}'>{header}<div class='{body_class}'>{body}</div></section>"


def _metric_card(*, label: str, value: str, detail: str = "", tone: str = "neutral") -> str:
    tone_class = " good" if tone == "good" else " bad" if tone == "bad" else ""
    detail_html = f"<div class='card-detail'>{_html(detail)}</div>" if detail else ""
    return (
        "<article class='card'>"
        f"<div class='card-label'>{_html(label)}</div>"
        f"<div class='card-value{tone_class}'>{_html(value or '-')}</div>"
        f"{detail_html}"
        "</article>"
    )


def _pill(label: str, *, tone: str = "neutral") -> str:
    class_name = "pill"
    if tone in {"good", "bad"}:
        class_name += f" {tone}"
    return f"<span class='{class_name}'>{_html(label)}</span>"


def _pill_from_number(value: Any, *, label: str) -> str:
    number = _to_float(value)
    tone = _tone_from_number(number)
    suffix = _fmt_signed_currency(number)
    return _pill(f"{label} {suffix}", tone=tone)


def _tone_from_number(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "neutral"
    if number > 0:
        return "good"
    if number < 0:
        return "bad"
    return "neutral"


def _fmt_dt(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    if isinstance(value, str) and value.strip():
        return value
    return "-"


def _fmt_number(value: Any, decimals: int = 2) -> str:
    number = _to_float(value)
    if number is None:
        return "-"
    return f"{number:.{decimals}f}"


def _fmt_currency(value: Any, decimals: int = 2) -> str:
    number = _to_float(value)
    if number is None:
        return "-"
    return f"${number:.{decimals}f}"


def _fmt_signed_currency(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "-"
    return f"${number:+.2f}"


def _fmt_signed_pct(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "-"
    return f"({number:+.2f}%)"


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _reason_counts_text(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return "-"
    parts = []
    for reason, count in sorted(value.items(), key=lambda item: (-int(item[1]), str(item[0]))):
        parts.append(f"{reason}:{int(count)}")
        if len(parts) >= 3:
            break
    return ", ".join(parts) or "-"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _html(value: Any) -> str:
    return escape(str(value), quote=True)


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value

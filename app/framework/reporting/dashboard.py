from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import scrolledtext, ttk

from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from .status import StatusReporter

APP_BUILD = "2026-04-22-live-readiness"
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
RELIABILITY_STACK_FILES = [
    ("AGENTS", REPO_ROOT / "AGENTS.md"),
    ("CONSTRAINTS", REPO_ROOT / "CONSTRAINTS.md"),
    ("DECISION_LOG", REPO_ROOT / "DECISION_LOG.md"),
    ("SKILL", REPO_ROOT / "SKILL.md"),
    ("PROGRESS", REPO_ROOT / "PROGRESS.txt"),
]
CHECKLIST_FILES = [
    ("STRATEGY_CHECK", REPO_ROOT / "docs" / "STRATEGY_SELECTION_CHECKLIST.md"),
    ("GO_LIVE", REPO_ROOT / "docs" / "GO_LIVE_CHECKLIST.md"),
]


class CentaurDashboardApp:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        refresh_seconds: int = 10,
    ) -> None:
        self.config = config or load_runtime_config()
        self.reporter = StatusReporter(config=self.config)
        self.refresh_ms = max(2, refresh_seconds) * 1000
        self.auto_refresh = True
        self.root = tk.Tk()
        self.root.title(f"Project Centaur Monitor [{APP_BUILD}]")
        self.root.geometry("1420x1040")
        self.root.minsize(1160, 840)
        self.document_views: dict[Path, scrolledtext.ScrolledText] = {}
        self.document_cache: dict[Path, str] = {}

        self._build_ui()
        self.refresh()

    def run(self) -> None:
        self.root.mainloop()

    def _build_ui(self) -> None:
        self._configure_styles()

        container = ttk.Frame(self.root, padding=14)
        container.pack(fill="both", expand=True)

        header = ttk.Frame(container)
        header.pack(fill="x")

        title = ttk.Label(header, text="Project Centaur", style="Title.TLabel")
        title.grid(row=0, column=0, sticky="w")

        self.status_var = tk.StringVar(value="Loading...")
        self.status_label = ttk.Label(
            header,
            textvariable=self.status_var,
            style="Badge.TLabel",
        )
        self.status_label.grid(row=0, column=1, sticky="e", padx=(12, 0))

        self.pnl_var = tk.StringVar(value="Day P/L: -")
        self.pnl_label = ttk.Label(
            header,
            textvariable=self.pnl_var,
            style="PnlFlat.TLabel",
        )
        self.pnl_label.grid(row=0, column=2, sticky="e", padx=(12, 0))

        self.pnl_gbp_var = tk.StringVar(value="Day P/L GBP: -")
        self.pnl_gbp_label = ttk.Label(
            header,
            textvariable=self.pnl_gbp_var,
            style="PnlFlat.TLabel",
        )
        self.pnl_gbp_label.grid(row=0, column=3, sticky="e", padx=(12, 0))

        subtitle = ttk.Label(
            header,
            text=(
                "Live monitor for scheduler health, shadow learning, paper execution, and live readiness"
                f" | build={APP_BUILD}"
            ),
            style="Subtitle.TLabel",
        )
        subtitle.grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))
        header.columnconfigure(0, weight=1)

        controls = ttk.Frame(container)
        controls.pack(fill="x", pady=(12, 10))

        self.checked_var = tk.StringVar(value="Checked: -")
        ttk.Label(controls, textvariable=self.checked_var, style="Small.TLabel").pack(
            side="left"
        )

        self.refresh_button = ttk.Button(
            controls,
            text="Refresh Now",
            command=self.refresh,
        )
        self.refresh_button.pack(side="right")

        self.toggle_button = ttk.Button(
            controls,
            text="Pause Auto Refresh",
            command=self.toggle_auto_refresh,
        )
        self.toggle_button.pack(side="right", padx=(0, 8))

        self.alert_var = tk.StringVar(value="Alerts: loading")
        self.alert_banner = tk.Label(
            container,
            textvariable=self.alert_var,
            anchor="w",
            padx=12,
            pady=8,
            font=("Avenir Next", 11, "bold"),
            bg="#e6efe2",
            fg="#215f52",
        )
        self.alert_banner.pack(fill="x", pady=(0, 10))

        metrics = ttk.Frame(container)
        metrics.pack(fill="x")
        for index in range(7):
            metrics.columnconfigure(index, weight=1)

        self.metric_vars: dict[str, tk.StringVar] = {}
        metric_specs = [
            ("backend", "Backend"),
            ("tick", "Latest Tick"),
            ("market", "Market"),
            ("cfo", "CFO"),
            ("paper", "Paper Mode"),
            ("live", "Live Mode"),
            ("orders", "Paper Orders"),
        ]
        for index, (key, label) in enumerate(metric_specs):
            card = ttk.Frame(metrics, style="Card.TFrame", padding=10)
            card.grid(row=0, column=index, sticky="nsew", padx=(0 if index == 0 else 6, 0))
            ttk.Label(card, text=label, style="CardLabel.TLabel").pack(anchor="w")
            value_var = tk.StringVar(value="-")
            ttk.Label(card, textvariable=value_var, style="CardValue.TLabel").pack(
                anchor="w",
                pady=(6, 0),
            )
            self.metric_vars[key] = value_var

        single_view = ttk.Frame(container)
        single_view.pack(fill="both", expand=True, pady=(12, 0))
        self._build_status_tab(single_view)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        bg = "#f4f0e8"
        panel = "#fffaf0"
        ink = "#1d2a2e"
        accent = "#215f52"
        warm = "#9f5d26"

        self.root.configure(background=bg)
        style.configure(".", background=bg, foreground=ink)
        style.configure("Title.TLabel", font=("Avenir Next", 22, "bold"), foreground=ink)
        style.configure("Subtitle.TLabel", font=("Avenir Next", 11), foreground=warm)
        style.configure("Badge.TLabel", font=("Menlo", 10, "bold"), foreground=panel, background=accent, padding=(10, 4))
        style.configure("PnlFlat.TLabel", font=("Menlo", 10, "bold"), foreground=panel, background="#6d655d", padding=(10, 4))
        style.configure("PnlGain.TLabel", font=("Menlo", 10, "bold"), foreground=panel, background="#2b8a57", padding=(10, 4))
        style.configure("PnlLoss.TLabel", font=("Menlo", 10, "bold"), foreground=panel, background="#b85f5f", padding=(10, 4))
        style.configure("Small.TLabel", font=("Avenir Next", 10), foreground=ink)
        style.configure("Card.TFrame", background=panel, relief="solid", borderwidth=1)
        style.configure("CardLabel.TLabel", background=panel, foreground=warm, font=("Avenir Next", 10, "bold"))
        style.configure("CardValue.TLabel", background=panel, foreground=ink, font=("Menlo", 10))
        style.configure("Panel.TFrame", background=panel, relief="solid", borderwidth=1)
        style.configure("PanelTitle.TLabel", background=panel, foreground=ink, font=("Avenir Next", 12, "bold"))
        style.configure("TButton", font=("Avenir Next", 10))
        style.configure("TNotebook", background=bg, borderwidth=0)
        style.configure("TNotebook.Tab", font=("Avenir Next", 10, "bold"), padding=(12, 8))

    def _build_status_tab(self, parent: ttk.Frame) -> None:
        left = ttk.Frame(parent)
        left.pack(fill="both", expand=True)

        self.summary_text = self._build_text_panel(
            parent=left,
            title="Alerts",
            height=7,
        )
        self.alert_text = self.summary_text
        self.summary_text = self._build_text_panel(
            parent=left,
            title="Overview",
            height=14,
        )
        self.diagnostics_text = self._build_text_panel(
            parent=left,
            title="Trade Diagnostics",
            height=10,
        )

    def _build_account_tab(self, parent: ttk.Frame) -> None:
        grid = ttk.Frame(parent)
        grid.pack(fill="both", expand=True)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        grid.rowconfigure(0, weight=1)
        grid.rowconfigure(1, weight=1)
        grid.rowconfigure(2, weight=0)
        grid.rowconfigure(3, weight=0)

        self.account_text = self._build_grid_text_panel(
            parent=grid,
            title="Account Summary",
            row=0,
            column=0,
            height=12,
        )
        self.account_pl_chart = self._build_chart_panel(
            parent=grid,
            title="Open Position P/L",
            row=0,
            column=1,
        )
        self.positions_text = self._build_grid_text_panel(
            parent=grid,
            title="Positions",
            row=1,
            column=0,
            height=14,
        )
        self.account_value_chart = self._build_chart_panel(
            parent=grid,
            title="Position Market Value",
            row=1,
            column=1,
        )
        self.capital_text = self._build_grid_text_panel(
            parent=grid,
            title="Capital Envelope",
            row=2,
            column=0,
            height=6,
            columnspan=2,
        )
        self.comparison_text = self._build_grid_text_panel(
            parent=grid,
            title="Return Pace vs Long-Term Investing",
            row=3,
            column=0,
            height=8,
            columnspan=2,
        )

    def _build_fitness_tab(self, parent: ttk.Frame) -> None:
        grid = ttk.Frame(parent)
        grid.pack(fill="both", expand=True)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        grid.rowconfigure(0, weight=1)
        grid.rowconfigure(1, weight=1)

        self.strategy_leaderboard_chart = self._build_chart_panel(
            parent=grid,
            title="Strategy Leaderboard",
            row=0,
            column=0,
        )
        self.strategy_ranking_text = self._build_grid_text_panel(
            parent=grid,
            title="Why It's Ranked This Way",
            row=0,
            column=1,
            height=14,
        )
        self.strategy_proposals_chart = self._build_chart_panel(
            parent=grid,
            title="Recent Proposals By Strategy (7d)",
            row=1,
            column=0,
        )
        self.strategy_training_chart = self._build_chart_panel(
            parent=grid,
            title="All-Time Outcomes By Strategy",
            row=1,
            column=1,
        )

    def _build_costs_tab(self, parent: ttk.Frame) -> None:
        grid = ttk.Frame(parent)
        grid.pack(fill="both", expand=True)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        grid.rowconfigure(0, weight=1)
        grid.rowconfigure(1, weight=1)

        self.cost_summary_text = self._build_grid_text_panel(
            parent=grid,
            title="Cost Summary",
            row=0,
            column=0,
            height=14,
        )
        self.cost_daily_chart = self._build_chart_panel(
            parent=grid,
            title="Estimated API Cost (7d)",
            row=0,
            column=1,
        )
        self.cost_today_chart = self._build_chart_panel(
            parent=grid,
            title="Today By Source",
            row=1,
            column=0,
        )
        self.cost_yesterday_chart = self._build_chart_panel(
            parent=grid,
            title="Yesterday By Source",
            row=1,
            column=1,
        )

    def _build_chart_panel(
        self,
        *,
        parent: ttk.Frame,
        title: str,
        row: int,
        column: int,
    ) -> tk.Canvas:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        frame.grid(row=row, column=column, sticky="nsew", padx=6, pady=6)
        ttk.Label(frame, text=title, style="PanelTitle.TLabel").pack(anchor="w")
        canvas = tk.Canvas(
            frame,
            height=240,
            bg="#fffdf8",
            highlightthickness=0,
            relief="flat",
        )
        canvas.pack(fill="both", expand=True, pady=(8, 0))
        return canvas

    def _build_text_panel(
        self,
        *,
        parent: ttk.Frame,
        title: str,
        height: int,
    ) -> scrolledtext.ScrolledText:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        frame.pack(fill="both", expand=True, pady=(0, 10))
        ttk.Label(frame, text=title, style="PanelTitle.TLabel").pack(anchor="w")
        text = scrolledtext.ScrolledText(
            frame,
            height=height,
            wrap="word",
            font=("Menlo", 10),
            bg="#fffdf8",
            fg="#1d2a2e",
            insertbackground="#1d2a2e",
            relief="flat",
            borderwidth=0,
        )
        text.pack(fill="both", expand=True, pady=(8, 0))
        text.configure(state="disabled")
        return text

    def _build_grid_text_panel(
        self,
        *,
        parent: ttk.Frame,
        title: str,
        row: int,
        column: int,
        height: int,
        columnspan: int = 1,
    ) -> scrolledtext.ScrolledText:
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=10)
        frame.grid(
            row=row,
            column=column,
            columnspan=columnspan,
            sticky="nsew",
            padx=6,
            pady=6,
        )
        ttk.Label(frame, text=title, style="PanelTitle.TLabel").pack(anchor="w")
        text = scrolledtext.ScrolledText(
            frame,
            height=height,
            wrap="word",
            font=("Menlo", 10),
            bg="#fffdf8",
            fg="#1d2a2e",
            insertbackground="#1d2a2e",
            relief="flat",
            borderwidth=0,
        )
        text.pack(fill="both", expand=True, pady=(8, 0))
        text.configure(state="disabled")
        return text

    def _build_document_tab(
        self,
        parent: ttk.Frame,
        *,
        path: Path,
    ) -> None:
        frame = ttk.Frame(parent, padding=10)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text=str(path), style="Small.TLabel").pack(anchor="w")
        text = scrolledtext.ScrolledText(
            frame,
            wrap="word",
            font=("Menlo", 10),
            bg="#fffdf8",
            fg="#1d2a2e",
            insertbackground="#1d2a2e",
            relief="flat",
            borderwidth=0,
        )
        text.pack(fill="both", expand=True, pady=(8, 0))
        text.configure(state="disabled")
        self.document_views[path] = text

    def toggle_auto_refresh(self) -> None:
        self.auto_refresh = not self.auto_refresh
        self.toggle_button.configure(
            text="Resume Auto Refresh" if not self.auto_refresh else "Pause Auto Refresh"
        )
        if self.auto_refresh:
            self.refresh()

    def refresh(self) -> None:
        try:
            self.reporter = StatusReporter(config=self.config)
            snapshot = self.reporter.snapshot(include_visuals=False, include_logs=False)
            summary_text = self.reporter.render(snapshot=snapshot)
            self._apply_snapshot(snapshot=snapshot, summary_text=summary_text)
        except Exception as exc:  # pragma: no cover
            self.status_var.set(f"Refresh error: {type(exc).__name__}")
            self._set_text(self.summary_text, f"Dashboard refresh failed:\n\n{exc}")

        if self.auto_refresh:
            self.root.after(self.refresh_ms, self.refresh)

    def _apply_snapshot(self, *, snapshot: dict[str, object], summary_text: str) -> None:
        checked_at = snapshot["checked_at"]
        latest_tick = snapshot["latest_tick"]
        alerts = snapshot["alerts"]
        recent_orders = snapshot["recent_orders"]
        trade_diagnostics = snapshot["trade_diagnostics"]
        centaur_activity = snapshot["centaur_activity"]
        account_overview = snapshot["account_overview"]
        live_execution_overview = snapshot.get("live_execution_overview", {})
        self.checked_var.set(
            f"Checked: {self.reporter._fmt_dt(checked_at)} | refresh every {self.refresh_ms // 1000}s"
        )
        self._apply_alert_banner(alerts)
        self._apply_pnl_badge(account_overview)

        if latest_tick is None:
            self.status_var.set("Heartbeat: unknown (-)")
            self.metric_vars["backend"].set(self.reporter.usage_ledger.backend)
            self.metric_vars["tick"].set("-")
            self.metric_vars["market"].set("-")
            self.metric_vars["cfo"].set("-")
            self.metric_vars["paper"].set(
                (
                    f"{'armed' if self.config.paper_execution_enabled and not self.config.paper_execution_kill_switch else 'safe-off'}"
                    f" | $0/${self.config.paper_execution_default_notional_usd * self.config.paper_execution_max_open_positions:.0f}"
                )
            )
            self.metric_vars["live"].set(self._live_metric_text(live_execution_overview))
            self.metric_vars["orders"].set(str(len(recent_orders)))
        else:
            snapshot_state = latest_tick.get("state_snapshot_json", {})
            market_gate = snapshot_state.get("market_gate", {}) if isinstance(snapshot_state, dict) else {}
            risk_cfo = snapshot_state.get("risk_cfo", {}) if isinstance(snapshot_state, dict) else {}
            execution = snapshot_state.get("execution", {}) if isinstance(snapshot_state, dict) else {}
            heartbeat = self.reporter._heartbeat_status(
                now=checked_at,
                started_at=latest_tick.get("started_at"),
            )
            heartbeat_age = self.reporter._age_text(
                checked_at,
                latest_tick.get("started_at"),
            )
            self.status_var.set(f"Heartbeat: {heartbeat} ({heartbeat_age})")
            self.metric_vars["backend"].set(self.reporter.usage_ledger.backend)
            self.metric_vars["tick"].set(str(latest_tick.get("tick_id", "-")))
            self.metric_vars["market"].set(
                f"{market_gate.get('reason', '-')}"
            )
            self.metric_vars["cfo"].set(
                f"{risk_cfo.get('decision', '-')} / {risk_cfo.get('reason', '-')}"
            )
            self.metric_vars["paper"].set(
                (
                    f"{execution.get('execution_status', '-')} | "
                    f"${self.reporter._fmt_number(account_overview.get('capital_committed_usd'), decimals=0)}/"
                    f"${self.reporter._fmt_number(account_overview.get('capital_envelope_max_usd'), decimals=0)}"
                )
            )
            self.metric_vars["live"].set(self._live_metric_text(live_execution_overview))
            self.metric_vars["orders"].set(str(len(recent_orders)))

        alert_lines = [self.reporter._render_alert_line(alert) for alert in alerts]
        diagnostic_lines = [f"- {line}" for line in trade_diagnostics] if trade_diagnostics else ["- none"]
        activity_lines = self.reporter._render_centaur_activity(
            centaur_activity if isinstance(centaur_activity, dict) else {}
        )
        diagnostic_lines.extend(["", "Centaur activity:"])
        diagnostic_lines.extend(f"- {line}" for line in activity_lines)

        self._set_text(self.alert_text, "\n".join(alert_lines))
        self._set_text(self.summary_text, summary_text)
        self._set_text(self.diagnostics_text, "\n".join(diagnostic_lines))

    def _live_metric_text(self, overview: object) -> str:
        if not isinstance(overview, dict):
            return "safe-off | -"
        status = str(overview.get("status", "safe_off") or "safe_off").replace("_", "-")
        envelope = self.reporter._fmt_number(overview.get("envelope_max_usd"), decimals=0)
        return f"{status} | $0/${envelope}"

    def _apply_pnl_badge(self, account_overview: dict[str, object]) -> None:
        day_change = self.reporter._to_float(account_overview.get("day_change_usd"))
        day_change_gbp = self.reporter._to_float(account_overview.get("day_change_gbp"))
        if day_change is None:
            self.pnl_var.set("Day P/L: -")
            self.pnl_label.configure(style="PnlFlat.TLabel")
        else:
            self.pnl_var.set(f"Day P/L: ${day_change:+.2f}")

        if day_change_gbp is None:
            self.pnl_gbp_var.set("Day P/L GBP: -")
            self.pnl_gbp_label.configure(style="PnlFlat.TLabel")
        else:
            self.pnl_gbp_var.set(f"Day P/L GBP: £{day_change_gbp:+.2f}")

        if day_change is None and day_change_gbp is None:
            self.pnl_label.configure(style="PnlFlat.TLabel")
            self.pnl_gbp_label.configure(style="PnlFlat.TLabel")
            return

        reference_value = day_change if day_change is not None else day_change_gbp
        if reference_value is not None and reference_value > 0:
            self.pnl_label.configure(style="PnlGain.TLabel")
            self.pnl_gbp_label.configure(style="PnlGain.TLabel")
        elif reference_value is not None and reference_value < 0:
            self.pnl_label.configure(style="PnlLoss.TLabel")
            self.pnl_gbp_label.configure(style="PnlLoss.TLabel")
        else:
            self.pnl_label.configure(style="PnlFlat.TLabel")
            self.pnl_gbp_label.configure(style="PnlFlat.TLabel")

    def _apply_alert_banner(self, alerts: list[dict[str, object]]) -> None:
        top_alert = alerts[0] if alerts else {"level": "ok", "summary": "No recent alerts"}
        level = str(top_alert.get("level", "ok")).lower()
        summary = str(top_alert.get("summary", "No recent alerts"))
        detail = str(top_alert.get("detail", "")).strip()
        text = f"Alerts: {summary}"
        if detail:
            text = f"{text} | {detail}"
        if level == "error":
            bg = "#f7d7d7"
            fg = "#8d1f1f"
        elif level == "warning":
            bg = "#f5e2bf"
            fg = "#8a4d12"
        elif level == "info":
            bg = "#dceaf4"
            fg = "#21507a"
        else:
            bg = "#e6efe2"
            fg = "#215f52"
        self.alert_var.set(text)
        self.alert_banner.configure(bg=bg, fg=fg)

    def _set_text(self, widget: scrolledtext.ScrolledText, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _refresh_document_tabs(self) -> None:
        for path, widget in self.document_views.items():
            content = self._read_document(path)
            if self.document_cache.get(path) == content:
                continue
            self._set_text(widget, content)
            self.document_cache[path] = content

    def _read_document(self, path: Path) -> str:
        if not path.exists():
            return f"(missing)\n\n{path}"

        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"(unreadable: {exc})\n\n{path}"

    def _tail_log(self, *, path: Path, line_count: int) -> str:
        if not path.exists():
            return f"{path}\n\n(missing)"

        try:
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                tail = "".join(deque(handle, maxlen=line_count))
        except OSError as exc:
            return f"{path}\n\n(unreadable: {exc})"

        return f"{path}\n\n{tail}".rstrip()

    def _draw_tick_duration_chart(self, canvas: tk.Canvas, ticks: list[dict[str, object]]) -> None:
        points = []
        labels = []
        for tick in reversed(ticks[-20:]):
            value = float(tick.get("duration_seconds") or 0)
            points.append(value)
            started_at = tick.get("started_at")
            labels.append(started_at.strftime("%H:%M") if isinstance(started_at, datetime) else "")
        self._draw_line_chart(
            canvas,
            values=points,
            labels=labels,
            color="#215f52",
            unit="s",
        )

    def _draw_request_chart(self, canvas: tk.Canvas, ticks: list[dict[str, object]]) -> None:
        values = [int(tick.get("tick_api_request_count") or 0) for tick in reversed(ticks[-20:])]
        labels = [
            tick.get("started_at").strftime("%H:%M")
            if isinstance(tick.get("started_at"), datetime)
            else ""
            for tick in reversed(ticks[-20:])
        ]
        self._draw_line_chart(
            canvas,
            values=values,
            labels=labels,
            color="#9f5d26",
            unit="req",
        )

    def _draw_hourly_proposal_chart(
        self,
        canvas: tk.Canvas,
        proposals: list[dict[str, object]],
    ) -> None:
        now = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
        buckets: list[tuple[datetime, int]] = []
        for offset in range(11, -1, -1):
            buckets.append((now.replace() - timedelta(hours=offset), 0))

        counts = {bucket.isoformat(): 0 for bucket, _ in buckets}
        for proposal in proposals:
            proposed_at = proposal.get("proposed_at")
            if not isinstance(proposed_at, datetime):
                continue
            bucket = proposed_at.astimezone().replace(minute=0, second=0, microsecond=0)
            key = bucket.isoformat()
            if key in counts:
                counts[key] += 1

        values = []
        labels = []
        for bucket, _ in buckets:
            values.append(counts[bucket.isoformat()])
            labels.append(bucket.strftime("%H:%M"))
        self._draw_bar_chart(
            canvas,
            values=values,
            labels=labels,
            color="#7a8b5b",
            unit="props",
        )

    def _draw_fitness_chart(
        self,
        canvas: tk.Canvas,
        rows: list[dict[str, object]],
    ) -> None:
        labels = [str(row.get("strategy_id", "")) for row in rows[:6]]
        values = [float(row.get("composite_fitness_score") or 0) for row in rows[:6]]
        self._draw_horizontal_bar_chart(
            canvas,
            labels=labels,
            values=values,
            color="#6f4a8e",
            unit="fit",
        )

    def _draw_strategy_coverage_chart(
        self,
        canvas: tk.Canvas,
        rows: list[dict[str, object]],
    ) -> None:
        labels = [
            self._short_strategy_label(str(row.get("strategy_id", "")))
            for row in rows
        ]
        values = [float(row.get("composite_fitness_score") or 0) for row in rows]
        self._draw_horizontal_bar_chart(
            canvas,
            labels=labels,
            values=values,
            color="#6f4a8e",
            unit="fit",
        )

    def _draw_strategy_leaderboard_chart(
        self,
        canvas: tk.Canvas,
        rows: list[dict[str, object]],
    ) -> None:
        labels = [
            self._short_strategy_label(str(row.get("strategy_id", "")))
            for row in rows
        ]
        values = [float(row.get("composite_fitness_score") or 0) for row in rows]
        detail_text = [
            (
                f"{float(row.get('composite_fitness_score') or 0):.2f} fit"
                f" | {str(row.get('latest_checkpoint_code') or '-')}"
                f" | {int(row.get('checkpoints_evaluated') or 0)} eval"
                f" | {str(row.get('sample_label') or 'none')}"
            )
            for row in rows
        ]
        self._draw_horizontal_bar_chart(
            canvas,
            labels=labels,
            values=values,
            color="#6f4a8e",
            unit="fit",
            detail_text=detail_text,
        )

    def _draw_strategy_proposal_chart(
        self,
        canvas: tk.Canvas,
        rows: list[dict[str, object]],
    ) -> None:
        labels = [
            self._short_strategy_label(str(row.get("strategy_id", "")))
            for row in rows
        ]
        values = [int(row.get("proposal_count_7d") or 0) for row in rows]
        self._draw_bar_chart(
            canvas,
            values=values,
            labels=labels,
            color="#7a8b5b",
            unit=" props",
        )

    def _draw_strategy_activity_chart(
        self,
        canvas: tk.Canvas,
        rows: list[dict[str, object]],
    ) -> None:
        labels = [str(row.get("label", "")) for row in rows]
        values = [int(row.get("count") or 0) for row in rows]
        self._draw_bar_chart(
            canvas,
            values=values,
            labels=labels,
            color="#9f5d26",
            unit=" props",
        )

    def _draw_strategy_training_chart(
        self,
        canvas: tk.Canvas,
        rows: list[dict[str, object]],
    ) -> None:
        labels = [
            self._short_strategy_label(str(row.get("strategy_id", "")))
            for row in rows
        ]
        values = [int(row.get("evaluated_outcomes_all") or 0) for row in rows]
        detail_text = [
            (
                f"{int(row.get('evaluated_outcomes_all') or 0)} out"
                f" | {int(row.get('total_proposals_all') or 0)} prop"
            )
            for row in rows
        ]
        self._draw_horizontal_bar_chart(
            canvas,
            labels=labels,
            values=values,
            color="#215f52",
            unit=" out",
            detail_text=detail_text,
        )

    def _draw_position_pl_chart(
        self,
        canvas: tk.Canvas,
        positions: list[dict[str, object]],
    ) -> None:
        labels = [str(item.get("symbol", "")) for item in positions]
        values = [float(item.get("unrealized_pl_usd") or 0) for item in positions]
        detail_text = [
            (
                f"${float(item.get('unrealized_pl_usd') or 0):+.2f}"
                f" | {float(item.get('unrealized_pl_pct') or 0):+.2f}%"
            )
            for item in positions
        ]
        self._draw_horizontal_bar_chart(
            canvas,
            labels=labels,
            values=values,
            color="#2b8a57",
            unit=" pnl",
            detail_text=detail_text,
        )

    def _draw_position_value_chart(
        self,
        canvas: tk.Canvas,
        positions: list[dict[str, object]],
    ) -> None:
        labels = [str(item.get("symbol", "")) for item in positions]
        values = [float(item.get("market_value_usd") or 0) for item in positions]
        detail_text = [
            (
                f"${float(item.get('market_value_usd') or 0):.2f}"
                f" | qty {float(item.get('qty') or 0):.4f}"
            )
            for item in positions
        ]
        self._draw_horizontal_bar_chart(
            canvas,
            labels=labels,
            values=values,
            color="#215f52",
            unit=" mv",
            detail_text=detail_text,
        )

    def _draw_cost_daily_chart(
        self,
        canvas: tk.Canvas,
        rows: list[dict[str, object]],
    ) -> None:
        labels = [str(row.get("label", "")) for row in rows]
        values = [float(row.get("estimated_cost_gbp") or row.get("estimated_cost_usd") or 0) for row in rows]
        self._draw_line_chart(
            canvas,
            values=values,
            labels=labels,
            color="#21507a",
            unit=" cost",
        )

    def _draw_cost_source_chart(
        self,
        canvas: tk.Canvas,
        rows: list[dict[str, object]],
    ) -> None:
        labels = [str(row.get("source", "")) for row in rows[:8]]
        values = [float(row.get("estimated_cost_gbp") or row.get("estimated_cost_usd") or 0) for row in rows[:8]]
        detail_text = [
            (
                f"£{float(row.get('estimated_cost_gbp') or 0):.4f}"
                f" | ${float(row.get('estimated_cost_usd') or 0):.4f}"
                f" | {int(row.get('request_count') or 0)} req"
            )
            for row in rows[:8]
        ]
        self._draw_horizontal_bar_chart(
            canvas,
            labels=labels,
            values=values,
            color="#9f5d26",
            unit=" cost",
            detail_text=detail_text,
        )

    def _draw_line_chart(
        self,
        canvas: tk.Canvas,
        *,
        values: list[float | int],
        labels: list[str],
        color: str,
        unit: str,
    ) -> None:
        canvas.delete("all")
        width = max(320, canvas.winfo_width() or 320)
        height = max(220, canvas.winfo_height() or 220)
        canvas.configure(width=width, height=height)
        if not values:
            self._draw_empty_chart(canvas, width, height)
            return

        left, right, top, bottom = 42, width - 20, 18, height - 38
        max_value = max(float(value) for value in values) or 1.0
        min_value = min(float(value) for value in values)
        span = max(1.0, max_value - min(0.0, min_value))

        canvas.create_line(left, bottom, right, bottom, fill="#cabfae", width=1)
        canvas.create_line(left, top, left, bottom, fill="#cabfae", width=1)

        count = len(values)
        points: list[float] = []
        for index, value in enumerate(values):
            x = left if count == 1 else left + ((right - left) * index / (count - 1))
            normalized = (float(value) - min(0.0, min_value)) / span
            y = bottom - ((bottom - top) * normalized)
            points.extend([x, y])
        if len(points) >= 4:
            canvas.create_line(*points, fill=color, width=3, smooth=True)
        for index, value in enumerate(values):
            x = left if count == 1 else left + ((right - left) * index / (count - 1))
            normalized = (float(value) - min(0.0, min_value)) / span
            y = bottom - ((bottom - top) * normalized)
            canvas.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline=color)
            if index in {0, count - 1} or index % max(1, count // 4) == 0:
                canvas.create_text(x, bottom + 14, text=labels[index], fill="#6d655d", font=("Menlo", 8))

        canvas.create_text(right, top, anchor="ne", text=f"max {max_value:.1f}{unit}", fill="#6d655d", font=("Menlo", 9))
        canvas.create_text(left, top, anchor="nw", text=f"min {min_value:.1f}{unit}", fill="#6d655d", font=("Menlo", 9))

    def _draw_bar_chart(
        self,
        canvas: tk.Canvas,
        *,
        values: list[int],
        labels: list[str],
        color: str,
        unit: str,
    ) -> None:
        canvas.delete("all")
        width = max(320, canvas.winfo_width() or 320)
        height = max(220, canvas.winfo_height() or 220)
        canvas.configure(width=width, height=height)
        if not values:
            self._draw_empty_chart(canvas, width, height)
            return

        left, right, top, bottom = 36, width - 20, 18, height - 38
        max_value = max(values) or 1
        canvas.create_line(left, bottom, right, bottom, fill="#cabfae", width=1)
        bar_width = max(8, int((right - left) / max(1, len(values) * 1.6)))
        gap = max(4, int((right - left - (bar_width * len(values))) / max(1, len(values) - 1)))
        x = left
        for index, value in enumerate(values):
            bar_height = 0 if max_value == 0 else ((bottom - top) * (value / max_value))
            canvas.create_rectangle(
                x,
                bottom - bar_height,
                x + bar_width,
                bottom,
                fill=color,
                outline=color,
            )
            if len(values) <= 12 or index % max(1, len(values) // 6) == 0:
                canvas.create_text(x + (bar_width / 2), bottom + 14, text=labels[index], fill="#6d655d", font=("Menlo", 8))
            x += bar_width + gap
        canvas.create_text(right, top, anchor="ne", text=f"max {max_value}{unit}", fill="#6d655d", font=("Menlo", 9))

    def _draw_horizontal_bar_chart(
        self,
        canvas: tk.Canvas,
        *,
        labels: list[str],
        values: list[float],
        color: str,
        unit: str,
        detail_text: list[str] | None = None,
    ) -> None:
        canvas.delete("all")
        width = max(320, canvas.winfo_width() or 320)
        height = max(220, canvas.winfo_height() or 220)
        canvas.configure(width=width, height=height)
        if not values:
            self._draw_empty_chart(canvas, width, height)
            return

        left, right, top, bottom = 120, width - 20, 18, height - 20
        max_abs = max(max(abs(value) for value in values), 1.0)
        row_height = max(24, int((bottom - top) / max(1, len(values))))
        zero_x = left + ((right - left) / 2)
        canvas.create_line(zero_x, top, zero_x, bottom, fill="#cabfae", width=1)

        for index, (label, value) in enumerate(zip(labels, values, strict=False)):
            y_top = top + (index * row_height) + 4
            y_bottom = y_top + row_height - 10
            y_mid = (y_top + y_bottom) / 2
            canvas.create_text(left - 8, y_mid, anchor="e", text=label[:18], fill="#6d655d", font=("Menlo", 8))
            magnitude = abs(value) / max_abs
            if value >= 0:
                x0, x1 = zero_x, zero_x + ((right - zero_x) * magnitude)
                fill = color
            else:
                x0, x1 = zero_x - ((zero_x - left) * magnitude), zero_x
                fill = "#b85f5f"
            canvas.create_rectangle(x0, y_top, x1, y_bottom, fill=fill, outline=fill)
            canvas.create_text(
                right,
                y_mid,
                anchor="e",
                text=(
                    detail_text[index]
                    if isinstance(detail_text, list) and index < len(detail_text)
                    else f"{value:.2f} {unit}"
                ),
                fill="#6d655d",
                font=("Menlo", 8),
            )

    def _draw_empty_chart(self, canvas: tk.Canvas, width: int, height: int) -> None:
        canvas.create_text(
            width / 2,
            height / 2,
            text="No data yet",
            fill="#8a8178",
            font=("Avenir Next", 12),
        )

    def _short_strategy_label(self, strategy_id: str) -> str:
        normalized = strategy_id.strip()
        replacements = {
            "mean_reversion.": "mean_rev.",
            "crypto_momentum.": "crypto_mom.",
            "liquidity_probe.": "liq_probe.",
            "momentum.volatility_breakout": "mom.vol_breakout",
            "momentum.": "momentum.",
        }
        for old, new in replacements.items():
            if normalized.startswith(old):
                return normalized.replace(old, new, 1)
        return normalized


def run_dashboard() -> None:
    CentaurDashboardApp(config=load_runtime_config()).run()

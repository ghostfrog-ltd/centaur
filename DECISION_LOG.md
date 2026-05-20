# Project Centaur Decision Log

Read this file first, then consult the canonical detailed log in:
- `docs/DECISION_LOG.md`

## Current High-Signal Decisions
- Surface Centaur's activity trail in status/dashboard views, including raw strategy signals, fitness-suppressed signals, surviving signals, and the current trade blocker, so "no Alpaca order" is not mistaken for "system idle."
- Add a guarded paper-only adaptive controller for the strategy-allocation suppress threshold; it uses the trade-aware GA adviser, a current-tick cliff governor, and persisted state to follow clean paper-allowed cliffs while keeping blocked/disallowed cliffs separated, and must not mutate `.env` or any other paper/live risk policy.
- Add a recommendation-only holding-window fitness adviser for `mean_reversion.snapback`; it compares fixed `15m`/`1h`/`1d` outcomes and simple dynamic policies, but must not alter managed paper exits without a separate explicit override.
- Preserve Centaur's managed-exit plan across Alpaca order refreshes and recover missing stop/target/holding-window data from the matching shadow proposal, so broker payload polling cannot silently strand an aged paper position.
- Start the multi-broker refactor by putting the working Alpaca execution path behind a broker adapter first, so current paper trading stays stable while IG is scaffolded.
- Keep IG scaffold-only for now; do not activate it for execution until its minimum-bet and leverage math can pass the `$10` / `1x` safety rules.
- Persist `broker_id` on paper-trade orders so future multi-broker reporting does not pollute Alpaca and IG execution history together.
- Use Gemini API as the current LLM layer.
- Keep the Gemini adapter in the repo, but allow Gemini analysis to be disabled by config so Centaur can run in function-only mode when API cost is too high.
- Temporarily hide the standalone `Graphs` dashboard tab while diagnosing Tk UI responsiveness; keep the rest of the dashboard active so monitoring remains available.
- Temporarily hide all dashboard tabs and run the Tk monitor in a single flat view while diagnosing UI responsiveness.
- Temporarily disable the live runtime-log and wrapper-log tail panes in the Tk monitor while diagnosing UI responsiveness.
- Temporarily disable the recent-activity panel in the Tk monitor while diagnosing UI responsiveness.
- Make the Tk dashboard use a lighter status snapshot and reuse it for rendering, instead of building a second full snapshot on every refresh.
- Build the system as explicit pipelines, not a monolithic agent.
- Use PostgreSQL as the live operations store.
- Prefer `launchd` over cron on this Mac for unattended scheduling.
- On the migrated Mac, make the `launchd` wrapper prefer the project-local `.venv-mac` Python environment so unattended ticks use a modern interpreter with the PostgreSQL driver installed.
- Keep unattended runtime logs in the home directory, not on the external project volume.
- Start with shadow trading before broader paper execution.
- Keep Gemini out of the critical path for shadow proposal generation.
- Use deterministic, pluggable strategy profiles.
- Use historical replay to accelerate training.
- Use simple managed paper orders instead of fractional bracket entries.
- Surface broker failures directly in status and dashboard views.
- Score shadow and replay outcomes with configurable execution friction instead of perfect-fill assumptions.
- Show open-position and trade-blocker diagnostics in status and dashboard views.
- Show API cost visibility in the dashboard and explicitly flag when pricing inputs are incomplete.
- Pin Gemini cost accounting to the official `gemini-2.5-flash` rates instead of leaving pricing at zero.
- Support a one-shot historical API cost repricing pass so older usage rows can be recalculated from stored units when pricing changes.
- Keep `momentum.volatility_breakout` in shadow mode until it earns enough evidence.
- Separate recent-window strategy counts from all-time training volume in the dashboard.
- Rank dashboard strategy rows by current best fitness and explain why the top strategy is top, while still surfacing sample-size caveats.
- Surface Alpaca account balance and day-change information directly in status and dashboard views.
- Give account information its own dashboard tab and a header day-P/L badge for faster at-a-glance reading.
- Show the header day-P/L in both USD and GBP so the operator can read paper-account movement in local currency without leaving the dashboard.
- Surface the paper capital envelope directly in the dashboard and status view so the `$10 x 10 = $100` operating bankroll is visible, not just implied.
- Compare Centaur’s current paper-trading pace against simple long-term investing yardsticks on the same bankroll, while clearly labeling that short paper samples are not proof.
- Anchor that return-comparison view to the last persisted tick before the first paper order, not the mutable paper-order row's current `tick_id`, so later order polling does not rewrite the starting baseline.
- Keep written strategy-selection and go-live checklists in the repo and expose them as dashboard-readable tabs.
- Widen the paper envelope only by explicit human override; the current override allows up to `10` paper positions, enables crypto paper trading, and swaps equity discovery to the full Nasdaq-100 universe while keeping `$10` notional and one-order-per-tick discipline.
- Harden micro-trade economics with a fixed shadow/replay friction floor, a minimum projected-gain gate, and marketable limit paper orders instead of raw market orders.
- Add a persisted daily equity-drawdown protector and a stale-entry-order reaper inside the main control pipeline.
- Persist broker account snapshots by `broker_id` and show broker-separated account state in status/dashboard surfaces before any IG execution is activated.
- Preserve broker-reported fractional exit quantities and only round down to Alpaca's 9-decimal fractional precision, because rounding managed-exit quantities upward causes insufficient-quantity rejects.
- Enable `momentum.volatility_breakout` for micro paper execution by explicit human override on 2026-04-15, while preserving `$10` notional, Alpaca Paper routing, the one-order-per-tick cap, and the `$5.00` daily protector.
- Lower the strategy-allocation suppress threshold from `-5.0` to `-5.25` by explicit human override on 2026-04-21 after a seven-day flatline, while preserving `$10` notional, Alpaca Paper routing, allowed strategies, market-hours, projected-gain, max-slot, and daily-protection rules.
- Lower the strategy-allocation suppress threshold again from `-5.25` to `-5.50` by explicit human override on 2026-05-07 after a second flatline, while preserving `$10` notional, Alpaca Paper routing, allowed strategies, market-hours, projected-gain, max-slot, and daily-protection rules.
- Lower the strategy-allocation suppress threshold again from `-5.50` to `-5.70` by explicit human override on 2026-05-11 after current `mean_reversion.snapback` signals were suppressed around `-5.669`, while preserving `$10` notional, Alpaca Paper routing, allowed strategies, market-hours, projected-gain, max-slot, and daily-protection rules.
- Persist a compact per-tick blocker summary in the state snapshot and surface it in status so entry-stage and exit-stage blockers can be audited directly from each stored tick.
- Make the primary dashboard path a DDEV/OrbStack-routed web app backed by a host-written `StatusReporter` snapshot file, and keep the direct Python web view plus the older Tk monitor only as fallback surfaces.
- Prepare an Alpaca Live sidecar lane for a possible May 2026 go-live discussion; it can only follow same-tick paper-approved trades and remains disabled unless credentials, activation acknowledgement, live allowlist, kill-switch, and daily-loss gates are explicitly set.
- Add an earned-slot compounding rule for paper and future live: each full `$10` of tracked P/L above the account lane's pre-first-order baseline adds one effective `$10` slot, while the per-trade notional remains fixed at `$10`.

## Canonical File
The detailed rationale, chronology, and implementation notes live in:
- `docs/DECISION_LOG.md`

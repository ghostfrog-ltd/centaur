# Project Centaur: Autonomous Wealth Generation Engine (2026)
**Target:** Semi-Autonomous Trading & Portfolio Growth
**Architecture:** LangGraph-Orchestrated Sentinel-Analyst-CFO Pipelines
**Optimization:** Evolutionary Genetic Algorithms

## Working Record
The long-lived project record now lives here:
- `docs/PROJECT_RECORD.md`
- `docs/DECISION_LOG.md`

These files should be updated whenever the system's operating reality or major decisions change, so the project does not depend on chat context alone.

---

## 0. Prime Directives
The system must optimize for long-term capital growth, not reckless short-term profit.

* **Prime Directive 1:** Grow capital safely, legally, and repeatably through trading.
* **Prime Directive 2:** Maximize risk-adjusted returns, not raw profit at any cost.
* **Prime Directive 3:** Preserve capital first. A strategy that cannot survive drawdowns is not fit for production.
* **Prime Directive 4:** Every decision must remain auditable, measurable, and attributable to data.
* **Prime Directive 5:** The fitness algorithm should reward profit only when it is achieved within hard risk and compliance limits.

### Fitness Mindset
The evolutionary loop should not select for "the bot that made the most money by any means possible." It should select for strategies that:

* Produce net profit after costs.
* Limit drawdown and concentration risk.
* Stay consistent across multiple sessions and market conditions.
* Avoid unnecessary API or inference cost.
* Fail hard if any CFO or compliance rule is violated.

---

## 1. Core Philosophy: The "eBay Bargain" for Markets
The system avoids the "Speed Trap" of High-Frequency Trading. Instead of trying to outrun institutional bots, it acts as a **Value Synthesizer**. It treats stocks like your eBay system treated items:
* **Scanning:** Looking for pricing anomalies (inefficiencies).
* **Validation:** Cross-referencing technical spikes with real-world news and social sentiment.
* **Arbitrage:** Entering trades where the "fair value" (determined by the LLM) is higher than the "market price" (determined by the API).

---

## 2. The 2026 Technology Stack
Optimized for the current proof-of-concept environment, with room to grow later.

* **Broker API:** Alpaca Markets (Paper Trading for PoC).
    * *Why:* Zero-commission, robust Python SDK, and supports "Alpaca MCP" for direct AI-to-Market communication.
* **Reasoning Layer:** Gemini API.
    * *Current Reality:* We do not have a local LLM in the stack right now, so all reasoning, summarization, and trade-context analysis flows through Gemini.
    * *Design Goal:* Keep the LLM integration behind a thin adapter so we can swap in local or alternative models later without rewriting the trading logic.
* **Workflow Orchestration:** LangGraph.
    * *Why:* The system should be split into explicit pipelines and stateful graph nodes rather than one monolithic agent.
    * *Guardrail:* LangGraph ensures the bot follows a controlled state machine (for example, it cannot Buy without passing a Risk Check node).
* **Database:** PostgreSQL with pgvector.
    * *Why:* To store "Embeddings" of successful trades to serve as a long-term memory.

---

## 3. Pipeline-First Architecture with LangGraph
The system should be built as a collection of clear pipelines, orchestrated through LangGraph, so each responsibility is isolated, testable, and replaceable.

### Proposed Core Pipelines
* **Market Scan Pipeline:** Pull watchlists, price movements, volume anomalies, and candidate symbols from market data APIs.
* **Context Enrichment Pipeline:** Gather news, filings, technical indicators, and sentiment inputs for each candidate.
* **Gemini Analysis Pipeline:** Use Gemini to score opportunity quality, summarize catalysts, and estimate confidence.
* **Risk & CFO Pipeline:** Apply deterministic rules for position sizing, stop-loss limits, exposure caps, and veto logic.
* **Execution Pipeline:** Submit, track, and reconcile paper trades through Alpaca.
* **Post-Trade Evaluation Pipeline:** Score outcomes, track why trades won or lost, and write structured memory to PostgreSQL.
* **Evolution Pipeline:** Run the genetic algorithm against historical paper-trading performance and produce the next strategy genome.

### Why This Matters
* Each pipeline can be developed and tested independently.
* LangGraph can coordinate handoffs between pipelines while preserving state and auditability.
* We can replace Gemini, Alpaca, or individual strategy modules later without rebuilding the full engine.

### Current Deterministic Strategy Direction
The early learning loop should favor deterministic, auditable strategies before AI-assisted execution. One concrete example now in shadow mode is:
* `momentum.volatility_breakout`: a 20-bar breakout strategy for high-beta equities that requires price to clear the prior 20-bar high, volume to exceed 2.0x the 20-bar average, and ATR to be above 1 percent of price.

This breakout profile uses:
* simple market-entry logic for paper execution compatibility
* internal stop/target management at `2.0 x ATR` and `4.0 x ATR`
* a conservative break-even trailing rule that activates on the bar after the `+2.0 ATR` trigger is reached

---

## 4. Self-Learning Layer: The Genetic Algorithm (GA)
To ensure the system improves without you manually tweaking code, we implement an **Evolutionary Strategy**.

### The "Genome"
The bot's strategy is defined by a set of parameters (the DNA):
* `RSI_Threshold`: When is a stock "oversold"?
* `Sentiment_Confidence`: How "sure" must Gemini be to trigger a trade?
* `StopLoss_Percentage`: How much pain can we take?
* `Sector_Weighting`: Which industries are we currently prioritizing?

### The Evolutionary Loop
1.  **Population:** The system spawns 10 "Child Bots," each with slightly different DNA (e.g., Bot A is aggressive, Bot B is conservative).
2.  **Fitness Test:** These bots run on Paper Trading for a set period (e.g., 5 days).
3.  **Selection:** The top 2 most profitable bots are "Selected."
4.  **Crossover & Mutation:** Their DNA is combined to create a new generation. We add "Mutation" (random changes) to prevent the bot from getting stuck in one strategy.
5.  **Iteration:** Over weeks, the system "evolves" toward the most profitable parameters for the current market regime.

---

## 5. Resilience & Security
To avoid the security pitfalls of current "open" agent frameworks:
* **Isolated Execution:** The bot runs in a Docker container with restricted network access (only to Alpaca and Google APIs).
* **The "CFO" Kill-Switch:** A deterministic Python node that has the power to veto any AI decision if it violates a hard risk rule (e.g., "Never trade more than 5% of the balance").
* **Audit Logging:** Every decision should be saved for post-mortem analysis, including inputs, outputs, scores, and rule checks. We should avoid storing raw chain-of-thought and instead log structured reasoning summaries.

---

## 6. Phase 1: Proof of Concept (PoC)
* **Initial Bankroll:** $100.00 (Simulated).
* **Duration:** 14 Days.
* **Goal:** Not to make money, but to ensure the "Fitness Function" correctly identifies why trades were won or lost.

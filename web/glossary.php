<?php
declare(strict_types=1);

header('Cache-Control: no-store, no-cache, must-revalidate, max-age=0');
header('Pragma: no-cache');

$templatePath = dirname(__DIR__) . '/.env.example';
$templateEntries = loadEnvTemplateEntries($templatePath);
$glossaryDocs = glossaryDocs();
$glossarySections = glossarySections();
$renderSections = buildGlossarySections($glossarySections, $templateEntries, $glossaryDocs);
$summary = buildGlossarySummary($renderSections);

function loadEnvTemplateEntries(string $path): array
{
    if (!is_file($path)) {
        return [];
    }

    $entries = [];
    $lines = file($path, FILE_IGNORE_NEW_LINES);
    if ($lines === false) {
        return [];
    }

    foreach ($lines as $index => $line) {
        if (!preg_match('/^([A-Z0-9_]+)=(.*)$/', $line, $matches)) {
            continue;
        }

        $entries[$matches[1]] = [
            'key' => $matches[1],
            'default' => trim((string) $matches[2]),
            'line' => $index + 1,
        ];
    }

    return $entries;
}

function glossaryDocs(): array
{
    return array_merge(
        [
            'CENTAUR_MODE' => doc(
                'Selects the runtime mode label for the process.',
                'Valid values are `shadow`, `paper`, `live_dry`, and `live`. This influences reporting and safety behavior, but it does not bypass broker or risk gates on its own.',
                ['mode', 'critical']
            ),
            'CENTAUR_ENVIRONMENT' => doc(
                'Declares whether the active lane should be treated as paper or live.',
                'If left empty, Centaur derives this from `CENTAUR_MODE`. The value is mainly used for honest provenance labels in storage and dashboards.',
                ['mode']
            ),
            'CENTAUR_ENV' => doc(
                'Adds a human environment label such as `development` or `production`.',
                'This is operational context rather than a trading lever.',
                ['ops']
            ),
            'CENTAUR_TIMEZONE' => doc(
                'Timezone used for Centaur-facing timestamps and operator reporting.',
                'Keep this aligned with how you review logs and dashboards.',
                ['ops']
            ),
            'MARKET_TIMEZONE' => doc(
                'Reference timezone for exchange-session logic.',
                'Equity market-hours checks depend on this being correct.',
                ['market-hours', 'critical']
            ),
            'LOG_LEVEL' => doc(
                'Controls runtime log verbosity.',
                'Use quieter levels for unattended operation and more verbose levels for debugging.',
                ['ops']
            ),
            'CONTROL_TICK_INTERVAL_SECONDS' => doc(
                'Target cadence for the control loop.',
                'The launch agent uses this as the intended rhythm between ticks. Faster ticks increase operator visibility but should not widen risk.',
                ['scheduler']
            ),
            'CONTROL_MAX_TICK_RUNTIME_SECONDS' => doc(
                'Soft runtime budget for a single tick.',
                'If normal ticks run longer than this, it is a sign the pipeline is falling behind the intended cadence.',
                ['scheduler']
            ),
            'CONTROL_ENABLE_PROFILING' => doc(
                'Toggles lightweight profiling and runtime diagnostics.',
                'Useful for investigating slow ticks without changing trading behavior.',
                ['ops']
            ),
            'CONTROL_REFRESH_DASHBOARD_SNAPSHOT' => doc(
                'Operator toggle for inline dashboard snapshot refresh work.',
                'Project docs describe this as the switch that keeps normal ticks from waiting on dashboard snapshot generation. The current PHP dashboard reads a live API proxy, so treat this as an ops-facing knob rather than a strategy lever.',
                ['ops', 'note']
            ),
            'CONTROL_LOCK_NAME' => doc(
                'Name of the scheduler lock used by the wrapper script.',
                'This prevents overlapping ticks from stacking when one run takes too long.',
                ['scheduler', 'critical']
            ),
            'OPERATIONS_DB_BACKEND' => doc(
                'Backend preference for operational storage.',
                'Current project truth is PostgreSQL for active paper/live work. When PostgreSQL is configured, or execution is enabled, Centaur should fail closed instead of silently falling back.',
                ['storage', 'critical']
            ),
            'CORE_POSTGRES_SCHEMA' => doc(
                'Shared PostgreSQL lane for reviewed evidence and strategy fitness.',
                'This is the cross-environment core schema.',
                ['storage']
            ),
            'PAPER_POSTGRES_SCHEMA' => doc(
                'Paper-execution PostgreSQL lane name.',
                'Used to separate paper execution/account rows from shared evidence.',
                ['storage', 'paper']
            ),
            'LIVE_POSTGRES_SCHEMA' => doc(
                'Live-execution PostgreSQL lane name.',
                'Used to separate live execution/account rows from shared evidence.',
                ['storage', 'live']
            ),
            'USAGE_LEDGER_DB_PATH' => doc(
                'Path for the API usage and cost ledger database.',
                'This ledger can remain SQLite even when operational trading data lives in PostgreSQL.',
                ['cost', 'storage']
            ),
            'POSTGRES_SCHEMA' => doc(
                'Optional active PostgreSQL runtime schema override.',
                'When set, this picks the currently active lane schema for a deployment while the broader core, paper, and live layout still exists alongside it.',
                ['storage']
            ),
            'API_DAILY_COST_WARNING_USD' => doc(
                'Daily API spend warning threshold.',
                'Crossing this level should prompt a review before costs drift further.',
                ['cost']
            ),
            'API_DAILY_COST_LIMIT_USD' => doc(
                'Daily API spend hard guardrail.',
                'This is the budget ceiling Centaur should treat as the daily limit for provider usage.',
                ['cost', 'critical']
            ),
            'POSTGRES_HOST' => doc(
                'PostgreSQL host used when building `DATABASE_URL` from parts.',
                'Ignored if a real `DATABASE_URL` is already set.',
                ['storage']
            ),
            'POSTGRES_PORT' => doc(
                'PostgreSQL port used when building `DATABASE_URL` from parts.',
                'Defaults to `5432` in the loader.',
                ['storage']
            ),
            'POSTGRES_DB' => doc(
                'PostgreSQL database name used when building `DATABASE_URL` from parts.',
                'Keep this aligned with the actual operations database.',
                ['storage']
            ),
            'POSTGRES_USER' => doc(
                'PostgreSQL username used when building `DATABASE_URL` from parts.',
                'This is a secret-bearing field and should stay in local ops config only.',
                ['storage', 'secret']
            ),
            'POSTGRES_PASSWORD' => doc(
                'PostgreSQL password used when building `DATABASE_URL` from parts.',
                'Treat this as sensitive secret material.',
                ['storage', 'secret']
            ),
            'POSTGRES_SSLMODE' => doc(
                'Optional PostgreSQL SSL mode appended to the connection string.',
                'Useful when the database requires explicit SSL behavior.',
                ['storage']
            ),
            'DATABASE_URL' => doc(
                'Full PostgreSQL connection string.',
                'If this contains a real value, it wins over the individual `POSTGRES_*` parts.',
                ['storage', 'critical', 'secret']
            ),
            'GEMINI_API_KEY' => doc(
                'Credential for Gemini-backed analysis.',
                'Keep this secret. Centaur keeps LLM work adapter-backed and must not let hidden model behavior drive risk decisions.',
                ['llm', 'secret']
            ),
            'GEMINI_API_BASE_URL' => doc(
                'Base URL for Gemini API requests.',
                'Normally the Google Generative Language endpoint.',
                ['llm']
            ),
            'GEMINI_MODEL' => doc(
                'Gemini model name used when analysis is enabled.',
                'Pinning this helps keep cost accounting and behavior stable.',
                ['llm']
            ),
            'GEMINI_ANALYSIS_ENABLED' => doc(
                'Enables or disables Gemini commentary/analysis.',
                'This should never be treated as permission to make opaque trading decisions.',
                ['llm', 'critical']
            ),
            'GEMINI_REQUEST_TIMEOUT_SECONDS' => doc(
                'Timeout budget for Gemini API calls.',
                'Shorter values protect the tick cadence when the model is slow.',
                ['llm']
            ),
            'GEMINI_ANALYSIS_CANDIDATE_LIMIT' => doc(
                'Maximum number of candidates sent to Gemini in one analysis pass.',
                'Higher values increase prompt size and cost.',
                ['llm', 'cost']
            ),
            'GEMINI_MAX_OUTPUT_TOKENS' => doc(
                'Upper bound on Gemini response length.',
                'This is primarily a cost and latency control.',
                ['llm', 'cost']
            ),
            'GEMINI_INPUT_COST_PER_MILLION_TOKENS_USD' => doc(
                'Input-side Gemini pricing assumption for internal cost accounting.',
                'Used for Centaur’s spend ledger rather than execution logic.',
                ['llm', 'cost']
            ),
            'GEMINI_OUTPUT_COST_PER_MILLION_TOKENS_USD' => doc(
                'Output-side Gemini pricing assumption for internal cost accounting.',
                'Used for Centaur’s spend ledger rather than execution logic.',
                ['llm', 'cost']
            ),
            'SHADOW_ENABLED' => doc(
                'Turns shadow proposal generation on or off.',
                'Shadow is the learning lane that gathers counterfactual evidence without mutating a broker.',
                ['shadow']
            ),
            'SHADOW_PROPOSAL_LIMIT' => doc(
                'Maximum number of shadow proposals generated per tick.',
                'Useful for keeping research volume bounded and interpretable.',
                ['shadow']
            ),
            'SHADOW_PROPOSAL_COOLDOWN_MINUTES' => doc(
                'Cooldown window before the same opportunity can be proposed again.',
                'This reduces spammy repeat proposals on the same symbol and strategy.',
                ['shadow']
            ),
            'SHADOW_MIN_OPPORTUNITY_SCORE' => doc(
                'Minimum score required before a shadow proposal is recorded.',
                'This is an upstream quality filter, not an execution permission switch.',
                ['shadow']
            ),
            'SHADOW_STOP_LOSS_PCT' => doc(
                'Default stop distance for shared shadow strategies.',
                'Used when evaluating counterfactual shadow trades.',
                ['shadow', 'risk']
            ),
            'SHADOW_TARGET_MULTIPLE' => doc(
                'Default target multiple relative to risk for shared shadow strategies.',
                'A value of `2.0` means the target is roughly two times the stop distance.',
                ['shadow']
            ),
            'PAPER_CRYPTO_MOMENTUM_STOP_LOSS_PCT' => doc(
                'Paper crypto-specific stop distance for the momentum lane.',
                'Separated from live so paper can test stricter or looser momentum behavior without silently changing live.',
                ['paper', 'crypto', 'risk']
            ),
            'PAPER_CRYPTO_MOMENTUM_TARGET_MULTIPLE' => doc(
                'Paper crypto-specific target multiple for the momentum lane.',
                'Controls the paper reward target relative to risk.',
                ['paper', 'crypto']
            ),
            'PAPER_CRYPTO_MOMENTUM_MIN_SIGNAL_SCORE' => doc(
                'Minimum raw signal score for paper crypto momentum candidates.',
                'Acts as a first-pass quality gate before later fitness checks.',
                ['paper', 'crypto']
            ),
            'PAPER_CRYPTO_MOMENTUM_MIN_MOVEMENT_PCT' => doc(
                'Minimum positive movement required for paper crypto momentum candidates.',
                'Helps avoid treating flat noise as momentum.',
                ['paper', 'crypto']
            ),
            'PAPER_CRYPTO_MOMENTUM_MIN_DISCOVERY_SCORE' => doc(
                'Discovery-stage score floor for paper crypto candidates.',
                'Candidates below this threshold do not proceed into deeper evaluation.',
                ['paper', 'crypto']
            ),
            'PAPER_CRYPTO_MOMENTUM_MIN_TRADE_COUNT' => doc(
                'Minimum trade-count evidence needed for paper crypto momentum evaluation.',
                'This helps keep fitness from leaning on extremely thin sample sizes.',
                ['paper', 'crypto']
            ),
            'LIVE_CRYPTO_MOMENTUM_STOP_LOSS_PCT' => doc(
                'Live crypto-specific stop distance for the momentum lane.',
                'Defaults to paper; if live is armed, a difference must be explicitly named in the same-as-paper validator allowlist.',
                ['live', 'crypto', 'risk', 'critical']
            ),
            'LIVE_CRYPTO_MOMENTUM_TARGET_MULTIPLE' => doc(
                'Live crypto-specific target multiple for the momentum lane.',
                'Defaults to paper and is guarded by live-vs-paper config validation.',
                ['live', 'crypto', 'critical']
            ),
            'LIVE_CRYPTO_MOMENTUM_MIN_SIGNAL_SCORE' => doc(
                'Minimum raw signal score for live crypto momentum candidates.',
                'Defaults to paper and is guarded by live-vs-paper config validation.',
                ['live', 'crypto', 'critical']
            ),
            'LIVE_CRYPTO_MOMENTUM_MIN_MOVEMENT_PCT' => doc(
                'Minimum positive movement required for live crypto momentum candidates.',
                'Defaults to paper and is guarded by live-vs-paper config validation.',
                ['live', 'crypto', 'critical']
            ),
            'LIVE_CRYPTO_MOMENTUM_MIN_DISCOVERY_SCORE' => doc(
                'Discovery-stage score floor for live crypto candidates.',
                'Defaults to paper and is guarded by live-vs-paper config validation.',
                ['live', 'crypto', 'critical']
            ),
            'LIVE_CRYPTO_MOMENTUM_MIN_TRADE_COUNT' => doc(
                'Minimum trade-count evidence needed for live crypto momentum evaluation.',
                'Defaults to paper and is guarded by live-vs-paper config validation.',
                ['live', 'crypto', 'critical']
            ),
            'SHADOW_CHECKPOINT_WINDOWS' => doc(
                'Future checkpoints recorded for each shadow proposal.',
                'These windows power outcome scoring and later strategy review.',
                ['shadow']
            ),
            'SHADOW_PROFIT_TARGET_LADDER_PCT' => doc(
                'Counterfactual profit-target ladder used for evidence.',
                'This supports “what if we had exited earlier or later?” reporting.',
                ['shadow']
            ),
            'SHADOW_EXECUTION_SPREAD_BPS' => doc(
                'Spread assumption applied to shadow fills.',
                'This makes counterfactual scoring less optimistic.',
                ['shadow', 'cost']
            ),
            'SHADOW_ENTRY_SLIPPAGE_BPS' => doc(
                'Entry slippage assumption applied to shadow fills.',
                'Especially important in micro-notional tests where a few basis points matter.',
                ['shadow', 'cost']
            ),
            'SHADOW_EXIT_SLIPPAGE_BPS' => doc(
                'Exit slippage assumption applied to shadow fills.',
                'Helps keep shadow outcomes closer to realistic execution.',
                ['shadow', 'cost']
            ),
            'SHADOW_FIXED_ROUND_TRIP_COST_USD' => doc(
                'Flat round-trip cost assumption for shadow scoring.',
                'Useful because micro trades are sensitive to penny-scale friction.',
                ['shadow', 'cost']
            ),
            'STRATEGY_FITNESS_LOOKBACK_DAYS' => doc(
                'Historical lookback window for fitness summaries.',
                'A value of `0` means use all available history.',
                ['fitness']
            ),
            'STRATEGY_FITNESS_MIN_CHECKPOINTS' => doc(
                'Minimum checkpoint count required before a fitness summary is considered reliable.',
                'This is about evidence confidence, not order routing.',
                ['fitness']
            ),
            'STRATEGY_ALLOCATION_MIN_CHECKPOINTS' => doc(
                'Minimum checkpoints before fitness can actively suppress or favor signals.',
                'Prevents very small samples from steering allocation.',
                ['fitness', 'critical']
            ),
            'STRATEGY_ALLOCATION_FAVOR_THRESHOLD' => doc(
                'Fitness score above which a signal is considered favored.',
                'This helps determine when evidence should support a strategy rather than merely allow it.',
                ['fitness']
            ),
            'STRATEGY_ALLOCATION_SUPPRESS_THRESHOLD' => doc(
                'Primary equity suppress threshold.',
                'Signals below this line are treated as blocked unless another guarded rule explicitly survives them.',
                ['fitness', 'critical']
            ),
            'STRATEGY_ALLOCATION_CRYPTO_SUPPRESS_THRESHOLD' => doc(
                'Separate suppress threshold for crypto.',
                'Crypto keeps its own threshold because its behavior differs from equities.',
                ['fitness', 'crypto', 'critical']
            ),
            'STRATEGY_THRESHOLD_ADAPTIVE_ENABLED' => doc(
                'Enables the guarded adaptive suppress-threshold controller.',
                'This is paper research infrastructure and must stay bounded by its rails.',
                ['fitness', 'critical']
            ),
            'STRATEGY_THRESHOLD_ADAPTIVE_FLOOR' => doc(
                'Lowest value the adaptive threshold controller may move to.',
                'Acts as the lower rail for suppression changes.',
                ['fitness']
            ),
            'STRATEGY_THRESHOLD_ADAPTIVE_CEILING' => doc(
                'Highest value the adaptive threshold controller may move to.',
                'Acts as the upper rail for suppression changes.',
                ['fitness']
            ),
            'STRATEGY_THRESHOLD_ADAPTIVE_BAND_WIDTH' => doc(
                'Local band width used by threshold advice and cliff logic.',
                'This affects how near-miss evidence is interpreted around the active threshold.',
                ['fitness']
            ),
            'STRATEGY_THRESHOLD_ADAPTIVE_CLIFF_SAFETY_GAP' => doc(
                'Required gap between allowed and blocked cliffs for adaptive changes.',
                'Keeps threshold moves away from unsafe cliff edges.',
                ['fitness', 'risk']
            ),
            'STRATEGY_THRESHOLD_ADAPTIVE_MAX_STEP' => doc(
                'Maximum threshold adjustment size per change.',
                'Prevents large swings from one advice cycle to the next.',
                ['fitness']
            ),
            'STRATEGY_THRESHOLD_ADAPTIVE_MIN_CONFIDENCE' => doc(
                'Minimum confidence label required before adaptive changes are allowed.',
                'This is another guard against reacting to weak evidence.',
                ['fitness']
            ),
            'STRATEGY_THRESHOLD_ADAPTIVE_COOLDOWN_MINUTES' => doc(
                'Cooldown between adaptive threshold changes.',
                'Useful for damping oscillation.',
                ['fitness']
            ),
            'STRATEGY_THRESHOLD_ADAPTIVE_MIN_TICKS' => doc(
                'Minimum usable tick evidence before adaptive changes can happen.',
                'Prevents the controller from acting on a tiny sample.',
                ['fitness']
            ),
            'ALPACA_DATA_BASE_URL' => doc(
                'Base URL for Alpaca market-data requests.',
                'This is separate from the paper/live trading endpoints.',
                ['market-data']
            ),
            'ALPACA_STOCK_FEED' => doc(
                'Stock feed identifier used for Alpaca equity data.',
                'The template uses `iex`.',
                ['market-data']
            ),
            'ALPACA_REQUEST_TIMEOUT_SECONDS' => doc(
                'Shared timeout for Alpaca API requests.',
                'Applies to the configured Alpaca access paths and protects the tick cadence.',
                ['market-data']
            ),
            'ALPACA_DATA_REQUEST_COST_USD' => doc(
                'Per-request cost assumption for Alpaca equity market data.',
                'Used for internal API cost accounting.',
                ['market-data', 'cost']
            ),
            'ALPACA_CRYPTO_DATA_REQUEST_COST_USD' => doc(
                'Per-request cost assumption for Alpaca crypto market data.',
                'Used for internal API cost accounting.',
                ['market-data', 'cost']
            ),
            'ALPACA_WATCHLIST_SYMBOLS' => doc(
                'Primary Alpaca watchlist-style equity universe.',
                'This is the large equity pool Centaur keeps ready for discovery and scanning.',
                ['market-data']
            ),
            'ALPACA_CRYPTO_LOCATION' => doc(
                'Alpaca crypto market location code.',
                'The template uses `us`.',
                ['market-data', 'crypto']
            ),
            'ALPACA_CRYPTO_SYMBOLS' => doc(
                'Crypto symbols requested from Alpaca.',
                'This is the broker/data-provider-side crypto universe.',
                ['market-data', 'crypto']
            ),
            'HISTORICAL_BACKFILL_DEFAULT_DAYS' => doc(
                'Default lookback window for historical market-data backfills.',
                'Used when backfill commands run without an explicit days override.',
                ['backfill']
            ),
            'HISTORICAL_BACKFILL_DEFAULT_TIMEFRAME' => doc(
                'Default timeframe for historical market-data backfills.',
                'Examples include `1Min` and `1Hour`.',
                ['backfill']
            ),
            'HISTORICAL_REPLAY_DEFAULT_DAYS' => doc(
                'Default lookback window for replay runs.',
                'Used when replay is launched without an explicit override.',
                ['replay']
            ),
            'HISTORICAL_REPLAY_DEFAULT_TIMEFRAME' => doc(
                'Default bar timeframe for replay runs.',
                'This changes the granularity of the counterfactual replay.',
                ['replay']
            ),
            'HISTORICAL_REPLAY_MAX_TIMESTAMPS' => doc(
                'Optional cap on replay timestamps.',
                'A value of `0` means no explicit cap.',
                ['replay']
            ),
            'DISCOVERY_EQUITY_SYMBOLS' => doc(
                'Equity symbols scanned by the discovery pipeline.',
                'This is the evaluation universe, which can differ from broader provider watchlists.',
                ['market-data']
            ),
            'DISCOVERY_CRYPTO_SYMBOLS' => doc(
                'Crypto symbols scanned by the discovery pipeline.',
                'This is the evaluation universe for crypto discovery.',
                ['market-data', 'crypto']
            ),
            'DISCOVERY_TARGET_COUNT' => doc(
                'How many candidates discovery should pass downstream.',
                'This keeps the later evaluation stages bounded.',
                ['market-data']
            ),
            'ECB_REFERENCE_RATES_URL' => doc(
                'ECB FX feed used for reference-rate conversion.',
                'Useful for GBP-facing reporting and comparable operator summaries.',
                ['market-data', 'fx']
            ),
            'ECB_REQUEST_TIMEOUT_SECONDS' => doc(
                'Timeout for ECB FX requests.',
                'Long waits here should not block the control loop.',
                ['market-data', 'fx']
            ),
            'ECB_REFERENCE_CACHE_MINUTES' => doc(
                'Cache duration for ECB reference-rate data.',
                'Reduces repeated FX lookups while keeping rates reasonably fresh.',
                ['market-data', 'fx']
            ),
            'POLYGON_API_KEY' => doc(
                'Reserved optional Polygon credential.',
                'Present as future-provider scaffold; not part of the active execution path today.',
                ['provider', 'secret', 'scaffold']
            ),
            'POLYGON_REQUEST_COST_USD' => doc(
                'Per-request Polygon cost assumption.',
                'Used only for cost accounting while Polygon remains optional scaffolding.',
                ['provider', 'cost', 'scaffold']
            ),
            'NEWS_API_KEY' => doc(
                'Reserved optional News API credential.',
                'Present as future-provider scaffold; not part of the active execution path today.',
                ['provider', 'secret', 'scaffold']
            ),
            'NEWS_API_REQUEST_COST_USD' => doc(
                'Per-request News API cost assumption.',
                'Used only for cost accounting while News API remains optional scaffolding.',
                ['provider', 'cost', 'scaffold']
            ),
            'APP_SHARED_SECRET' => doc(
                'Reserved shared-secret slot for app-to-app integrations.',
                'Treat this as sensitive even though the current repo does not actively surface it on the dashboard.',
                ['integration', 'secret']
            ),
            'WEBHOOK_SECRET' => doc(
                'Reserved shared-secret slot for webhook validation.',
                'Treat this as sensitive even though it is currently more of a preparedness setting than an active trading lever.',
                ['integration', 'secret']
            ),
            'IG_API_KEY' => doc(
                'IG scaffold API key.',
                'IG is scaffold or shadow only right now and must fail closed for real execution.',
                ['ig', 'secret', 'scaffold']
            ),
            'IG_USERNAME' => doc(
                'IG scaffold username.',
                'Keep secret; IG remains scaffold-only.',
                ['ig', 'secret', 'scaffold']
            ),
            'IG_PASSWORD' => doc(
                'IG scaffold password.',
                'Keep secret; IG remains scaffold-only.',
                ['ig', 'secret', 'scaffold']
            ),
            'IG_ACCOUNT_TYPE' => doc(
                'IG account type, typically `DEMO`.',
                'Useful for keeping the scaffold lane honest about which environment it is wired to.',
                ['ig', 'scaffold']
            ),
            'IG_ACCOUNT_NUMBER' => doc(
                'IG account identifier.',
                'Keep secret; this is still scaffold-only configuration.',
                ['ig', 'secret', 'scaffold']
            ),
            'IG_BASE_URL' => doc(
                'Base URL for the IG API.',
                'The template points at the demo environment.',
                ['ig', 'scaffold']
            ),
            'IG_REQUEST_TIMEOUT_SECONDS' => doc(
                'Timeout for IG API calls.',
                'Important if you test the scaffold lane without letting it slow the control loop.',
                ['ig', 'scaffold']
            ),
            'IG_MIN_BET_PER_POINT_GBP' => doc(
                'Minimum IG bet-size assumption.',
                'This matters because IG may not fit the current `$10` micro-risk envelope.',
                ['ig', 'risk', 'scaffold']
            ),
            'IG_EPIC_OVERRIDES' => doc(
                'Optional symbol-to-IG-epic mapping overrides.',
                'Useful when a symbol needs an explicit IG market identifier.',
                ['ig', 'scaffold']
            ),
            'IG_REQUEST_COST_USD' => doc(
                'Per-request IG cost assumption for the usage ledger.',
                'Used for cost accounting while IG remains scaffold-only.',
                ['ig', 'cost', 'scaffold']
            ),
            'ALPACA_API_KEY' => doc(
                'Credential for Alpaca Paper trading.',
                'Keep secret. This is the active paper broker credential pair.',
                ['paper', 'secret']
            ),
            'ALPACA_SECRET_KEY' => doc(
                'Secret credential for Alpaca Paper trading.',
                'Keep secret. This is the active paper broker credential pair.',
                ['paper', 'secret']
            ),
            'ALPACA_BASE_URL' => doc(
                'Base URL for Alpaca Paper order-routing requests.',
                'The template points to the paper trading endpoint.',
                ['paper']
            ),
            'ALPACA_REQUEST_COST_USD' => doc(
                'Per-request cost assumption for Alpaca Paper trading calls.',
                'Used for internal cost accounting.',
                ['paper', 'cost']
            ),
            'TRAILING_DRAWDOWN_OBSERVER_ENABLED' => doc(
                'Enables the observe-only trailing drawdown monitor.',
                'This observer records evidence and advice; it is not the same as widening or changing execution risk rules.',
                ['paper', 'risk']
            ),
            'TRAILING_DRAWDOWN_OBSERVER_PAPER_GIVEBACK_USD' => doc(
                'Dollar giveback threshold for the paper trailing drawdown observer.',
                'Observe-only unless explicitly promoted in project policy.',
                ['paper', 'risk']
            ),
            'TRAILING_DRAWDOWN_OBSERVER_PAPER_GIVEBACK_PCT' => doc(
                'Percentage giveback threshold for the paper trailing drawdown observer.',
                'Observe-only unless explicitly promoted in project policy.',
                ['paper', 'risk']
            ),
            'ALPACA_LIVE_API_KEY' => doc(
                'Credential for Alpaca Live trading.',
                'Keep secret. Credentials alone are not enough to permit live entries.',
                ['live', 'secret', 'critical']
            ),
            'ALPACA_LIVE_SECRET_KEY' => doc(
                'Secret credential for Alpaca Live trading.',
                'Keep secret. Credentials alone are not enough to permit live entries.',
                ['live', 'secret', 'critical']
            ),
            'ALPACA_LIVE_BASE_URL' => doc(
                'Base URL for Alpaca Live order-routing requests.',
                'This is the funded-account endpoint.',
                ['live']
            ),
            'ALPACA_LIVE_REQUEST_COST_USD' => doc(
                'Per-request cost assumption for Alpaca Live trading calls.',
                'Used for internal cost accounting.',
                ['live', 'cost']
            ),
            'TRAILING_DRAWDOWN_OBSERVER_LIVE_GIVEBACK_USD' => doc(
                'Dollar giveback threshold for the live trailing drawdown observer.',
                'Observe-only unless explicitly promoted in project policy.',
                ['live', 'risk']
            ),
            'TRAILING_DRAWDOWN_OBSERVER_LIVE_GIVEBACK_PCT' => doc(
                'Percentage giveback threshold for the live trailing drawdown observer.',
                'Observe-only unless explicitly promoted in project policy.',
                ['live', 'risk']
            ),
        ],
        buildExecutionDocs('PAPER_EXECUTION', 'Paper', false),
        buildExecutionDocs('LIVE_EXECUTION', 'Live', true)
    );
}

function buildExecutionDocs(string $prefix, string $label, bool $isLive): array
{
    $lane = strtolower($label);
    $docs = [
        "{$prefix}_ENABLED" => doc(
            "{$label} execution master enable flag.",
            $isLive
                ? 'Turning this on is still not enough for live entries. The kill switch, credentials, activation acknowledgement, same-as-paper validation, and readiness guard must all pass.'
                : 'Turning this on allows Centaur to submit orders to the paper broker, subject to the kill switch and all other safety gates.',
            [$lane, 'critical']
        ),
        "{$prefix}_KILL_SWITCH" => doc(
            "{$label} execution kill switch.",
            $isLive
                ? 'Keep this true unless you intentionally want the live follower lane able to mutate the broker.'
                : 'When true, Centaur will not submit paper orders.',
            [$lane, 'critical']
        ),
        "{$prefix}_REQUIRE_MARKET_OPEN" => doc(
            "{$label} market-hours gate for equities.",
            'When true, equity entries respect exchange open/closed rules. Crypto can still behave separately.',
            [$lane, 'market-hours']
        ),
        "{$prefix}_EQUITY_ONLY" => doc(
            "{$label} asset-class restriction.",
            'When true, the lane will avoid crypto execution and only route equities.',
            [$lane]
        ),
        "{$prefix}_MAX_ORDERS_PER_TICK" => doc(
            "{$label} hard cap on order submissions per tick.",
            'This is one of the core anti-overtrading levers.',
            [$lane, 'risk']
        ),
        "{$prefix}_MAX_OPEN_POSITIONS" => doc(
            "{$label} slot cap for concurrently open positions.",
            'This bounds how many positions the lane may carry at once.',
            [$lane, 'risk']
        ),
        "{$prefix}_DEFAULT_NOTIONAL_USD" => doc(
            "{$label} per-trade notional size in US dollars.",
            $isLive
                ? 'The live lane is approved only inside the same-as-paper micro envelope, so widening this without an explicit approved difference should fail closed.'
                : 'This is the micro trade size Centaur uses when it enters a paper position.',
            [$lane, 'risk', 'critical']
        ),
        "{$prefix}_MAX_DAILY_DRAWDOWN_USD" => doc(
            "{$label} daily drawdown protector in US dollars.",
            'If losses breach this level, new entries should be blocked for the day.',
            [$lane, 'risk', 'critical']
        ),
        "{$prefix}_STALE_ORDER_MINUTES" => doc(
            "{$label} stale-entry timeout in minutes.",
            'Unfilled equity entry limits older than this should be cancelled or cleaned up.',
            [$lane]
        ),
        "{$prefix}_MIN_PROJECTED_GAIN_PCT" => doc(
            "{$label} minimum projected gain for equities.",
            'The value is expressed as a decimal fraction, so `0.015` means `1.5%`.',
            [$lane, 'risk']
        ),
        "{$prefix}_CRYPTO_MIN_PROJECTED_GAIN_PCT" => doc(
            "{$label} minimum projected gain for crypto.",
            'The value is expressed as a decimal fraction, so `0.02` means `2%`.',
            [$lane, 'crypto', 'risk']
        ),
        "{$prefix}_PROFIT_CAPTURE_PCT" => doc(
            "{$label} managed profit-capture trigger.",
            'This is the early profit-taking level for the managed exit path.',
            [$lane]
        ),
        "{$prefix}_LIMIT_BUFFER_BPS" => doc(
            "{$label} equity marketable-limit buffer in basis points.",
            'A higher number makes entry limits more aggressive about getting filled.',
            [$lane]
        ),
        "{$prefix}_CRYPTO_LIMIT_BUFFER_BPS" => doc(
            "{$label} crypto marketable-limit buffer in basis points.",
            'Crypto keeps a separate buffer because the fill environment differs from equities.',
            [$lane, 'crypto']
        ),
        "{$prefix}_HIGH_SCORE_OVERRIDE_ENABLED" => doc(
            "{$label} high-score near-miss override switch.",
            'When enabled, exceptionally strong raw signals may survive slightly below-threshold fitness.',
            [$lane]
        ),
        "{$prefix}_HIGH_SCORE_OVERRIDE_MIN_SCORE" => doc(
            "{$label} minimum raw signal score for the high-score override.",
            'Signals below this raw score never qualify for the override.',
            [$lane]
        ),
        "{$prefix}_HIGH_SCORE_OVERRIDE_FITNESS_MARGIN" => doc(
            "{$label} allowed distance below the active fitness threshold for override candidates.",
            'Smaller values make the override stricter.',
            [$lane]
        ),
        "{$prefix}_EQUITY_NO_WEEKEND_CARRY_ENABLED" => doc(
            "{$label} Friday no-weekend-carry rule for equities.",
            'When enabled, Friday entries near the close are blocked and managed flattening happens before the weekend.',
            [$lane, 'market-hours', 'risk']
        ),
        "{$prefix}_EQUITY_FRIDAY_ENTRY_CUTOFF_MINUTES_BEFORE_CLOSE" => doc(
            "{$label} Friday equity entry cutoff window.",
            'New Friday equity entries are blocked inside this many minutes before the regular close.',
            [$lane, 'market-hours']
        ),
        "{$prefix}_EQUITY_FRIDAY_FLATTEN_MINUTES_BEFORE_CLOSE" => doc(
            "{$label} Friday equity flatten window.",
            'Managed equity positions are flattened inside this many minutes before the regular close.',
            [$lane, 'market-hours']
        ),
        "{$prefix}_EQUITY_BROKER_ID" => doc(
            "{$label} broker routing id for equities.",
            'This should match a supported execution adapter such as `alpaca_paper` or `alpaca_live`.',
            [$lane, 'routing']
        ),
        "{$prefix}_CRYPTO_BROKER_ID" => doc(
            "{$label} broker routing id for crypto.",
            'This should match a supported execution adapter such as `alpaca_paper` or `alpaca_live`.',
            [$lane, 'routing']
        ),
        "{$prefix}_ALLOWED_STRATEGIES" => doc(
            "{$label} strategy allowlist.",
            'Only strategies listed here may route orders for this lane.',
            [$lane, 'critical']
        ),
    ];

    if ($isLive) {
        $docs["{$prefix}_ACTIVATION_ACK"] = doc(
            'Explicit live activation acknowledgement token.',
            'This must match the approved acknowledgement value before live trading is considered intentionally armed.',
            ['live', 'critical']
        );
        $docs["{$prefix}_ALLOWED_PAPER_DIFFERENCES"] = doc(
            'Named list of reviewed live-vs-paper differences.',
            'Leave this empty for true same-as-paper behavior. If you intentionally allow a drift, list the exact validator name such as `execution_default_notional_usd` or `crypto_momentum_min_signal_score` or config load should fail closed.',
            ['live', 'critical']
        );
    }

    return $docs;
}

function glossarySections(): array
{
    return [
        section('runtime-core', 'Runtime Core', 'Mode labels, timezones, and process-level defaults.', [
            'CENTAUR_MODE',
            'CENTAUR_ENVIRONMENT',
            'CENTAUR_ENV',
            'CENTAUR_TIMEZONE',
            'MARKET_TIMEZONE',
            'LOG_LEVEL',
        ], 'core'),
        section('control-loop', 'Control Loop', 'Scheduler knobs and control-tick timing.', [
            'CONTROL_TICK_INTERVAL_SECONDS',
            'CONTROL_MAX_TICK_RUNTIME_SECONDS',
            'CONTROL_ENABLE_PROFILING',
            'CONTROL_REFRESH_DASHBOARD_SNAPSHOT',
            'CONTROL_LOCK_NAME',
        ], 'core'),
        section('storage-cost', 'Storage And Cost', 'Database routing, schemas, and API spend guardrails.', [
            'OPERATIONS_DB_BACKEND',
            'CORE_POSTGRES_SCHEMA',
            'PAPER_POSTGRES_SCHEMA',
            'LIVE_POSTGRES_SCHEMA',
            'POSTGRES_SCHEMA',
            'USAGE_LEDGER_DB_PATH',
            'API_DAILY_COST_WARNING_USD',
            'API_DAILY_COST_LIMIT_USD',
            'POSTGRES_HOST',
            'POSTGRES_PORT',
            'POSTGRES_DB',
            'POSTGRES_USER',
            'POSTGRES_PASSWORD',
            'POSTGRES_SSLMODE',
            'DATABASE_URL',
        ], 'core'),
        section('gemini', 'Gemini', 'LLM adapter settings and cost accounting.', [
            'GEMINI_API_KEY',
            'GEMINI_API_BASE_URL',
            'GEMINI_MODEL',
            'GEMINI_ANALYSIS_ENABLED',
            'GEMINI_REQUEST_TIMEOUT_SECONDS',
            'GEMINI_ANALYSIS_CANDIDATE_LIMIT',
            'GEMINI_MAX_OUTPUT_TOKENS',
            'GEMINI_INPUT_COST_PER_MILLION_TOKENS_USD',
            'GEMINI_OUTPUT_COST_PER_MILLION_TOKENS_USD',
        ], 'core'),
        section('shadow', 'Shadow Research', 'Counterfactual proposal generation and shared strategy defaults.', [
            'SHADOW_ENABLED',
            'SHADOW_PROPOSAL_LIMIT',
            'SHADOW_PROPOSAL_COOLDOWN_MINUTES',
            'SHADOW_MIN_OPPORTUNITY_SCORE',
            'SHADOW_STOP_LOSS_PCT',
            'SHADOW_TARGET_MULTIPLE',
            'SHADOW_CHECKPOINT_WINDOWS',
            'SHADOW_PROFIT_TARGET_LADDER_PCT',
            'SHADOW_EXECUTION_SPREAD_BPS',
            'SHADOW_ENTRY_SLIPPAGE_BPS',
            'SHADOW_EXIT_SLIPPAGE_BPS',
            'SHADOW_FIXED_ROUND_TRIP_COST_USD',
        ], 'core'),
        section('fitness', 'Fitness And Thresholds', 'Evidence gates that decide when a strategy is favored, tolerated, or suppressed.', [
            'STRATEGY_FITNESS_LOOKBACK_DAYS',
            'STRATEGY_FITNESS_MIN_CHECKPOINTS',
            'STRATEGY_ALLOCATION_MIN_CHECKPOINTS',
            'STRATEGY_ALLOCATION_FAVOR_THRESHOLD',
            'STRATEGY_ALLOCATION_SUPPRESS_THRESHOLD',
            'STRATEGY_ALLOCATION_CRYPTO_SUPPRESS_THRESHOLD',
            'STRATEGY_THRESHOLD_ADAPTIVE_ENABLED',
            'STRATEGY_THRESHOLD_ADAPTIVE_FLOOR',
            'STRATEGY_THRESHOLD_ADAPTIVE_CEILING',
            'STRATEGY_THRESHOLD_ADAPTIVE_BAND_WIDTH',
            'STRATEGY_THRESHOLD_ADAPTIVE_CLIFF_SAFETY_GAP',
            'STRATEGY_THRESHOLD_ADAPTIVE_MAX_STEP',
            'STRATEGY_THRESHOLD_ADAPTIVE_MIN_CONFIDENCE',
            'STRATEGY_THRESHOLD_ADAPTIVE_COOLDOWN_MINUTES',
            'STRATEGY_THRESHOLD_ADAPTIVE_MIN_TICKS',
        ], 'core'),
        section('market-data', 'Market Data And Replay', 'Discovery universes, backfill defaults, FX references, and optional providers.', [
            'ALPACA_DATA_BASE_URL',
            'ALPACA_STOCK_FEED',
            'ALPACA_REQUEST_TIMEOUT_SECONDS',
            'ALPACA_DATA_REQUEST_COST_USD',
            'ALPACA_CRYPTO_DATA_REQUEST_COST_USD',
            'ALPACA_WATCHLIST_SYMBOLS',
            'ALPACA_CRYPTO_LOCATION',
            'ALPACA_CRYPTO_SYMBOLS',
            'HISTORICAL_BACKFILL_DEFAULT_DAYS',
            'HISTORICAL_BACKFILL_DEFAULT_TIMEFRAME',
            'HISTORICAL_REPLAY_DEFAULT_DAYS',
            'HISTORICAL_REPLAY_DEFAULT_TIMEFRAME',
            'HISTORICAL_REPLAY_MAX_TIMESTAMPS',
            'DISCOVERY_EQUITY_SYMBOLS',
            'DISCOVERY_CRYPTO_SYMBOLS',
            'DISCOVERY_TARGET_COUNT',
            'ECB_REFERENCE_RATES_URL',
            'ECB_REQUEST_TIMEOUT_SECONDS',
            'ECB_REFERENCE_CACHE_MINUTES',
            'POLYGON_API_KEY',
            'POLYGON_REQUEST_COST_USD',
            'NEWS_API_KEY',
            'NEWS_API_REQUEST_COST_USD',
        ], 'core'),
        section('integrations', 'Integrations And Secrets', 'Reserved shared secrets and scaffolded provider credentials.', [
            'APP_SHARED_SECRET',
            'WEBHOOK_SECRET',
            'IG_API_KEY',
            'IG_USERNAME',
            'IG_PASSWORD',
            'IG_ACCOUNT_TYPE',
            'IG_ACCOUNT_NUMBER',
            'IG_BASE_URL',
            'IG_REQUEST_TIMEOUT_SECONDS',
            'IG_MIN_BET_PER_POINT_GBP',
            'IG_EPIC_OVERRIDES',
            'IG_REQUEST_COST_USD',
        ], 'core'),
        section('paper-broker', 'Paper Broker', 'Alpaca Paper credentials and broker endpoint settings.', [
            'ALPACA_API_KEY',
            'ALPACA_SECRET_KEY',
            'ALPACA_BASE_URL',
            'ALPACA_REQUEST_COST_USD',
        ], 'paper'),
        section('paper-execution', 'Paper Execution', 'The active proving lane: micro notional, bounded slots, and hard protections.', [
            'PAPER_EXECUTION_ENABLED',
            'PAPER_EXECUTION_KILL_SWITCH',
            'PAPER_EXECUTION_REQUIRE_MARKET_OPEN',
            'PAPER_EXECUTION_EQUITY_ONLY',
            'PAPER_EXECUTION_MAX_ORDERS_PER_TICK',
            'PAPER_EXECUTION_MAX_OPEN_POSITIONS',
            'PAPER_EXECUTION_DEFAULT_NOTIONAL_USD',
            'PAPER_EXECUTION_MAX_DAILY_DRAWDOWN_USD',
            'PAPER_EXECUTION_STALE_ORDER_MINUTES',
            'PAPER_EXECUTION_MIN_PROJECTED_GAIN_PCT',
            'PAPER_EXECUTION_CRYPTO_MIN_PROJECTED_GAIN_PCT',
            'PAPER_EXECUTION_PROFIT_CAPTURE_PCT',
            'PAPER_EXECUTION_LIMIT_BUFFER_BPS',
            'PAPER_EXECUTION_CRYPTO_LIMIT_BUFFER_BPS',
            'PAPER_EXECUTION_HIGH_SCORE_OVERRIDE_ENABLED',
            'PAPER_EXECUTION_HIGH_SCORE_OVERRIDE_MIN_SCORE',
            'PAPER_EXECUTION_HIGH_SCORE_OVERRIDE_FITNESS_MARGIN',
            'PAPER_EXECUTION_EQUITY_NO_WEEKEND_CARRY_ENABLED',
            'PAPER_EXECUTION_EQUITY_FRIDAY_ENTRY_CUTOFF_MINUTES_BEFORE_CLOSE',
            'PAPER_EXECUTION_EQUITY_FRIDAY_FLATTEN_MINUTES_BEFORE_CLOSE',
            'PAPER_EXECUTION_EQUITY_BROKER_ID',
            'PAPER_EXECUTION_CRYPTO_BROKER_ID',
            'PAPER_EXECUTION_ALLOWED_STRATEGIES',
            'PAPER_CRYPTO_MOMENTUM_STOP_LOSS_PCT',
            'PAPER_CRYPTO_MOMENTUM_TARGET_MULTIPLE',
            'PAPER_CRYPTO_MOMENTUM_MIN_SIGNAL_SCORE',
            'PAPER_CRYPTO_MOMENTUM_MIN_MOVEMENT_PCT',
            'PAPER_CRYPTO_MOMENTUM_MIN_DISCOVERY_SCORE',
            'PAPER_CRYPTO_MOMENTUM_MIN_TRADE_COUNT',
            'TRAILING_DRAWDOWN_OBSERVER_ENABLED',
            'TRAILING_DRAWDOWN_OBSERVER_PAPER_GIVEBACK_USD',
            'TRAILING_DRAWDOWN_OBSERVER_PAPER_GIVEBACK_PCT',
        ], 'paper'),
        section('live-broker', 'Live Broker', 'Alpaca Live credentials and funded-account endpoint settings.', [
            'ALPACA_LIVE_API_KEY',
            'ALPACA_LIVE_SECRET_KEY',
            'ALPACA_LIVE_BASE_URL',
            'ALPACA_LIVE_REQUEST_COST_USD',
        ], 'live'),
        section('live-execution', 'Live Execution', 'Same-as-paper follower controls plus extra live activation guards.', [
            'LIVE_EXECUTION_ENABLED',
            'LIVE_EXECUTION_KILL_SWITCH',
            'LIVE_EXECUTION_REQUIRE_MARKET_OPEN',
            'LIVE_EXECUTION_EQUITY_ONLY',
            'LIVE_EXECUTION_MAX_ORDERS_PER_TICK',
            'LIVE_EXECUTION_MAX_OPEN_POSITIONS',
            'LIVE_EXECUTION_DEFAULT_NOTIONAL_USD',
            'LIVE_EXECUTION_MAX_DAILY_DRAWDOWN_USD',
            'LIVE_EXECUTION_STALE_ORDER_MINUTES',
            'LIVE_EXECUTION_MIN_PROJECTED_GAIN_PCT',
            'LIVE_EXECUTION_CRYPTO_MIN_PROJECTED_GAIN_PCT',
            'LIVE_EXECUTION_PROFIT_CAPTURE_PCT',
            'LIVE_EXECUTION_LIMIT_BUFFER_BPS',
            'LIVE_EXECUTION_CRYPTO_LIMIT_BUFFER_BPS',
            'LIVE_EXECUTION_HIGH_SCORE_OVERRIDE_ENABLED',
            'LIVE_EXECUTION_HIGH_SCORE_OVERRIDE_MIN_SCORE',
            'LIVE_EXECUTION_HIGH_SCORE_OVERRIDE_FITNESS_MARGIN',
            'LIVE_EXECUTION_EQUITY_NO_WEEKEND_CARRY_ENABLED',
            'LIVE_EXECUTION_EQUITY_FRIDAY_ENTRY_CUTOFF_MINUTES_BEFORE_CLOSE',
            'LIVE_EXECUTION_EQUITY_FRIDAY_FLATTEN_MINUTES_BEFORE_CLOSE',
            'LIVE_EXECUTION_EQUITY_BROKER_ID',
            'LIVE_EXECUTION_CRYPTO_BROKER_ID',
            'LIVE_EXECUTION_ALLOWED_STRATEGIES',
            'LIVE_EXECUTION_ACTIVATION_ACK',
            'LIVE_EXECUTION_ALLOWED_PAPER_DIFFERENCES',
            'LIVE_CRYPTO_MOMENTUM_STOP_LOSS_PCT',
            'LIVE_CRYPTO_MOMENTUM_TARGET_MULTIPLE',
            'LIVE_CRYPTO_MOMENTUM_MIN_SIGNAL_SCORE',
            'LIVE_CRYPTO_MOMENTUM_MIN_MOVEMENT_PCT',
            'LIVE_CRYPTO_MOMENTUM_MIN_DISCOVERY_SCORE',
            'LIVE_CRYPTO_MOMENTUM_MIN_TRADE_COUNT',
            'TRAILING_DRAWDOWN_OBSERVER_LIVE_GIVEBACK_USD',
            'TRAILING_DRAWDOWN_OBSERVER_LIVE_GIVEBACK_PCT',
        ], 'live'),
    ];
}

function buildGlossarySections(array $sections, array $templateEntries, array $glossaryDocs): array
{
    $usedKeys = [];
    $renderSections = [];

    foreach ($sections as $section) {
        $rows = [];
        foreach ($section['keys'] as $key) {
            if (!isset($templateEntries[$key])) {
                continue;
            }

            $usedKeys[$key] = true;
            $rows[] = buildGlossaryRow($templateEntries[$key], $glossaryDocs[$key] ?? fallbackDoc($key), $section['scope']);
        }

        if ($rows !== []) {
            $section['rows'] = $rows;
            $section['count'] = count($rows);
            $renderSections[] = $section;
        }
    }

    $missing = [];
    foreach ($templateEntries as $key => $entry) {
        if (isset($usedKeys[$key])) {
            continue;
        }
        $missing[] = buildGlossaryRow($entry, $glossaryDocs[$key] ?? fallbackDoc($key), 'core');
    }

    if ($missing !== []) {
        $renderSections[] = [
            'id' => 'uncatalogued',
            'title' => 'Uncatalogued',
            'description' => 'Template keys not yet assigned to a richer section.',
            'scope' => 'core',
            'rows' => $missing,
            'count' => count($missing),
        ];
    }

    return $renderSections;
}

function buildGlossarySummary(array $sections): array
{
    $total = 0;
    $core = 0;
    $paper = 0;
    $live = 0;

    foreach ($sections as $section) {
        $count = (int) ($section['count'] ?? 0);
        $total += $count;
        if (($section['scope'] ?? 'core') === 'paper') {
            $paper += $count;
            continue;
        }
        if (($section['scope'] ?? 'core') === 'live') {
            $live += $count;
            continue;
        }
        $core += $count;
    }

    return [
        'total' => $total,
        'core' => $core,
        'paper' => $paper,
        'live' => $live,
        'sections' => count($sections),
    ];
}

function buildGlossaryRow(array $entry, array $doc, string $scope): array
{
    $default = (string) ($entry['default'] ?? '');
    $chips = array_values(array_unique(array_merge([$scope], $doc['chips'] ?? [])));

    return [
        'key' => $entry['key'],
        'default' => $default,
        'default_label' => $default === '' ? 'empty' : $default,
        'line' => (int) $entry['line'],
        'summary' => $doc['summary'],
        'detail' => $doc['detail'],
        'chips' => $chips,
        'scope' => $scope,
        'search' => strtolower(
            implode(' ', [
                $entry['key'],
                $scope,
                $doc['summary'],
                $doc['detail'],
                implode(' ', $chips),
            ])
        ),
    ];
}

function doc(string $summary, string $detail = '', array $chips = []): array
{
    return [
        'summary' => $summary,
        'detail' => $detail,
        'chips' => $chips,
    ];
}

function fallbackDoc(string $key): array
{
    return doc(
        'Template setting included in `.env.example`.',
        "This key is present in the template but does not yet have a custom glossary note. Review the runtime loader before changing it: `{$key}`.",
        ['needs-doc']
    );
}

function section(string $id, string $title, string $description, array $keys, string $scope): array
{
    return [
        'id' => $id,
        'title' => $title,
        'description' => $description,
        'keys' => $keys,
        'scope' => $scope,
    ];
}

function escapeHtml(string $value): string
{
    return htmlspecialchars($value, ENT_QUOTES, 'UTF-8');
}

function formatScopeLabel(string $scope): string
{
    return match ($scope) {
        'paper' => 'Paper',
        'live' => 'Live',
        default => 'Core',
    };
}
?>
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Project Centaur Glossary</title>
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
      --blue: #3867d6;
      --rose: #c94b5f;
      --green: #258b57;
      --shadow: 0 16px 40px rgba(18, 31, 32, 0.08);
    }

    * {
      box-sizing: border-box;
    }

    [hidden] {
      display: none !important;
    }

    html {
      scroll-behavior: smooth;
    }

    body {
      margin: 0;
      background:
        linear-gradient(180deg, rgba(15, 139, 141, 0.08), rgba(244, 247, 245, 0) 34rem),
        var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    a {
      color: inherit;
    }

    button,
    input {
      font: inherit;
    }

    .shell {
      width: min(1460px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0 40px;
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

    .subtitle {
      margin: 10px 0 0;
      color: var(--muted);
      font-size: 15px;
      line-height: 1.55;
      max-width: 66ch;
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

    .button:hover,
    .button.active {
      border-color: rgba(15, 139, 141, 0.45);
    }

    .button.primary {
      background: var(--teal);
      border-color: var(--teal);
      color: white;
    }

    .stack {
      display: grid;
      gap: 18px;
    }

    .hero-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.3fr) minmax(320px, 0.88fr);
      gap: 18px;
    }

    .panel {
      background: rgba(255, 255, 255, 0.92);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
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

    .panel-body {
      padding: 16px;
    }

    .lede {
      margin: 0;
      color: var(--muted);
      line-height: 1.6;
    }

    .callout {
      margin-top: 14px;
      padding: 14px 16px;
      border: 1px solid rgba(15, 139, 141, 0.16);
      border-radius: 8px;
      background: linear-gradient(135deg, rgba(15, 139, 141, 0.08), rgba(56, 103, 214, 0.05));
      color: var(--ink);
      line-height: 1.55;
    }

    .stat-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }

    .stat {
      min-height: 110px;
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 14px;
      box-shadow: 0 8px 22px rgba(18, 31, 32, 0.05);
    }

    .stat-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    .stat-value {
      margin-top: 12px;
      font-size: clamp(22px, 2.25vw, 34px);
      font-weight: 900;
      line-height: 1;
    }

    .stat-detail {
      margin-top: 8px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.4;
    }

    .filters {
      display: grid;
      gap: 14px;
    }

    .search-input {
      width: 100%;
      min-height: 46px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: white;
      color: var(--ink);
      padding: 10px 14px;
      font-size: 15px;
    }

    .search-input:focus {
      outline: 2px solid rgba(15, 139, 141, 0.18);
      border-color: rgba(15, 139, 141, 0.45);
    }

    .scope-buttons,
    .jump-links {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }

    .jump-link {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: white;
      padding: 0 12px;
      text-decoration: none;
      font-weight: 760;
      color: var(--ink);
    }

    .jump-link:hover {
      border-color: rgba(15, 139, 141, 0.45);
    }

    .jump-count {
      color: var(--muted);
      font-size: 12px;
      font-weight: 800;
    }

    .section-note {
      margin: 0;
      color: var(--muted);
      line-height: 1.55;
      padding: 16px 16px 0;
    }

    .settings-list {
      display: grid;
      gap: 14px;
      padding: 16px;
    }

    .setting {
      border: 1px solid var(--line);
      border-radius: 8px;
      background: rgba(255, 255, 255, 0.88);
      padding: 14px;
      display: grid;
      gap: 12px;
    }

    .setting-top {
      display: flex;
      justify-content: space-between;
      align-items: start;
      gap: 18px;
    }

    .setting-title {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      text-decoration: none;
      font-weight: 900;
      font-size: 15px;
      overflow-wrap: anywhere;
    }

    .setting-title code {
      font-size: 14px;
    }

    .setting-summary,
    .setting-detail {
      margin: 8px 0 0;
      color: var(--muted);
      line-height: 1.55;
    }

    .setting-detail {
      font-size: 14px;
    }

    .setting-meta {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
    }

    .meta-chip {
      display: inline-flex;
      align-items: center;
      min-height: 26px;
      border-radius: 999px;
      padding: 4px 10px;
      background: var(--surface-2);
      color: var(--teal-dark);
      font-size: 11px;
      font-weight: 850;
      letter-spacing: 0.02em;
      text-transform: uppercase;
    }

    .meta-chip.scope-paper {
      background: rgba(56, 103, 214, 0.09);
      color: var(--blue);
    }

    .meta-chip.scope-live {
      background: rgba(201, 75, 95, 0.09);
      color: var(--rose);
    }

    .meta-chip.scope-core {
      background: rgba(15, 139, 141, 0.10);
      color: var(--teal-dark);
    }

    .setting-foot {
      display: grid;
      gap: 10px;
    }

    .default-box {
      display: inline-grid;
      gap: 6px;
      width: fit-content;
      max-width: 100%;
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 8px;
      background: #f8fbf9;
    }

    .default-label {
      color: var(--muted);
      font-size: 11px;
      font-weight: 850;
      letter-spacing: 0.06em;
      text-transform: uppercase;
    }

    code {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
      overflow-wrap: anywhere;
    }

    .results-note {
      color: var(--muted);
      font-size: 13px;
    }

    .empty-state {
      margin: 0;
      padding: 18px 16px;
      color: var(--muted);
    }

    @media (max-width: 1100px) {
      .hero-grid {
        grid-template-columns: 1fr;
      }
    }

    @media (max-width: 860px) {
      .shell {
        width: min(100%, calc(100% - 24px));
      }

      .topbar {
        flex-direction: column;
        align-items: stretch;
      }

      .toolbar {
        justify-content: stretch;
      }

      .button {
        flex: 1 1 auto;
      }

      .setting-top {
        grid-template-columns: 1fr;
        display: grid;
      }

      .setting-meta {
        justify-content: flex-start;
      }

      .stat-grid {
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
        <h1>Config Glossary</h1>
        <p class="subtitle">Developer-style notes for every setting currently defined in `.env.example`, grouped by runtime area and presented without exposing live secrets from the real `.env`.</p>
      </div>
      <div class="toolbar">
        <a class="button primary" href="/glossary.php">Glossary</a>
        <a class="button" href="/dashboard.php">Dashboard</a>
        <a class="button" href="/">Slot Compounding</a>
      </div>
    </header>

    <div class="stack">
      <section class="hero-grid">
        <article class="panel">
          <div class="panel-head">
            <div class="panel-title">What This Page Covers</div>
            <span class="badge">Template driven</span>
          </div>
          <div class="panel-body">
            <p class="lede">This glossary reads the checked-in `.env.example` file, then layers human explanations over each key. That keeps the page honest about what exists in the template while avoiding the risk of dumping real local secrets into the browser.</p>
            <div class="callout">
              Use the search box to jump by variable name, behavior, or keyword. Scope filters let you isolate core runtime settings from the paper and live execution lanes.
            </div>
          </div>
        </article>

        <article class="panel">
          <div class="panel-head">
            <div class="panel-title">Quick Read</div>
            <span class="badge">At a glance</span>
          </div>
          <div class="panel-body">
            <div class="stat-grid">
              <div class="stat">
                <div class="stat-label">Template Keys</div>
                <div class="stat-value"><?= escapeHtml((string) $summary['total']) ?></div>
                <div class="stat-detail">Every variable parsed from `.env.example`.</div>
              </div>
              <div class="stat">
                <div class="stat-label">Core Settings</div>
                <div class="stat-value"><?= escapeHtml((string) $summary['core']) ?></div>
                <div class="stat-detail">Mode, control, research, storage, and provider settings.</div>
              </div>
              <div class="stat">
                <div class="stat-label">Paper Lane</div>
                <div class="stat-value"><?= escapeHtml((string) $summary['paper']) ?></div>
                <div class="stat-detail">Active proving-lane broker and execution controls.</div>
              </div>
              <div class="stat">
                <div class="stat-label">Live Lane</div>
                <div class="stat-value"><?= escapeHtml((string) $summary['live']) ?></div>
                <div class="stat-detail">Follower-lane controls guarded by extra activation checks.</div>
              </div>
            </div>
          </div>
        </article>
      </section>

      <section class="panel">
        <div class="panel-head">
          <div class="panel-title">Find A Setting</div>
          <span id="results-note" class="results-note">Showing all sections</span>
        </div>
        <div class="panel-body filters">
          <input id="search-input" class="search-input" type="search" placeholder="Search by variable, behavior, provider, risk gate, or keyword">
          <div class="scope-buttons" role="group" aria-label="Filter by scope">
            <button type="button" class="button active" data-filter="all">All</button>
            <button type="button" class="button" data-filter="core">Core</button>
            <button type="button" class="button" data-filter="paper">Paper</button>
            <button type="button" class="button" data-filter="live">Live</button>
          </div>
          <div class="jump-links" aria-label="Jump to section">
            <?php foreach ($renderSections as $section): ?>
              <a class="jump-link" href="#<?= escapeHtml($section['id']) ?>" data-jump-scope="<?= escapeHtml($section['scope']) ?>">
                <span><?= escapeHtml($section['title']) ?></span>
                <span class="jump-count"><?= escapeHtml((string) $section['count']) ?></span>
              </a>
            <?php endforeach; ?>
          </div>
        </div>
      </section>

      <?php foreach ($renderSections as $section): ?>
        <section id="<?= escapeHtml($section['id']) ?>" class="panel glossary-section" data-section-scope="<?= escapeHtml($section['scope']) ?>">
          <div class="panel-head">
            <div class="panel-title"><?= escapeHtml($section['title']) ?></div>
            <span class="badge section-badge"><?= escapeHtml((string) $section['count']) ?> settings</span>
          </div>
          <p class="section-note"><?= escapeHtml($section['description']) ?></p>
          <div class="settings-list">
            <?php foreach ($section['rows'] as $row): ?>
              <article
                id="<?= escapeHtml($row['key']) ?>"
                class="setting glossary-row"
                data-scope="<?= escapeHtml($row['scope']) ?>"
                data-search="<?= escapeHtml($row['search']) ?>"
              >
                <div class="setting-top">
                  <div>
                    <a class="setting-title" href="#<?= escapeHtml($row['key']) ?>">
                      <code><?= escapeHtml($row['key']) ?></code>
                    </a>
                    <p class="setting-summary"><?= escapeHtml($row['summary']) ?></p>
                  </div>
                  <div class="setting-meta">
                    <span class="meta-chip scope-<?= escapeHtml($row['scope']) ?>"><?= escapeHtml(formatScopeLabel($row['scope'])) ?></span>
                    <?php foreach ($row['chips'] as $chip): ?>
                      <?php if ($chip === $row['scope']) { continue; } ?>
                      <span class="meta-chip"><?= escapeHtml(str_replace('_', ' ', $chip)) ?></span>
                    <?php endforeach; ?>
                    <span class="meta-chip">line <?= escapeHtml((string) $row['line']) ?></span>
                  </div>
                </div>
                <div class="setting-foot">
                  <div class="default-box">
                    <span class="default-label">Template default</span>
                    <code><?= escapeHtml($row['default_label']) ?></code>
                  </div>
                  <?php if ($row['detail'] !== ''): ?>
                    <p class="setting-detail"><?= escapeHtml($row['detail']) ?></p>
                  <?php endif; ?>
                </div>
              </article>
            <?php endforeach; ?>
          </div>
        </section>
      <?php endforeach; ?>
    </div>
  </main>

  <script>
    const searchInput = document.getElementById("search-input");
    const filterButtons = Array.from(document.querySelectorAll("[data-filter]"));
    const jumpLinks = Array.from(document.querySelectorAll("[data-jump-scope]"));
    const rows = Array.from(document.querySelectorAll(".glossary-row"));
    const sections = Array.from(document.querySelectorAll(".glossary-section"));
    const resultsNote = document.getElementById("results-note");

    let activeFilter = "all";

    function updateResults() {
      const query = (searchInput.value || "").trim().toLowerCase();
      let visibleRows = 0;

      rows.forEach((row) => {
        const matchesQuery = query === "" || (row.dataset.search || "").includes(query);
        const matchesScope = activeFilter === "all" || row.dataset.scope === activeFilter;
        const visible = matchesQuery && matchesScope;
        row.hidden = !visible;
        if (visible) {
          visibleRows += 1;
        }
      });

      sections.forEach((section) => {
        const visibleInSection = section.querySelectorAll(".glossary-row:not([hidden])").length;
        section.hidden = visibleInSection === 0;
        const badge = section.querySelector(".section-badge");
        if (badge) {
          badge.textContent = `${visibleInSection} settings`;
        }
      });

      jumpLinks.forEach((link) => {
        const targetId = link.getAttribute("href")?.slice(1);
        const target = targetId ? document.getElementById(targetId) : null;
        link.hidden = !target || target.hidden;
      });

      const queryNote = query ? ` matching "${query}"` : "";
      const scopeNote = activeFilter === "all" ? "all scopes" : `${activeFilter} scope`;
      resultsNote.textContent = `${visibleRows} settings shown across ${scopeNote}${queryNote}`;
    }

    filterButtons.forEach((button) => {
      button.addEventListener("click", () => {
        activeFilter = button.dataset.filter || "all";
        filterButtons.forEach((candidate) => {
          candidate.classList.toggle("active", candidate === button);
        });
        updateResults();
      });
    });

    searchInput.addEventListener("input", updateResults);
    updateResults();
  </script>
</body>
</html>

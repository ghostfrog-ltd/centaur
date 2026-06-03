from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_TRADING212_UK_EQUITY_SYMBOLS = (
    "VOD,SHEL,BARC,HSBA,BP,LLOY,AZN,GSK,ULVR,REL,"
    "RIO,GLEN,BATS,DGE,NG,TSCO,RR,LSEG,PRU,IMB,"
    "BA,EXPN,AAL,ANTO,AV,III,LAND,SGE,SMIN,SVT"
)
DEFAULT_TRADING212_UK_PRICE_SEED_SYMBOLS = (
    "VOD,SHEL,BP,BARC,HSBA,LLOY,AZN,GSK,ULVR,REL,"
    "RIO,GLEN,BATS,DGE,NG,TSCO,RR,LSEG,BA,SGE"
)
DEFAULT_NASDAQ_100_SYMBOLS = (
    "AAPL,ABNB,ADBE,ADI,ADP,ADSK,AEP,ALNY,AMAT,AMD,AMGN,AMZN,APP,ARM,ASML,"
    "AVGO,AXON,BKNG,BKR,CCEP,CDNS,CEG,CHTR,CMCSA,COST,CPRT,CRWD,CSCO,CSGP,CSX,"
    "CTAS,CTSH,DASH,DDOG,DXCM,EA,EXC,FANG,FAST,FER,FTNT,GEHC,GILD,GOOG,GOOGL,"
    "HON,IDXX,INSM,INTC,INTU,ISRG,KDP,KHC,KLAC,LIN,LRCX,MAR,MCHP,MDLZ,MELI,"
    "META,MNST,MPWR,MRVL,MSFT,MSTR,MU,NFLX,NVDA,NXPI,ODFL,ORLY,PANW,PAYX,PCAR,"
    "PDD,PEP,PLTR,PYPL,QCOM,REGN,ROP,ROST,SBUX,SHOP,SNPS,STX,TEAM,TMUS,TRI,"
    "TSLA,TTWO,TXN,VRSK,VRTX,WBD,WDAY,WDC,WMT,XEL,ZS"
)
DEFAULT_DISCOVERY_CRYPTO_SYMBOLS = (
    "BTC/USD,ETH/USD,SOL/USD,XRP/USD,DOGE/USD,"
    "LTC/USD,BCH/USD,LINK/USD,AVAX/USD,UNI/USD,AAVE/USD"
)


@dataclass(frozen=True, slots=True)
class SourcePricing:
    source: str
    cost_per_request_usd: float = 0.0
    input_cost_per_million_units_usd: float = 0.0
    output_cost_per_million_units_usd: float = 0.0


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    centaur_mode: str
    centaur_environment: str
    env_name: str
    centaur_timezone: str
    market_timezone: str
    log_level: str
    control_tick_interval_seconds: int
    control_max_tick_runtime_seconds: int
    control_enable_profiling: bool
    control_lock_name: str
    operations_db_backend_preference: str
    usage_ledger_db_path: Path
    database_url: str
    database_url_source: str
    postgres_schema: str
    postgres_core_schema: str
    postgres_paper_schema: str
    postgres_live_schema: str
    api_daily_cost_warning_usd: float
    api_daily_cost_limit_usd: float
    slack_alerts_enabled: bool
    slack_webhook_url: str
    slack_alert_dedupe_minutes: int
    slack_request_timeout_seconds: int
    slack_hourly_status_enabled: bool
    slack_hourly_status_interval_minutes: int
    live_equity_pdt_review_reminders_enabled: bool
    live_equity_pdt_review_reminder_start_date: str
    live_equity_pdt_review_reminder_interval_minutes: int
    alpaca_api_key: str
    alpaca_secret_key: str
    alpaca_base_url: str
    alpaca_data_base_url: str
    alpaca_live_api_key: str
    alpaca_live_secret_key: str
    alpaca_live_base_url: str
    alpaca_stock_feed: str
    alpaca_request_timeout_seconds: int
    alpaca_watchlist_symbols: tuple[str, ...]
    alpaca_crypto_location: str
    alpaca_crypto_symbols: tuple[str, ...]
    historical_backfill_default_days: int
    historical_backfill_default_timeframe: str
    historical_replay_default_days: int
    historical_replay_default_timeframe: str
    historical_replay_max_timestamps: int
    discovery_equity_symbols: tuple[str, ...]
    discovery_crypto_symbols: tuple[str, ...]
    discovery_target_count: int
    ecb_reference_rates_url: str
    ecb_request_timeout_seconds: int
    ecb_reference_cache_minutes: int
    gemini_api_key: str
    gemini_api_base_url: str
    gemini_model: str
    gemini_analysis_enabled: bool
    gemini_request_timeout_seconds: int
    gemini_analysis_candidate_limit: int
    gemini_max_output_tokens: int
    shadow_enabled: bool
    shadow_proposal_limit: int
    shadow_proposal_cooldown_minutes: int
    shadow_min_opportunity_score: float
    shadow_stop_loss_pct: float
    shadow_target_multiple: float
    crypto_momentum_stop_loss_pct: float
    crypto_momentum_target_multiple: float
    crypto_momentum_min_signal_score: float
    crypto_momentum_min_movement_pct: float
    crypto_momentum_max_movement_pct: float
    crypto_momentum_min_discovery_score: float
    crypto_momentum_min_trade_count: int
    crypto_momentum_min_volume_gbp: float
    crypto_momentum_max_spread_pct: float
    paper_crypto_momentum_stop_loss_pct: float
    paper_crypto_momentum_target_multiple: float
    paper_crypto_momentum_min_signal_score: float
    paper_crypto_momentum_min_movement_pct: float
    paper_crypto_momentum_max_movement_pct: float
    paper_crypto_momentum_min_discovery_score: float
    paper_crypto_momentum_min_trade_count: int
    paper_crypto_momentum_min_volume_gbp: float
    paper_crypto_momentum_max_spread_pct: float
    live_crypto_momentum_stop_loss_pct: float
    live_crypto_momentum_target_multiple: float
    live_crypto_momentum_min_signal_score: float
    live_crypto_momentum_min_movement_pct: float
    live_crypto_momentum_max_movement_pct: float
    live_crypto_momentum_min_discovery_score: float
    live_crypto_momentum_min_trade_count: int
    live_crypto_momentum_min_volume_gbp: float
    live_crypto_momentum_max_spread_pct: float
    shadow_checkpoint_windows: tuple[str, ...]
    shadow_profit_target_ladder_pct: tuple[float, ...]
    shadow_execution_spread_bps: float
    shadow_entry_slippage_bps: float
    shadow_exit_slippage_bps: float
    shadow_fixed_round_trip_cost_usd: float
    strategy_fitness_lookback_days: int
    strategy_fitness_min_checkpoints: int
    strategy_allocation_min_checkpoints: int
    strategy_allocation_favor_threshold: float
    strategy_allocation_suppress_threshold: float
    strategy_allocation_crypto_suppress_threshold: float
    strategy_threshold_adaptive_enabled: bool
    strategy_threshold_adaptive_floor: float
    strategy_threshold_adaptive_ceiling: float
    strategy_threshold_adaptive_band_width: float
    strategy_threshold_adaptive_cliff_safety_gap: float
    strategy_threshold_adaptive_max_step: float
    strategy_threshold_adaptive_min_confidence: str
    strategy_threshold_adaptive_cooldown_minutes: int
    strategy_threshold_adaptive_min_ticks: int
    paper_execution_enabled: bool
    paper_execution_kill_switch: bool
    paper_execution_require_market_open: bool
    paper_execution_equity_only: bool
    paper_execution_max_orders_per_tick: int
    paper_execution_max_open_positions: int
    paper_execution_default_notional_usd: float
    paper_execution_max_daily_drawdown_usd: float
    paper_execution_stale_order_minutes: int
    paper_execution_min_projected_gain_pct: float
    paper_execution_crypto_min_projected_gain_pct: float
    paper_execution_profit_capture_pct: float
    paper_execution_limit_buffer_bps: float
    paper_execution_crypto_limit_buffer_bps: float
    paper_execution_high_score_override_enabled: bool
    paper_execution_high_score_override_min_score: float
    paper_execution_high_score_override_fitness_margin: float
    paper_min_signal_score_to_trade: float
    paper_execution_equity_no_weekend_carry_enabled: bool
    paper_execution_equity_friday_entry_cutoff_minutes_before_close: int
    paper_execution_equity_friday_flatten_minutes_before_close: int
    trailing_drawdown_observer_enabled: bool
    trailing_drawdown_observer_paper_giveback_usd: float
    trailing_drawdown_observer_paper_giveback_pct: float
    trailing_drawdown_observer_live_giveback_usd: float
    trailing_drawdown_observer_live_giveback_pct: float
    paper_execution_equity_broker_id: str
    paper_execution_crypto_broker_id: str
    paper_execution_allowed_strategies: tuple[str, ...]
    live_execution_enabled: bool
    live_execution_kill_switch: bool
    live_execution_require_market_open: bool
    live_execution_equity_only: bool
    live_execution_max_orders_per_tick: int
    live_execution_max_open_positions: int
    live_execution_default_notional_usd: float
    live_execution_max_daily_drawdown_usd: float
    live_execution_stale_order_minutes: int
    live_execution_min_projected_gain_pct: float
    live_execution_crypto_min_projected_gain_pct: float
    live_execution_profit_capture_pct: float
    live_execution_limit_buffer_bps: float
    live_execution_crypto_limit_buffer_bps: float
    live_execution_high_score_override_enabled: bool
    live_execution_high_score_override_min_score: float
    live_execution_high_score_override_fitness_margin: float
    live_min_signal_score_to_trade: float
    live_execution_equity_no_weekend_carry_enabled: bool
    live_execution_equity_friday_entry_cutoff_minutes_before_close: int
    live_execution_equity_friday_flatten_minutes_before_close: int
    live_execution_equity_broker_id: str
    live_execution_crypto_broker_id: str
    live_execution_allowed_strategies: tuple[str, ...]
    live_execution_activation_ack: str
    live_execution_allowed_paper_differences: tuple[str, ...]
    ig_api_key: str
    ig_username: str
    ig_password: str
    ig_account_type: str
    ig_account_number: str
    ig_base_url: str
    ig_request_timeout_seconds: int
    ig_min_bet_per_point_gbp: float
    ig_epic_overrides: dict[str, str]
    trading212_paper_api_key: str
    trading212_paper_api_secret: str
    trading212_paper_base_url: str
    trading212_paper_request_timeout_seconds: int
    trading212_paper_primary_currency: str
    trading212_paper_market_timezone: str
    trading212_paper_market_open_time: str
    trading212_paper_market_close_time: str
    trading212_paper_equity_symbols: tuple[str, ...]
    trading212_paper_price_seed_symbols: tuple[str, ...]
    trading212_paper_market_data_provider: str
    trading212_paper_ticker_overrides: dict[str, str]
    trading212_paper_execution_enabled: bool
    trading212_paper_default_notional_native: float
    trading212_live_api_key: str
    trading212_live_api_secret: str
    trading212_live_base_url: str
    trading212_live_request_timeout_seconds: int
    trading212_live_primary_currency: str
    trading212_live_market_timezone: str
    trading212_live_market_open_time: str
    trading212_live_market_close_time: str
    trading212_live_equity_symbols: tuple[str, ...]
    trading212_live_market_data_provider: str
    trading212_live_ticker_overrides: dict[str, str]
    trading212_live_execution_enabled: bool
    trading212_live_default_notional_native: float
    gemini_api_configured: bool
    alpaca_api_configured: bool
    alpaca_live_api_configured: bool
    ig_api_configured: bool
    trading212_paper_api_configured: bool
    trading212_live_api_configured: bool
    postgres_configured: bool
    provider_pricing: dict[str, SourcePricing] = field(default_factory=dict)


def load_runtime_config() -> RuntimeConfig:
    load_dotenv(DEFAULT_ENV_PATH)

    usage_db_path = _resolve_project_path(
        os.getenv("USAGE_LEDGER_DB_PATH", ".runtime/centaur_usage.sqlite3")
    )
    database_url, database_url_source = _resolve_database_url()
    centaur_mode = _resolve_centaur_mode()
    centaur_environment = _resolve_centaur_environment()
    paper_crypto_momentum_stop_loss_pct = _parse_percent_control(
        os.getenv("PAPER_CRYPTO_MOMENTUM_STOP_LOSS_PCT")
        or os.getenv("CRYPTO_MOMENTUM_STOP_LOSS_PCT"),
        default=0.01,
    )
    paper_crypto_momentum_target_multiple = _parse_float(
        os.getenv("PAPER_CRYPTO_MOMENTUM_TARGET_MULTIPLE")
        or os.getenv("CRYPTO_MOMENTUM_TARGET_MULTIPLE"),
        default=2.0,
    )
    paper_crypto_momentum_min_signal_score = _parse_float(
        os.getenv("PAPER_CRYPTO_MOMENTUM_MIN_SIGNAL_SCORE")
        or os.getenv("CRYPTO_MOMENTUM_MIN_SIGNAL_SCORE"),
        default=60.0,
    )
    paper_crypto_momentum_min_movement_pct = _parse_float(
        os.getenv("PAPER_CRYPTO_MOMENTUM_MIN_MOVEMENT_PCT")
        or os.getenv("CRYPTO_MOMENTUM_MIN_MOVEMENT_PCT"),
        default=0.15,
    )
    paper_crypto_momentum_max_movement_pct = _parse_float(
        os.getenv("PAPER_CRYPTO_MOMENTUM_MAX_MOVEMENT_PCT")
        or os.getenv("CRYPTO_MOMENTUM_MAX_MOVEMENT_PCT"),
        default=2.5,
    )
    paper_crypto_momentum_min_discovery_score = _parse_float(
        os.getenv("PAPER_CRYPTO_MOMENTUM_MIN_DISCOVERY_SCORE")
        or os.getenv("CRYPTO_MOMENTUM_MIN_DISCOVERY_SCORE"),
        default=2.5,
    )
    paper_crypto_momentum_min_trade_count = _parse_int(
        os.getenv("PAPER_CRYPTO_MOMENTUM_MIN_TRADE_COUNT")
        or os.getenv("CRYPTO_MOMENTUM_MIN_TRADE_COUNT"),
        default=2,
    )
    paper_crypto_momentum_min_volume_gbp = _parse_float(
        os.getenv("PAPER_CRYPTO_MOMENTUM_MIN_VOLUME_GBP")
        or os.getenv("CRYPTO_MOMENTUM_MIN_VOLUME_GBP"),
        default=50_000.0,
    )
    paper_crypto_momentum_max_spread_pct = _parse_float(
        os.getenv("PAPER_CRYPTO_MOMENTUM_MAX_SPREAD_PCT")
        or os.getenv("CRYPTO_MOMENTUM_MAX_SPREAD_PCT"),
        default=0.25,
    )
    live_crypto_momentum_stop_loss_pct = _parse_percent_control(
        os.getenv("LIVE_CRYPTO_MOMENTUM_STOP_LOSS_PCT"),
        default=paper_crypto_momentum_stop_loss_pct,
    )
    live_crypto_momentum_target_multiple = _parse_float(
        os.getenv("LIVE_CRYPTO_MOMENTUM_TARGET_MULTIPLE"),
        default=paper_crypto_momentum_target_multiple,
    )
    live_crypto_momentum_min_signal_score = _parse_float(
        os.getenv("LIVE_CRYPTO_MOMENTUM_MIN_SIGNAL_SCORE"),
        default=paper_crypto_momentum_min_signal_score,
    )
    live_crypto_momentum_min_movement_pct = _parse_float(
        os.getenv("LIVE_CRYPTO_MOMENTUM_MIN_MOVEMENT_PCT"),
        default=paper_crypto_momentum_min_movement_pct,
    )
    live_crypto_momentum_max_movement_pct = _parse_float(
        os.getenv("LIVE_CRYPTO_MOMENTUM_MAX_MOVEMENT_PCT"),
        default=paper_crypto_momentum_max_movement_pct,
    )
    live_crypto_momentum_min_discovery_score = _parse_float(
        os.getenv("LIVE_CRYPTO_MOMENTUM_MIN_DISCOVERY_SCORE"),
        default=paper_crypto_momentum_min_discovery_score,
    )
    live_crypto_momentum_min_trade_count = _parse_int(
        os.getenv("LIVE_CRYPTO_MOMENTUM_MIN_TRADE_COUNT"),
        default=paper_crypto_momentum_min_trade_count,
    )
    live_crypto_momentum_min_volume_gbp = _parse_float(
        os.getenv("LIVE_CRYPTO_MOMENTUM_MIN_VOLUME_GBP"),
        default=paper_crypto_momentum_min_volume_gbp,
    )
    live_crypto_momentum_max_spread_pct = _parse_float(
        os.getenv("LIVE_CRYPTO_MOMENTUM_MAX_SPREAD_PCT"),
        default=paper_crypto_momentum_max_spread_pct,
    )
    active_crypto_momentum_is_live = centaur_environment == "live"
    paper_min_signal_score_to_trade = _parse_float(
        os.getenv("PAPER_MIN_SIGNAL_SCORE_TO_TRADE")
        or os.getenv("PAPER_EXECUTION_HIGH_SCORE_OVERRIDE_MIN_SCORE"),
        default=90.0,
    )
    live_min_signal_score_to_trade = _parse_float(
        os.getenv("LIVE_MIN_SIGNAL_SCORE_TO_TRADE")
        or os.getenv("LIVE_EXECUTION_HIGH_SCORE_OVERRIDE_MIN_SCORE"),
        default=90.0,
    )

    config = RuntimeConfig(
        centaur_mode=centaur_mode,
        centaur_environment=centaur_environment,
        env_name=os.getenv("CENTAUR_ENV", "development"),
        centaur_timezone=os.getenv("CENTAUR_TIMEZONE", "Europe/London"),
        market_timezone=os.getenv("MARKET_TIMEZONE", "America/New_York"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        control_tick_interval_seconds=_parse_int(
            os.getenv("CONTROL_TICK_INTERVAL_SECONDS"),
            default=60,
        ),
        control_max_tick_runtime_seconds=_parse_int(
            os.getenv("CONTROL_MAX_TICK_RUNTIME_SECONDS"),
            default=55,
        ),
        control_enable_profiling=_parse_bool(
            os.getenv("CONTROL_ENABLE_PROFILING"),
            default=True,
        ),
        control_lock_name=os.getenv("CONTROL_LOCK_NAME", "centaur_control_tick"),
        operations_db_backend_preference=_normalize_backend_preference(
            os.getenv("OPERATIONS_DB_BACKEND", "auto")
        ),
        usage_ledger_db_path=usage_db_path,
        database_url=database_url,
        database_url_source=database_url_source,
        postgres_schema=_normalize_postgres_schema(os.getenv("POSTGRES_SCHEMA", "")),
        postgres_core_schema=_normalize_postgres_schema(
            os.getenv("CORE_POSTGRES_SCHEMA", "core")
        ),
        postgres_paper_schema=_normalize_postgres_schema(
            os.getenv("PAPER_POSTGRES_SCHEMA", "paper")
        ),
        postgres_live_schema=_normalize_postgres_schema(
            os.getenv("LIVE_POSTGRES_SCHEMA", "live")
        ),
        api_daily_cost_warning_usd=_parse_float(
            os.getenv("API_DAILY_COST_WARNING_USD"),
            default=5.0,
        ),
        api_daily_cost_limit_usd=_parse_float(
            os.getenv("API_DAILY_COST_LIMIT_USD"),
            default=20.0,
        ),
        slack_alerts_enabled=_parse_bool(
            os.getenv("SLACK_ALERTS_ENABLED"),
            default=False,
        ),
        slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL", "").strip(),
        slack_alert_dedupe_minutes=_parse_int(
            os.getenv("SLACK_ALERT_DEDUPE_MINUTES"),
            default=360,
        ),
        slack_request_timeout_seconds=_parse_int(
            os.getenv("SLACK_REQUEST_TIMEOUT_SECONDS"),
            default=5,
        ),
        slack_hourly_status_enabled=_parse_bool(
            os.getenv("SLACK_HOURLY_STATUS_ENABLED"),
            default=True,
        ),
        slack_hourly_status_interval_minutes=_parse_int(
            os.getenv("SLACK_HOURLY_STATUS_INTERVAL_MINUTES"),
            default=60,
        ),
        live_equity_pdt_review_reminders_enabled=_parse_bool(
            os.getenv("LIVE_EQUITY_PDT_REVIEW_REMINDERS_ENABLED"),
            default=True,
        ),
        live_equity_pdt_review_reminder_start_date=os.getenv(
            "LIVE_EQUITY_PDT_REVIEW_REMINDER_START_DATE",
            "2026-06-04",
        ).strip(),
        live_equity_pdt_review_reminder_interval_minutes=_parse_int(
            os.getenv("LIVE_EQUITY_PDT_REVIEW_REMINDER_INTERVAL_MINUTES"),
            default=30,
        ),
        alpaca_api_key=os.getenv("ALPACA_API_KEY", "").strip(),
        alpaca_secret_key=os.getenv("ALPACA_SECRET_KEY", "").strip(),
        alpaca_base_url=os.getenv(
            "ALPACA_BASE_URL",
            "https://paper-api.alpaca.markets",
        ).strip(),
        alpaca_data_base_url=os.getenv(
            "ALPACA_DATA_BASE_URL",
            "https://data.alpaca.markets",
        ).strip(),
        alpaca_live_api_key=os.getenv("ALPACA_LIVE_API_KEY", "").strip(),
        alpaca_live_secret_key=os.getenv("ALPACA_LIVE_SECRET_KEY", "").strip(),
        alpaca_live_base_url=os.getenv(
            "ALPACA_LIVE_BASE_URL",
            "https://api.alpaca.markets",
        ).strip(),
        alpaca_stock_feed=(
            os.getenv("ALPACA_STOCK_FEED", "iex").strip().lower() or "iex"
        ),
        alpaca_request_timeout_seconds=_parse_int(
            os.getenv("ALPACA_REQUEST_TIMEOUT_SECONDS"),
            default=10,
        ),
        alpaca_watchlist_symbols=_parse_csv(
            os.getenv("ALPACA_WATCHLIST_SYMBOLS", DEFAULT_NASDAQ_100_SYMBOLS)
        ),
        alpaca_crypto_location=os.getenv("ALPACA_CRYPTO_LOCATION", "us").strip(),
        alpaca_crypto_symbols=_parse_csv(
            os.getenv("ALPACA_CRYPTO_SYMBOLS", DEFAULT_DISCOVERY_CRYPTO_SYMBOLS)
        ),
        historical_backfill_default_days=_parse_int(
            os.getenv("HISTORICAL_BACKFILL_DEFAULT_DAYS"),
            default=30,
        ),
        historical_backfill_default_timeframe=os.getenv(
            "HISTORICAL_BACKFILL_DEFAULT_TIMEFRAME",
            "1Min",
        ).strip(),
        historical_replay_default_days=_parse_int(
            os.getenv("HISTORICAL_REPLAY_DEFAULT_DAYS"),
            default=30,
        ),
        historical_replay_default_timeframe=os.getenv(
            "HISTORICAL_REPLAY_DEFAULT_TIMEFRAME",
            "1Hour",
        ).strip(),
        historical_replay_max_timestamps=_parse_int(
            os.getenv("HISTORICAL_REPLAY_MAX_TIMESTAMPS"),
            default=0,
        ),
        discovery_equity_symbols=_parse_csv(
            os.getenv(
                "DISCOVERY_EQUITY_SYMBOLS",
                DEFAULT_NASDAQ_100_SYMBOLS,
            )
        ),
        discovery_crypto_symbols=_parse_csv(
            os.getenv(
                "DISCOVERY_CRYPTO_SYMBOLS",
                DEFAULT_DISCOVERY_CRYPTO_SYMBOLS,
            )
        ),
        discovery_target_count=_parse_int(
            os.getenv("DISCOVERY_TARGET_COUNT"),
            default=6,
        ),
        ecb_reference_rates_url=os.getenv(
            "ECB_REFERENCE_RATES_URL",
            "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml",
        ).strip(),
        ecb_request_timeout_seconds=_parse_int(
            os.getenv("ECB_REQUEST_TIMEOUT_SECONDS"),
            default=10,
        ),
        ecb_reference_cache_minutes=_parse_int(
            os.getenv("ECB_REFERENCE_CACHE_MINUTES"),
            default=60,
        ),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_api_base_url=os.getenv(
            "GEMINI_API_BASE_URL",
            "https://generativelanguage.googleapis.com",
        ).strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-model-name"),
        gemini_analysis_enabled=_parse_bool(
            os.getenv("GEMINI_ANALYSIS_ENABLED"),
            default=True,
        ),
        gemini_request_timeout_seconds=_parse_int(
            os.getenv("GEMINI_REQUEST_TIMEOUT_SECONDS"),
            default=20,
        ),
        gemini_analysis_candidate_limit=_parse_int(
            os.getenv("GEMINI_ANALYSIS_CANDIDATE_LIMIT"),
            default=5,
        ),
        gemini_max_output_tokens=_parse_int(
            os.getenv("GEMINI_MAX_OUTPUT_TOKENS"),
            default=1200,
        ),
        shadow_enabled=_parse_bool(
            os.getenv("SHADOW_ENABLED"),
            default=True,
        ),
        shadow_proposal_limit=_parse_int(
            os.getenv("SHADOW_PROPOSAL_LIMIT"),
            default=3,
        ),
        shadow_proposal_cooldown_minutes=_parse_int(
            os.getenv("SHADOW_PROPOSAL_COOLDOWN_MINUTES"),
            default=60,
        ),
        shadow_min_opportunity_score=_parse_float(
            os.getenv("SHADOW_MIN_OPPORTUNITY_SCORE"),
            default=55.0,
        ),
        shadow_stop_loss_pct=_parse_percent_control(
            os.getenv("SHADOW_STOP_LOSS_PCT"),
            default=0.02,
        ),
        shadow_target_multiple=_parse_float(
            os.getenv("SHADOW_TARGET_MULTIPLE"),
            default=2.0,
        ),
        crypto_momentum_stop_loss_pct=(
            live_crypto_momentum_stop_loss_pct
            if active_crypto_momentum_is_live
            else paper_crypto_momentum_stop_loss_pct
        ),
        crypto_momentum_target_multiple=(
            live_crypto_momentum_target_multiple
            if active_crypto_momentum_is_live
            else paper_crypto_momentum_target_multiple
        ),
        crypto_momentum_min_signal_score=(
            live_crypto_momentum_min_signal_score
            if active_crypto_momentum_is_live
            else paper_crypto_momentum_min_signal_score
        ),
        crypto_momentum_min_movement_pct=(
            live_crypto_momentum_min_movement_pct
            if active_crypto_momentum_is_live
            else paper_crypto_momentum_min_movement_pct
        ),
        crypto_momentum_max_movement_pct=(
            live_crypto_momentum_max_movement_pct
            if active_crypto_momentum_is_live
            else paper_crypto_momentum_max_movement_pct
        ),
        crypto_momentum_min_discovery_score=(
            live_crypto_momentum_min_discovery_score
            if active_crypto_momentum_is_live
            else paper_crypto_momentum_min_discovery_score
        ),
        crypto_momentum_min_trade_count=(
            live_crypto_momentum_min_trade_count
            if active_crypto_momentum_is_live
            else paper_crypto_momentum_min_trade_count
        ),
        crypto_momentum_min_volume_gbp=(
            live_crypto_momentum_min_volume_gbp
            if active_crypto_momentum_is_live
            else paper_crypto_momentum_min_volume_gbp
        ),
        crypto_momentum_max_spread_pct=(
            live_crypto_momentum_max_spread_pct
            if active_crypto_momentum_is_live
            else paper_crypto_momentum_max_spread_pct
        ),
        paper_crypto_momentum_stop_loss_pct=paper_crypto_momentum_stop_loss_pct,
        paper_crypto_momentum_target_multiple=paper_crypto_momentum_target_multiple,
        paper_crypto_momentum_min_signal_score=paper_crypto_momentum_min_signal_score,
        paper_crypto_momentum_min_movement_pct=paper_crypto_momentum_min_movement_pct,
        paper_crypto_momentum_max_movement_pct=paper_crypto_momentum_max_movement_pct,
        paper_crypto_momentum_min_discovery_score=paper_crypto_momentum_min_discovery_score,
        paper_crypto_momentum_min_trade_count=paper_crypto_momentum_min_trade_count,
        paper_crypto_momentum_min_volume_gbp=paper_crypto_momentum_min_volume_gbp,
        paper_crypto_momentum_max_spread_pct=paper_crypto_momentum_max_spread_pct,
        live_crypto_momentum_stop_loss_pct=live_crypto_momentum_stop_loss_pct,
        live_crypto_momentum_target_multiple=live_crypto_momentum_target_multiple,
        live_crypto_momentum_min_signal_score=live_crypto_momentum_min_signal_score,
        live_crypto_momentum_min_movement_pct=live_crypto_momentum_min_movement_pct,
        live_crypto_momentum_max_movement_pct=live_crypto_momentum_max_movement_pct,
        live_crypto_momentum_min_discovery_score=live_crypto_momentum_min_discovery_score,
        live_crypto_momentum_min_trade_count=live_crypto_momentum_min_trade_count,
        live_crypto_momentum_min_volume_gbp=live_crypto_momentum_min_volume_gbp,
        live_crypto_momentum_max_spread_pct=live_crypto_momentum_max_spread_pct,
        shadow_checkpoint_windows=_parse_shadow_windows(
            os.getenv("SHADOW_CHECKPOINT_WINDOWS", "15m,1h,1d,7d")
        ),
        shadow_profit_target_ladder_pct=_parse_float_csv(
            os.getenv("SHADOW_PROFIT_TARGET_LADDER_PCT"),
            default=(1.25, 2.0, 3.0, 4.0, 6.0),
        ),
        shadow_execution_spread_bps=_parse_float(
            os.getenv("SHADOW_EXECUTION_SPREAD_BPS"),
            default=4.0,
        ),
        shadow_entry_slippage_bps=_parse_float(
            os.getenv("SHADOW_ENTRY_SLIPPAGE_BPS"),
            default=2.0,
        ),
        shadow_exit_slippage_bps=_parse_float(
            os.getenv("SHADOW_EXIT_SLIPPAGE_BPS"),
            default=2.0,
        ),
        shadow_fixed_round_trip_cost_usd=_parse_float(
            os.getenv("SHADOW_FIXED_ROUND_TRIP_COST_USD"),
            default=0.03,
        ),
        strategy_fitness_lookback_days=_parse_int(
            os.getenv("STRATEGY_FITNESS_LOOKBACK_DAYS"),
            default=0,
        ),
        strategy_fitness_min_checkpoints=_parse_int(
            os.getenv("STRATEGY_FITNESS_MIN_CHECKPOINTS"),
            default=1,
        ),
        strategy_allocation_min_checkpoints=_parse_int(
            os.getenv("STRATEGY_ALLOCATION_MIN_CHECKPOINTS"),
            default=2,
        ),
        strategy_allocation_favor_threshold=_parse_float(
            os.getenv("STRATEGY_ALLOCATION_FAVOR_THRESHOLD"),
            default=3.0,
        ),
        strategy_allocation_suppress_threshold=_parse_float(
            os.getenv("STRATEGY_ALLOCATION_SUPPRESS_THRESHOLD"),
            default=-5.0,
        ),
        strategy_allocation_crypto_suppress_threshold=_parse_float(
            os.getenv("STRATEGY_ALLOCATION_CRYPTO_SUPPRESS_THRESHOLD"),
            default=-6.2,
        ),
        strategy_threshold_adaptive_enabled=_parse_bool(
            os.getenv("STRATEGY_THRESHOLD_ADAPTIVE_ENABLED"),
            default=False,
        ),
        strategy_threshold_adaptive_floor=_parse_float(
            os.getenv("STRATEGY_THRESHOLD_ADAPTIVE_FLOOR"),
            default=-6.0,
        ),
        strategy_threshold_adaptive_ceiling=_parse_float(
            os.getenv("STRATEGY_THRESHOLD_ADAPTIVE_CEILING"),
            default=-5.0,
        ),
        strategy_threshold_adaptive_band_width=_parse_float(
            os.getenv("STRATEGY_THRESHOLD_ADAPTIVE_BAND_WIDTH"),
            default=0.1,
        ),
        strategy_threshold_adaptive_cliff_safety_gap=_parse_float(
            os.getenv("STRATEGY_THRESHOLD_ADAPTIVE_CLIFF_SAFETY_GAP"),
            default=0.05,
        ),
        strategy_threshold_adaptive_max_step=_parse_float(
            os.getenv("STRATEGY_THRESHOLD_ADAPTIVE_MAX_STEP"),
            default=0.1,
        ),
        strategy_threshold_adaptive_min_confidence=(
            os.getenv("STRATEGY_THRESHOLD_ADAPTIVE_MIN_CONFIDENCE", "medium")
            .strip()
            .lower()
            or "medium"
        ),
        strategy_threshold_adaptive_cooldown_minutes=_parse_int(
            os.getenv("STRATEGY_THRESHOLD_ADAPTIVE_COOLDOWN_MINUTES"),
            default=30,
        ),
        strategy_threshold_adaptive_min_ticks=_parse_int(
            os.getenv("STRATEGY_THRESHOLD_ADAPTIVE_MIN_TICKS"),
            default=120,
        ),
        paper_execution_enabled=_parse_bool(
            os.getenv("PAPER_EXECUTION_ENABLED"),
            default=False,
        ),
        paper_execution_kill_switch=_parse_bool(
            os.getenv("PAPER_EXECUTION_KILL_SWITCH"),
            default=True,
        ),
        paper_execution_require_market_open=_parse_bool(
            os.getenv("PAPER_EXECUTION_REQUIRE_MARKET_OPEN"),
            default=True,
        ),
        paper_execution_equity_only=_parse_bool(
            os.getenv("PAPER_EXECUTION_EQUITY_ONLY"),
            default=True,
        ),
        paper_execution_max_orders_per_tick=_parse_int(
            os.getenv("PAPER_EXECUTION_MAX_ORDERS_PER_TICK"),
            default=1,
        ),
        paper_execution_max_open_positions=_parse_int(
            os.getenv("PAPER_EXECUTION_MAX_OPEN_POSITIONS"),
            default=1,
        ),
        paper_execution_default_notional_usd=_parse_float(
            os.getenv("PAPER_EXECUTION_DEFAULT_NOTIONAL_USD"),
            default=10.0,
        ),
        paper_execution_max_daily_drawdown_usd=_parse_float(
            os.getenv("PAPER_EXECUTION_MAX_DAILY_DRAWDOWN_USD"),
            default=5.0,
        ),
        paper_execution_stale_order_minutes=_parse_int(
            os.getenv("PAPER_EXECUTION_STALE_ORDER_MINUTES"),
            default=5,
        ),
        paper_execution_min_projected_gain_pct=_parse_percent_control(
            os.getenv("PAPER_EXECUTION_MIN_PROJECTED_GAIN_PCT"),
            default=0.015,
        ),
        paper_execution_crypto_min_projected_gain_pct=_parse_percent_control(
            os.getenv("PAPER_EXECUTION_CRYPTO_MIN_PROJECTED_GAIN_PCT"),
            default=0.02,
        ),
        paper_execution_profit_capture_pct=_parse_percent_control(
            os.getenv("PAPER_EXECUTION_PROFIT_CAPTURE_PCT"),
            default=0.0,
        ),
        paper_execution_limit_buffer_bps=_parse_float(
            os.getenv("PAPER_EXECUTION_LIMIT_BUFFER_BPS"),
            default=5.0,
        ),
        paper_execution_crypto_limit_buffer_bps=_parse_float(
            os.getenv("PAPER_EXECUTION_CRYPTO_LIMIT_BUFFER_BPS")
            or os.getenv("PAPER_EXECUTION_LIMIT_BUFFER_BPS"),
            default=5.0,
        ),
        paper_execution_high_score_override_enabled=_parse_bool(
            os.getenv("PAPER_EXECUTION_HIGH_SCORE_OVERRIDE_ENABLED"),
            default=False,
        ),
        paper_execution_high_score_override_min_score=paper_min_signal_score_to_trade,
        paper_execution_high_score_override_fitness_margin=_parse_float(
            os.getenv("PAPER_EXECUTION_HIGH_SCORE_OVERRIDE_FITNESS_MARGIN"),
            default=0.25,
        ),
        paper_min_signal_score_to_trade=paper_min_signal_score_to_trade,
        paper_execution_equity_no_weekend_carry_enabled=_parse_bool(
            os.getenv("PAPER_EXECUTION_EQUITY_NO_WEEKEND_CARRY_ENABLED"),
            default=True,
        ),
        paper_execution_equity_friday_entry_cutoff_minutes_before_close=_parse_int(
            os.getenv("PAPER_EXECUTION_EQUITY_FRIDAY_ENTRY_CUTOFF_MINUTES_BEFORE_CLOSE"),
            default=60,
        ),
        paper_execution_equity_friday_flatten_minutes_before_close=_parse_int(
            os.getenv("PAPER_EXECUTION_EQUITY_FRIDAY_FLATTEN_MINUTES_BEFORE_CLOSE"),
            default=15,
        ),
        trailing_drawdown_observer_enabled=_parse_bool(
            os.getenv("TRAILING_DRAWDOWN_OBSERVER_ENABLED"),
            default=True,
        ),
        trailing_drawdown_observer_paper_giveback_usd=_parse_float(
            os.getenv("TRAILING_DRAWDOWN_OBSERVER_PAPER_GIVEBACK_USD"),
            default=2.0,
        ),
        trailing_drawdown_observer_paper_giveback_pct=_parse_percent_control(
            os.getenv("TRAILING_DRAWDOWN_OBSERVER_PAPER_GIVEBACK_PCT"),
            default=0.0,
        ),
        trailing_drawdown_observer_live_giveback_usd=_parse_float(
            os.getenv("TRAILING_DRAWDOWN_OBSERVER_LIVE_GIVEBACK_USD"),
            default=2.0,
        ),
        trailing_drawdown_observer_live_giveback_pct=_parse_percent_control(
            os.getenv("TRAILING_DRAWDOWN_OBSERVER_LIVE_GIVEBACK_PCT"),
            default=0.0,
        ),
        paper_execution_equity_broker_id=(
            os.getenv("PAPER_EXECUTION_EQUITY_BROKER_ID", "alpaca_paper").strip().lower()
            or "alpaca_paper"
        ),
        paper_execution_crypto_broker_id=(
            os.getenv("PAPER_EXECUTION_CRYPTO_BROKER_ID", "alpaca_paper").strip().lower()
            or "alpaca_paper"
        ),
        paper_execution_allowed_strategies=_parse_identifier_csv(
            os.getenv(
                "PAPER_EXECUTION_ALLOWED_STRATEGIES",
                "mean_reversion.snapback",
            )
        ),
        live_execution_enabled=_parse_bool(
            os.getenv("LIVE_EXECUTION_ENABLED"),
            default=False,
        ),
        live_execution_kill_switch=_parse_bool(
            os.getenv("LIVE_EXECUTION_KILL_SWITCH"),
            default=True,
        ),
        live_execution_require_market_open=_parse_bool(
            os.getenv("LIVE_EXECUTION_REQUIRE_MARKET_OPEN"),
            default=True,
        ),
        live_execution_equity_only=_parse_bool(
            os.getenv("LIVE_EXECUTION_EQUITY_ONLY"),
            default=True,
        ),
        live_execution_max_orders_per_tick=_parse_int(
            os.getenv("LIVE_EXECUTION_MAX_ORDERS_PER_TICK"),
            default=1,
        ),
        live_execution_max_open_positions=_parse_int(
            os.getenv("LIVE_EXECUTION_MAX_OPEN_POSITIONS"),
            default=10,
        ),
        live_execution_default_notional_usd=_parse_float(
            os.getenv("LIVE_EXECUTION_DEFAULT_NOTIONAL_USD"),
            default=10.0,
        ),
        live_execution_max_daily_drawdown_usd=_parse_float(
            os.getenv("LIVE_EXECUTION_MAX_DAILY_DRAWDOWN_USD"),
            default=5.0,
        ),
        live_execution_stale_order_minutes=_parse_int(
            os.getenv("LIVE_EXECUTION_STALE_ORDER_MINUTES"),
            default=5,
        ),
        live_execution_min_projected_gain_pct=_parse_percent_control(
            os.getenv("LIVE_EXECUTION_MIN_PROJECTED_GAIN_PCT"),
            default=0.015,
        ),
        live_execution_crypto_min_projected_gain_pct=_parse_percent_control(
            os.getenv("LIVE_EXECUTION_CRYPTO_MIN_PROJECTED_GAIN_PCT"),
            default=0.02,
        ),
        live_execution_profit_capture_pct=_parse_percent_control(
            os.getenv("LIVE_EXECUTION_PROFIT_CAPTURE_PCT"),
            default=0.0125,
        ),
        live_execution_limit_buffer_bps=_parse_float(
            os.getenv("LIVE_EXECUTION_LIMIT_BUFFER_BPS"),
            default=5.0,
        ),
        live_execution_crypto_limit_buffer_bps=_parse_float(
            os.getenv("LIVE_EXECUTION_CRYPTO_LIMIT_BUFFER_BPS"),
            default=25.0,
        ),
        live_execution_high_score_override_enabled=_parse_bool(
            os.getenv("LIVE_EXECUTION_HIGH_SCORE_OVERRIDE_ENABLED"),
            default=True,
        ),
        live_execution_high_score_override_min_score=live_min_signal_score_to_trade,
        live_execution_high_score_override_fitness_margin=_parse_float(
            os.getenv("LIVE_EXECUTION_HIGH_SCORE_OVERRIDE_FITNESS_MARGIN"),
            default=0.25,
        ),
        live_min_signal_score_to_trade=live_min_signal_score_to_trade,
        live_execution_equity_no_weekend_carry_enabled=_parse_bool(
            os.getenv("LIVE_EXECUTION_EQUITY_NO_WEEKEND_CARRY_ENABLED"),
            default=True,
        ),
        live_execution_equity_friday_entry_cutoff_minutes_before_close=_parse_int(
            os.getenv("LIVE_EXECUTION_EQUITY_FRIDAY_ENTRY_CUTOFF_MINUTES_BEFORE_CLOSE"),
            default=60,
        ),
        live_execution_equity_friday_flatten_minutes_before_close=_parse_int(
            os.getenv("LIVE_EXECUTION_EQUITY_FRIDAY_FLATTEN_MINUTES_BEFORE_CLOSE"),
            default=15,
        ),
        live_execution_equity_broker_id=(
            os.getenv("LIVE_EXECUTION_EQUITY_BROKER_ID", "alpaca_live").strip().lower()
            or "alpaca_live"
        ),
        live_execution_crypto_broker_id=(
            os.getenv("LIVE_EXECUTION_CRYPTO_BROKER_ID", "alpaca_live").strip().lower()
            or "alpaca_live"
        ),
        live_execution_allowed_strategies=_parse_identifier_csv(
            os.getenv("LIVE_EXECUTION_ALLOWED_STRATEGIES", "")
        ),
        live_execution_activation_ack=os.getenv(
            "LIVE_EXECUTION_ACTIVATION_ACK",
            "",
        ).strip(),
        live_execution_allowed_paper_differences=_parse_identifier_csv(
            os.getenv("LIVE_EXECUTION_ALLOWED_PAPER_DIFFERENCES", "")
        ),
        ig_api_key=os.getenv("IG_API_KEY", "").strip(),
        ig_username=os.getenv("IG_USERNAME", "").strip(),
        ig_password=os.getenv("IG_PASSWORD", "").strip(),
        ig_account_type=os.getenv("IG_ACCOUNT_TYPE", "DEMO").strip().upper() or "DEMO",
        ig_account_number=os.getenv("IG_ACCOUNT_NUMBER", "").strip(),
        ig_base_url=os.getenv(
            "IG_BASE_URL",
            "https://demo-api.ig.com/gateway/deal",
        ).strip(),
        ig_request_timeout_seconds=_parse_int(
            os.getenv("IG_REQUEST_TIMEOUT_SECONDS"),
            default=10,
        ),
        ig_min_bet_per_point_gbp=_parse_float(
            os.getenv("IG_MIN_BET_PER_POINT_GBP"),
            default=0.10,
        ),
        ig_epic_overrides=_parse_symbol_map(
            os.getenv("IG_EPIC_OVERRIDES", "")
        ),
        trading212_paper_api_key=os.getenv("TRADING212_PAPER_API_KEY", "").strip(),
        trading212_paper_api_secret=os.getenv("TRADING212_PAPER_API_SECRET", "").strip(),
        trading212_paper_base_url=os.getenv(
            "TRADING212_PAPER_BASE_URL",
            "https://demo.trading212.com/api/v0",
        ).strip(),
        trading212_paper_request_timeout_seconds=_parse_int(
            os.getenv("TRADING212_PAPER_REQUEST_TIMEOUT_SECONDS"),
            default=10,
        ),
        trading212_paper_primary_currency=(
            os.getenv("TRADING212_PAPER_PRIMARY_CURRENCY", "GBP").strip().upper()
            or "GBP"
        ),
        trading212_paper_market_timezone=(
            os.getenv("TRADING212_PAPER_MARKET_TIMEZONE", "Europe/London").strip()
            or "Europe/London"
        ),
        trading212_paper_market_open_time=(
            os.getenv("TRADING212_PAPER_MARKET_OPEN_TIME", "08:00").strip()
            or "08:00"
        ),
        trading212_paper_market_close_time=(
            os.getenv("TRADING212_PAPER_MARKET_CLOSE_TIME", "16:30").strip()
            or "16:30"
        ),
        trading212_paper_equity_symbols=_parse_csv(
            os.getenv(
                "TRADING212_PAPER_EQUITY_SYMBOLS",
                DEFAULT_TRADING212_UK_EQUITY_SYMBOLS,
            )
        ),
        trading212_paper_price_seed_symbols=_parse_csv(
            os.getenv(
                "TRADING212_PAPER_PRICE_SEED_SYMBOLS",
                os.getenv(
                    "TRADING212_PAPER_EQUITY_SYMBOLS",
                    DEFAULT_TRADING212_UK_PRICE_SEED_SYMBOLS,
                ),
            )
        ),
        trading212_paper_market_data_provider=(
            os.getenv("TRADING212_PAPER_MARKET_DATA_PROVIDER", "disabled")
            .strip()
            .lower()
            or "disabled"
        ),
        trading212_paper_ticker_overrides=_parse_symbol_map(
            os.getenv("TRADING212_PAPER_TICKER_OVERRIDES", "")
        ),
        trading212_paper_execution_enabled=_parse_bool(
            os.getenv("TRADING212_PAPER_EXECUTION_ENABLED"),
            default=True,
        ),
        trading212_paper_default_notional_native=_parse_float(
            os.getenv("TRADING212_PAPER_DEFAULT_NOTIONAL_NATIVE"),
            default=10.0,
        ),
        trading212_live_api_key=os.getenv("TRADING212_LIVE_API_KEY", "").strip(),
        trading212_live_api_secret=os.getenv("TRADING212_LIVE_API_SECRET", "").strip(),
        trading212_live_base_url=os.getenv(
            "TRADING212_LIVE_BASE_URL",
            "https://live.trading212.com/api/v0",
        ).strip(),
        trading212_live_request_timeout_seconds=_parse_int(
            os.getenv("TRADING212_LIVE_REQUEST_TIMEOUT_SECONDS"),
            default=10,
        ),
        trading212_live_primary_currency=(
            os.getenv("TRADING212_LIVE_PRIMARY_CURRENCY", "GBP").strip().upper()
            or "GBP"
        ),
        trading212_live_market_timezone=(
            os.getenv("TRADING212_LIVE_MARKET_TIMEZONE", "Europe/London").strip()
            or "Europe/London"
        ),
        trading212_live_market_open_time=(
            os.getenv("TRADING212_LIVE_MARKET_OPEN_TIME", "08:00").strip()
            or "08:00"
        ),
        trading212_live_market_close_time=(
            os.getenv("TRADING212_LIVE_MARKET_CLOSE_TIME", "16:30").strip()
            or "16:30"
        ),
        trading212_live_equity_symbols=_parse_csv(
            os.getenv(
                "TRADING212_LIVE_EQUITY_SYMBOLS",
                os.getenv(
                    "TRADING212_PAPER_EQUITY_SYMBOLS",
                    DEFAULT_TRADING212_UK_EQUITY_SYMBOLS,
                ),
            )
        ),
        trading212_live_market_data_provider=(
            os.getenv("TRADING212_LIVE_MARKET_DATA_PROVIDER", "disabled")
            .strip()
            .lower()
            or "disabled"
        ),
        trading212_live_ticker_overrides=_parse_symbol_map(
            os.getenv("TRADING212_LIVE_TICKER_OVERRIDES", "")
        ),
        trading212_live_execution_enabled=_parse_bool(
            os.getenv("TRADING212_LIVE_EXECUTION_ENABLED"),
            default=False,
        ),
        trading212_live_default_notional_native=_parse_float(
            os.getenv("TRADING212_LIVE_DEFAULT_NOTIONAL_NATIVE"),
            default=10.0,
        ),
        gemini_api_configured=_is_real_value(os.getenv("GEMINI_API_KEY", "")),
        alpaca_api_configured=(
            _is_real_value(os.getenv("ALPACA_API_KEY", ""))
            and _is_real_value(os.getenv("ALPACA_SECRET_KEY", ""))
        ),
        alpaca_live_api_configured=(
            _is_real_value(os.getenv("ALPACA_LIVE_API_KEY", ""))
            and _is_real_value(os.getenv("ALPACA_LIVE_SECRET_KEY", ""))
        ),
        ig_api_configured=(
            _is_real_value(os.getenv("IG_API_KEY", ""))
            and _is_real_value(os.getenv("IG_USERNAME", ""))
            and _is_real_value(os.getenv("IG_PASSWORD", ""))
        ),
        trading212_paper_api_configured=_is_real_value(
            os.getenv("TRADING212_PAPER_API_KEY", "")
        )
        and _is_real_value(
            os.getenv("TRADING212_PAPER_API_SECRET", "")
        ),
        trading212_live_api_configured=_is_real_value(
            os.getenv("TRADING212_LIVE_API_KEY", "")
        )
        and _is_real_value(
            os.getenv("TRADING212_LIVE_API_SECRET", "")
        ),
        postgres_configured=bool(database_url),
        provider_pricing=_load_provider_pricing(),
    )
    _validate_live_same_as_paper_config(config)
    return config


def _validate_live_same_as_paper_config(config: RuntimeConfig) -> None:
    """Fail closed when the armed live follower drifts from paper risk levers."""
    if not (
        config.live_execution_enabled
        or config.live_execution_activation_ack
        or config.centaur_mode in {"live", "live_dry"}
    ):
        return

    mirrored_fields = (
        ("execution_require_market_open", "paper_execution_require_market_open", "live_execution_require_market_open"),
        ("execution_equity_only", "paper_execution_equity_only", "live_execution_equity_only"),
        ("execution_max_orders_per_tick", "paper_execution_max_orders_per_tick", "live_execution_max_orders_per_tick"),
        ("execution_max_open_positions", "paper_execution_max_open_positions", "live_execution_max_open_positions"),
        ("execution_default_notional_usd", "paper_execution_default_notional_usd", "live_execution_default_notional_usd"),
        ("execution_max_daily_drawdown_usd", "paper_execution_max_daily_drawdown_usd", "live_execution_max_daily_drawdown_usd"),
        ("execution_stale_order_minutes", "paper_execution_stale_order_minutes", "live_execution_stale_order_minutes"),
        ("execution_min_projected_gain_pct", "paper_execution_min_projected_gain_pct", "live_execution_min_projected_gain_pct"),
        ("execution_crypto_min_projected_gain_pct", "paper_execution_crypto_min_projected_gain_pct", "live_execution_crypto_min_projected_gain_pct"),
        ("execution_profit_capture_pct", "paper_execution_profit_capture_pct", "live_execution_profit_capture_pct"),
        ("execution_limit_buffer_bps", "paper_execution_limit_buffer_bps", "live_execution_limit_buffer_bps"),
        ("execution_crypto_limit_buffer_bps", "paper_execution_crypto_limit_buffer_bps", "live_execution_crypto_limit_buffer_bps"),
        ("min_signal_score_to_trade", "paper_min_signal_score_to_trade", "live_min_signal_score_to_trade"),
        ("execution_equity_no_weekend_carry_enabled", "paper_execution_equity_no_weekend_carry_enabled", "live_execution_equity_no_weekend_carry_enabled"),
        (
            "execution_equity_friday_entry_cutoff_minutes_before_close",
            "paper_execution_equity_friday_entry_cutoff_minutes_before_close",
            "live_execution_equity_friday_entry_cutoff_minutes_before_close",
        ),
        (
            "execution_equity_friday_flatten_minutes_before_close",
            "paper_execution_equity_friday_flatten_minutes_before_close",
            "live_execution_equity_friday_flatten_minutes_before_close",
        ),
        ("execution_allowed_strategies", "paper_execution_allowed_strategies", "live_execution_allowed_strategies"),
        (
            "trailing_drawdown_observer_giveback_usd",
            "trailing_drawdown_observer_paper_giveback_usd",
            "trailing_drawdown_observer_live_giveback_usd",
        ),
        (
            "trailing_drawdown_observer_giveback_pct",
            "trailing_drawdown_observer_paper_giveback_pct",
            "trailing_drawdown_observer_live_giveback_pct",
        ),
        (
            "crypto_momentum_stop_loss_pct",
            "paper_crypto_momentum_stop_loss_pct",
            "live_crypto_momentum_stop_loss_pct",
        ),
        (
            "crypto_momentum_target_multiple",
            "paper_crypto_momentum_target_multiple",
            "live_crypto_momentum_target_multiple",
        ),
        (
            "crypto_momentum_min_signal_score",
            "paper_crypto_momentum_min_signal_score",
            "live_crypto_momentum_min_signal_score",
        ),
        (
            "crypto_momentum_min_movement_pct",
            "paper_crypto_momentum_min_movement_pct",
            "live_crypto_momentum_min_movement_pct",
        ),
        (
            "crypto_momentum_max_movement_pct",
            "paper_crypto_momentum_max_movement_pct",
            "live_crypto_momentum_max_movement_pct",
        ),
        (
            "crypto_momentum_min_discovery_score",
            "paper_crypto_momentum_min_discovery_score",
            "live_crypto_momentum_min_discovery_score",
        ),
        (
            "crypto_momentum_min_trade_count",
            "paper_crypto_momentum_min_trade_count",
            "live_crypto_momentum_min_trade_count",
        ),
        (
            "crypto_momentum_min_volume_gbp",
            "paper_crypto_momentum_min_volume_gbp",
            "live_crypto_momentum_min_volume_gbp",
        ),
        (
            "crypto_momentum_max_spread_pct",
            "paper_crypto_momentum_max_spread_pct",
            "live_crypto_momentum_max_spread_pct",
        ),
    )
    allowed_differences = set(config.live_execution_allowed_paper_differences)
    known_difference_names = {name for name, _, _ in mirrored_fields}
    unknown_differences = sorted(allowed_differences - known_difference_names)
    if unknown_differences:
        joined = ", ".join(unknown_differences)
        raise ValueError(f"live_same_as_paper_unknown_allowed_difference: {joined}")

    mismatches = [
        name
        for name, paper_attr, live_attr in mirrored_fields
        if getattr(config, paper_attr) != getattr(config, live_attr)
        and name not in allowed_differences
    ]
    if mismatches:
        joined = ", ".join(mismatches)
        raise ValueError(f"live_same_as_paper_config_mismatch: {joined}")


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _load_provider_pricing() -> dict[str, SourcePricing]:
    return {
        "gemini_api": SourcePricing(
            source="gemini_api",
            input_cost_per_million_units_usd=_parse_float(
                os.getenv("GEMINI_INPUT_COST_PER_MILLION_TOKENS_USD"),
                default=0.0,
            ),
            output_cost_per_million_units_usd=_parse_float(
                os.getenv("GEMINI_OUTPUT_COST_PER_MILLION_TOKENS_USD"),
                default=0.0,
            ),
        ),
        "alpaca_paper": SourcePricing(
            source="alpaca_paper",
            cost_per_request_usd=_parse_float(
                os.getenv("ALPACA_REQUEST_COST_USD"),
                default=0.0,
            ),
        ),
        "alpaca_live": SourcePricing(
            source="alpaca_live",
            cost_per_request_usd=_parse_float(
                os.getenv("ALPACA_LIVE_REQUEST_COST_USD"),
                default=0.0,
            ),
        ),
        "alpaca_market_data": SourcePricing(
            source="alpaca_market_data",
            cost_per_request_usd=_parse_float(
                os.getenv("ALPACA_DATA_REQUEST_COST_USD"),
                default=0.0,
            ),
        ),
        "alpaca_crypto_data": SourcePricing(
            source="alpaca_crypto_data",
            cost_per_request_usd=_parse_float(
                os.getenv("ALPACA_CRYPTO_DATA_REQUEST_COST_USD"),
                default=0.0,
            ),
        ),
        "ig_spreadbet": SourcePricing(
            source="ig_spreadbet",
            cost_per_request_usd=_parse_float(
                os.getenv("IG_REQUEST_COST_USD"),
                default=0.0,
            ),
        ),
        "trading212_paper": SourcePricing(
            source="trading212_paper",
            cost_per_request_usd=_parse_float(
                os.getenv("TRADING212_PAPER_REQUEST_COST_USD"),
                default=0.0,
            ),
        ),
        "trading212_live": SourcePricing(
            source="trading212_live",
            cost_per_request_usd=_parse_float(
                os.getenv("TRADING212_LIVE_REQUEST_COST_USD"),
                default=0.0,
            ),
        ),
        "ecb_fx": SourcePricing(
            source="ecb_fx",
            cost_per_request_usd=0.0,
        ),
        "polygon_api": SourcePricing(
            source="polygon_api",
            cost_per_request_usd=_parse_float(
                os.getenv("POLYGON_REQUEST_COST_USD"),
                default=0.0,
            ),
        ),
        "news_api": SourcePricing(
            source="news_api",
            cost_per_request_usd=_parse_float(
                os.getenv("NEWS_API_REQUEST_COST_USD"),
                default=0.0,
            ),
        ),
    }


def _resolve_project_path(value: str) -> Path:
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def _resolve_database_url() -> tuple[str, str]:
    configured_database_url = os.getenv("DATABASE_URL", "").strip()
    if configured_database_url and "replace_me" not in configured_database_url:
        return configured_database_url, "env"

    host = os.getenv("POSTGRES_HOST", "").strip()
    port = os.getenv("POSTGRES_PORT", "5432").strip()
    database = os.getenv("POSTGRES_DB", "").strip()
    user = os.getenv("POSTGRES_USER", "").strip()
    password = os.getenv("POSTGRES_PASSWORD", "").strip()
    sslmode = os.getenv("POSTGRES_SSLMODE", "").strip()

    parts = [host, database, user, password]
    if not all(_is_real_value(part) for part in parts):
        return "", ""

    encoded_user = quote(user)
    encoded_password = quote(password)
    encoded_database = quote(database)
    base_url = (
        f"postgresql://{encoded_user}:{encoded_password}@{host}:{port}/{encoded_database}"
    )
    if sslmode:
        return f"{base_url}?sslmode={quote(sslmode)}", "parts"
    return base_url, "parts"


def _normalize_backend_preference(value: str) -> str:
    normalized = value.strip().lower()
    if normalized in {"auto", "postgres", "sqlite"}:
        return normalized
    return "auto"


def _normalize_postgres_schema(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    allowed = []
    for char in normalized:
        if char.isalnum() or char == "_":
            allowed.append(char.lower())
    return "".join(allowed)


def _normalize_centaur_mode(value: str) -> str:
    normalized = str(value or "paper").strip().lower()
    if normalized in {"shadow", "paper", "live_dry", "live"}:
        return normalized
    return "paper"


def _normalize_centaur_environment(value: str) -> str:
    normalized = str(value or "paper").strip().lower()
    if normalized in {"paper", "live"}:
        return normalized
    return "paper"


def _resolve_centaur_mode() -> str:
    configured = os.getenv("CENTAUR_MODE")
    if configured is not None and configured.strip():
        return _normalize_centaur_mode(configured)

    # Transition helper for the existing same-as-paper live follower lane: older
    # .env files predate CENTAUR_MODE, so reflect an already-armed live lane
    # honestly in status/metadata without changing any live activation gates.
    if (
        _parse_bool(os.getenv("LIVE_EXECUTION_ENABLED"), default=False)
        and not _parse_bool(os.getenv("LIVE_EXECUTION_KILL_SWITCH"), default=True)
        and os.getenv("LIVE_EXECUTION_ACTIVATION_ACK", "").strip()
        == "LIVE_TRADING_APPROVED"
    ):
        return "live"

    return "paper"


def _resolve_centaur_environment() -> str:
    configured = os.getenv("CENTAUR_ENVIRONMENT")
    if configured is not None and configured.strip():
        return _normalize_centaur_environment(configured)

    return "live" if _resolve_centaur_mode() in {"live", "live_dry"} else "paper"


def _parse_csv(value: str | None) -> tuple[str, ...]:
    if value is None:
        return tuple()

    items = []
    for raw_item in value.split(","):
        item = raw_item.strip().upper()
        if item:
            items.append(item)
    return tuple(items)


def _parse_identifier_csv(value: str | None) -> tuple[str, ...]:
    if value is None:
        return tuple()

    items = []
    for raw_item in value.split(","):
        item = raw_item.strip().lower()
        if item:
            items.append(item)
    return tuple(items)


def _parse_symbol_map(value: str | None) -> dict[str, str]:
    if value is None:
        return {}

    mapping: dict[str, str] = {}
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item or ":" not in item:
            continue
        symbol, mapped_value = item.split(":", 1)
        symbol = symbol.strip().upper()
        mapped_value = mapped_value.strip()
        if symbol and mapped_value:
            mapping[symbol] = mapped_value
    return mapping


def _parse_shadow_windows(value: str | None) -> tuple[str, ...]:
    if value is None:
        return tuple()

    windows = []
    for raw_item in value.split(","):
        item = raw_item.strip().lower()
        if item:
            windows.append(item)
    return tuple(windows)


def _parse_float_csv(value: str | None, *, default: tuple[float, ...]) -> tuple[float, ...]:
    if value is None or not value.strip():
        return default
    parsed: list[float] = []
    for raw_item in value.split(","):
        item = raw_item.strip()
        if item:
            parsed.append(float(item))
    return tuple(parsed) if parsed else default


def _parse_bool(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(value: str | None, *, default: int) -> int:
    if value is None or not value.strip():
        return default
    return int(value)


def _parse_float(value: str | None, *, default: float) -> float:
    if value is None or not value.strip():
        return default
    return float(value)


def _parse_percent_control(value: str | None, *, default: float) -> float:
    """Parse operator percent controls.

    Preferred input is human percent notation: `0.5` means 0.5%, `1` means 1%,
    and `1.2` means 1.2%. Legacy decimal-ratio values below 0.1 are accepted so
    existing `.env` files keep their current risk behaviour until rewritten.
    """
    if value is None or not value.strip():
        return default
    parsed = float(value)
    if parsed < 0:
        raise ValueError("percent controls must be non-negative")
    if 0 < parsed < 0.1:
        return parsed
    return parsed / 100.0


def _is_real_value(value: str) -> bool:
    normalized = value.strip()
    if not normalized:
        return False
    return not normalized.startswith("replace_me")

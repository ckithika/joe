# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-03-09

### Added

- Strategy pattern with `BaseStrategy` ABC and auto-discovery registry (`agent/strategies/`)
- 7 pluggable strategy modules: trend_following, mean_reversion, breakout, momentum, day_trade, opening_range_breakout, vwap_bounce
- `BaseBroker` abstract interface (`brokers/base.py`) — IBKR and Capital.com now inherit from it
- Cross-process file locking utility (`agent/file_lock.py`) using `fcntl.flock()` for safe concurrent JSON/CSV access
- `config/trading.yaml` for market hours, holidays, circuit breakers, and risk controls (previously hardcoded)
- Backtester slippage (0.05%) and commission ($1/trade) modeling
- 63 new tests (config validator, risk profiles, strategies, broker base, trading config, file locking)

### Changed

- PaperTrader decomposed into PositionManager, PnLCalculator, and PerformanceTracker (facade preserved for backward compatibility)
- All shared state files (positions, performance, session state, bot state, trade history) now use file locking
- All JSON writes use atomic tempfile + os.replace inside exclusive locks
- Docker container runs as non-root user `joeai`

### Fixed

- Silent `except: pass` blocks now log errors (monitor.py, main.py)
- News API safe `.get()` pattern prevents KeyError on missing sentiment scores
- IBKR client passes explicit timeout to `reqHistoricalData`

## [0.2.0] - 2026-03-08

### Added

- Opening Range Breakout (ORB) strategy for day trading
- VWAP crossover strategy with intraday signals
- Upgraded monitor with real-time position tracking
- Intraday risk management with per-trade stop-loss and daily loss limits
- Telegram bot commands for day trading control
- Auto-tuner for strategy parameter optimization
- Daily trading digest with P&L summary
- Weekly performance digest with win rate and strategy breakdown
- Real-time signal alerts via Telegram
- Day trading session management (market open/close awareness)

### Changed

- Pipeline architecture pivoted from swing trading to day trading focus
- Risk management module expanded with intraday-specific controls
- Monitor upgraded to support sub-minute refresh intervals

### Fixed

- Broker connection stability during high-frequency polling
- Signal deduplication for rapid intraday signals

## [0.1.0] - 2026-02-20

### Added

- Core trading pipeline with modular architecture
- 5 trading strategies (momentum, mean reversion, breakout, trend following, volatility)
- Paper trading support with simulated execution
- IBKR broker integration (local gateway)
- Capital.com broker integration (cloud/demo mode)
- Telegram bot for alerts and portfolio monitoring
- Cloud deployment support (GCP)
- Crypto market intelligence and screening
- Stock market intelligence and screening
- Streamlit dashboard for portfolio visualization
- Configuration via YAML and environment variables
- Automated scheduling with configurable intervals

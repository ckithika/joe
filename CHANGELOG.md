# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

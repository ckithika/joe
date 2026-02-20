# Live Trading Roadmap — Overview

> Last updated: 2026-02-20
> Status: Spec complete, not yet started
> Estimated total effort: 14-20 weeks (1 developer)

## Executive Summary

Joe AI is currently a **research and analysis engine** with a paper trading simulator. It scans markets via IBKR and Capital.com, scores instruments, detects market regimes, matches strategies, and tracks virtual positions. It cannot execute real trades.

This roadmap defines the work required to transition from paper-only to live execution while maintaining the existing research pipeline as the analytical foundation.

## Current Architecture

```
Cloud Scheduler → Cloud Run Job → main.py --once --broker capital --push
                                    │
                                    ├── RegimeDetector (SPY/VIX analysis)
                                    ├── MarketScanner (IBKR scanners + Capital.com watchlists)
                                    ├── ScoringEngine (technical + sentiment scoring)
                                    ├── StrategyEngine (trend, mean reversion, breakout, momentum)
                                    ├── RiskProfiler (5-dimension assessment)
                                    ├── PaperTrader (JSON-based virtual positions)
                                    ├── AIAnalyst (Gemini daily summary + trade analysis)
                                    ├── CryptoDataCollector / StockDataCollector / AfterHoursEngine
                                    ├── ReportGenerator (markdown + CSV + JSON)
                                    └── AlertManager (Telegram + Discord)
```

**Key limitation:** The pipeline runs as a batch job (2-5 minutes, once or twice daily). Positions are tracked in local JSON files. No order execution exists anywhere in the codebase.

## Target Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Event Loop (Daemon)                    │
│                                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐   │
│  │ Price     │  │ Order    │  │ Position Monitor     │   │
│  │ Streams   │→ │ Manager  │← │ (SL/TP/Trail check)  │   │
│  │ (WebSocket│  │          │  │                       │   │
│  └──────────┘  └──────────┘  └──────────────────────┘   │
│        ↑              ↑                ↑                  │
│        │              │                │                  │
│  ┌─────┴──────────────┴────────────────┴──────────┐     │
│  │          Execution Layer (new)                   │     │
│  │  ┌────────────────┐  ┌────────────────────────┐ │     │
│  │  │ IBKRExecutor   │  │ CapitalExecutor        │ │     │
│  │  │ (ib_insync)    │  │ (REST + WebSocket)     │ │     │
│  │  └────────────────┘  └────────────────────────┘ │     │
│  └─────────────────────────────────────────────────┘     │
│                          ↑                                │
│  ┌───────────────────────┴──────────────────────────┐   │
│  │        Analysis Pipeline (existing, enhanced)      │   │
│  │  Regime → Scan → Score → Strategy → Risk → Signal  │   │
│  └────────────────────────────────────────────────────┘   │
│                          ↑                                │
│  ┌───────────────────────┴──────────────────────────┐   │
│  │              Safety Layer (new)                     │   │
│  │  Kill switch, margin monitor, audit log, alerts    │   │
│  └────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

## Phase Overview

| Phase | Title | Effort | Dependencies | Deliverables |
|-------|-------|--------|--------------|--------------|
| 1 | Broker Execution APIs | 2-3 weeks | None | Order placement, fill tracking, account info for IBKR + Capital.com |
| 2 | Portfolio Abstraction | 1-2 weeks | Phase 1 | PortfolioManager interface, Paper + Live implementations |
| 3 | Live Config & Mode Switching | ~1 week | Phase 2 | execution.yaml, environment detection, audit logging, confirmation gates |
| 4 | Real-Time Event Loop | 4-6 weeks | Phases 1-3 | Persistent daemon, WebSocket streams, continuous position monitoring |
| 5 | Error Handling & Safety | 2-3 weeks | Phases 1-4 | Partial fills, kill switches, margin monitoring, duplicate prevention |
| 6 | Testing & Hardening | 3-4 weeks | Phases 1-5 | Shadow mode, small-size testing, chaos testing, reconciliation |

## Key Design Principles

1. **Paper trading must always work.** The live execution layer is additive — never break the existing paper trading pipeline.
2. **Default to paper.** If configuration is missing or ambiguous, the system must fall back to paper mode, never live.
3. **Fail closed.** On any error during live execution, the system should halt new entries (not retry blindly). Open positions remain with their broker-side stops.
4. **Audit everything.** Every order attempt, fill, rejection, modification, and cancel must be logged to `data/audit/` with timestamps.
5. **One switch.** A single `TRADING_MODE` environment variable controls paper vs live. No partial states.

## Files Modified Per Phase

### Phase 1
- `brokers/ibkr_client.py` — Add execution methods
- `brokers/capital_client.py` — Add execution methods
- `agent/models.py` — Add Order, Fill, AccountInfo dataclasses

### Phase 2
- New: `agent/portfolio_manager.py` — Abstract interface
- `agent/paper_trader.py` — Refactor to implement interface
- New: `agent/live_trader.py` — Live implementation
- `main.py` — Use PortfolioManager interface

### Phase 3
- New: `config/execution.yaml` — Live trading configuration
- New: `agent/audit.py` — Audit logging
- `main.py` — Mode detection, confirmation gates

### Phase 4
- New: `agent/event_loop.py` — Persistent daemon
- New: `agent/price_stream.py` — WebSocket price feeds
- New: `agent/order_manager.py` — Order lifecycle management
- `main.py` — Daemon mode entry point

### Phase 5
- `agent/resilience.py` — Execution-specific circuit breakers
- New: `agent/safety.py` — Kill switches, margin monitor
- `agent/alerts.py` — Execution alerts
- `agent/risk_profiler.py` — Real-time margin checks

### Phase 6
- New: `agent/shadow_mode.py` — Paper/live comparison
- New: `tests/test_execution.py` — Execution integration tests
- New: `tests/test_safety.py` — Safety mechanism tests

## Prerequisites Before Starting

1. **Paper trading track record** — Run paper for at least 30 days with 50+ trades to validate strategies before risking real money
2. **IBKR paper account** — Continue using port 7497 (paper) through Phases 1-5. Only switch to 7496 (live) after Phase 6 completion.
3. **Capital.com demo account** — Keep `CAPITAL_DEMO=true` through all phases
4. **Backup broker access** — Have both IBKR and Capital.com functional for failover scenarios

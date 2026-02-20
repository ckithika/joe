"""Joe AI — Streamlit Dashboard."""

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import pytz
import streamlit as st
import yaml

st.set_page_config(page_title="Joe AI", page_icon="📊", layout="wide")

DATA_DIR = Path("data/paper")
REPORTS_DIR = Path("data/reports")
FINDINGS_DIR = Path("data/findings")
CONFIG_DIR = Path("config")

logger = logging.getLogger(__name__)


# ── Data Loading ─────────────────────────────────────────────────


def load_json(path: Path) -> dict | list:
    if path.exists():
        return json.loads(path.read_text())
    return {}


def load_csv(path: Path) -> pd.DataFrame:
    if path.exists():
        return pd.read_csv(path)
    return pd.DataFrame()


def load_config() -> dict:
    path = CONFIG_DIR / "dashboard.yaml"
    if path.exists():
        data = yaml.safe_load(path.read_text())
        return data.get("dashboard", {})
    return {}


def load_preferences() -> dict:
    path = CONFIG_DIR / "preferences.yaml"
    if path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}


config = load_config()
prefs = load_preferences()
modules = prefs.get("modules", {"stocks": True, "crypto": True, "after_hours": True})

performance = load_json(DATA_DIR / "performance.json")
regime_data = load_json(DATA_DIR / "regime.json")
risk_data = load_json(DATA_DIR / "risk_assessment.json")
positions_data = load_json(DATA_DIR / "open_positions.json")
if isinstance(positions_data, dict):
    positions_data = positions_data.get("positions", [])
if not isinstance(positions_data, list):
    positions_data = []
trades_df = load_csv(DATA_DIR / "trade_history.csv")
today_report = load_json(REPORTS_DIR / f"{date.today()}.json")
if not isinstance(today_report, dict):
    today_report = {}
behavior_log_path = DATA_DIR / "behavior_log.json"
regime_daily_log = load_json(DATA_DIR / "regime_daily_log.json")
if not isinstance(regime_daily_log, list):
    regime_daily_log = []
today_findings = load_json(FINDINGS_DIR / f"{date.today()}.json")
if not isinstance(today_findings, dict):
    today_findings = {}
portfolio_analytics = load_json(DATA_DIR / "portfolio_analytics.json")
if not isinstance(portfolio_analytics, dict):
    portfolio_analytics = {}
api_health = load_json(DATA_DIR / "api_health.json")
if not isinstance(api_health, list):
    api_health = []


# ── Sidebar Navigation ──────────────────────────────────────────


st.sidebar.title("📊 Joe AI")

timestamp = regime_data.get("timestamp", "No data yet") if isinstance(regime_data, dict) else "No data yet"
st.sidebar.caption(f"Last updated: {timestamp}")

# Build navigation based on enabled modules
nav_options = ["Overview", "Stocks"]
if modules.get("crypto", False):
    nav_options.append("Crypto")
nav_options.extend(["Portfolio", "Performance", "System"])

page = st.sidebar.radio("Navigate", nav_options, label_visibility="collapsed")

st.sidebar.divider()

# Market session status in sidebar
sessions = config.get("market_sessions", {})


def get_session_status(session_config: dict) -> dict:
    """Determine if a market session is open/closed and countdown."""
    tz_name = session_config.get("timezone", "UTC")
    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)

    if session_config.get("always_open"):
        return {"status": "24/7", "icon": "🟢", "note": session_config.get("note", "")}

    days = session_config.get("days", [0, 1, 2, 3, 4])
    if now.weekday() not in days:
        return {"status": "CLOSED", "icon": "🔴", "note": "Weekend"}

    holidays = config.get("holidays_2026", [])
    if now.strftime("%Y-%m-%d") in holidays:
        return {"status": "CLOSED", "icon": "🔴", "note": "Holiday"}

    regular_open = session_config.get("regular_open", "09:30")
    regular_close = session_config.get("regular_close", "16:00")
    premarket_open = session_config.get("premarket_open")
    afterhours_close = session_config.get("afterhours_close")

    open_h, open_m = map(int, regular_open.split(":"))
    close_h, close_m = map(int, regular_close.split(":"))
    open_time = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    close_time = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)

    if open_time <= now <= close_time:
        remaining = close_time - now
        hours, rem = divmod(int(remaining.total_seconds()), 3600)
        minutes = rem // 60
        return {"status": "OPEN", "icon": "🟢", "note": f"Closes in {hours}h {minutes}m"}

    if afterhours_close:
        ah_h, ah_m = map(int, afterhours_close.split(":"))
        ah_time = now.replace(hour=ah_h, minute=ah_m, second=0, microsecond=0)
        if close_time < now <= ah_time:
            remaining = ah_time - now
            hours, rem = divmod(int(remaining.total_seconds()), 3600)
            minutes = rem // 60
            return {"status": "AFTER-HRS", "icon": "🟡", "note": f"Ends in {hours}h {minutes}m"}

    if premarket_open:
        pm_h, pm_m = map(int, premarket_open.split(":"))
        pm_time = now.replace(hour=pm_h, minute=pm_m, second=0, microsecond=0)
        if pm_time <= now < open_time:
            remaining = open_time - now
            hours, rem = divmod(int(remaining.total_seconds()), 3600)
            minutes = rem // 60
            return {"status": "PRE-MKT", "icon": "🟡", "note": f"Regular in {hours}h {minutes}m"}

    if now > close_time:
        next_open = open_time + timedelta(days=1)
    else:
        next_open = open_time
    remaining = next_open - now
    hours, rem = divmod(int(remaining.total_seconds()), 3600)
    minutes = rem // 60
    return {"status": "CLOSED", "icon": "🔴", "note": f"Opens in {hours}h {minutes}m"}


if sessions:
    st.sidebar.markdown("**Market Sessions**")
    for key, sess in sessions.items():
        # Skip crypto session if module disabled
        if key == "crypto" and not modules.get("crypto", False):
            continue
        status = get_session_status(sess)
        st.sidebar.markdown(f"{status['icon']} **{sess.get('name', key)}** — {status['status']}")
        if status["note"]:
            st.sidebar.caption(f"  {status['note']}")

st.sidebar.divider()

# Module status
st.sidebar.markdown("**Enabled Modules**")
for mod, enabled in modules.items():
    icon = "✅" if enabled else "⬜"
    st.sidebar.markdown(f"{icon} {mod.replace('_', ' ').title()}")

st.sidebar.caption("Configure: `python setup_wizard.py`")


# ── Helper ───────────────────────────────────────────────────────


def _log_decision(ticker: str, action: str, strategy: str, reason: str):
    """Log a dashboard decision to behavior_log.json."""
    entry = {
        "date": date.today().isoformat(),
        "action": action,
        "ticker": ticker,
        "strategy": strategy,
        "reason": reason,
        "plan_aligned": True,
        "discipline_rating": None,
    }
    log = []
    if behavior_log_path.exists():
        log = json.loads(behavior_log_path.read_text())
    log.append(entry)
    behavior_log_path.parent.mkdir(parents=True, exist_ok=True)
    behavior_log_path.write_text(json.dumps(log, indent=2))


# ═════════════════════════════════════════════════════════════════
# PAGES
# ═════════════════════════════════════════════════════════════════


if page == "Overview":
    st.title("Overview")
    st.caption(
        "Your learning dashboard — see what the market is doing today, understand the strategies "
        "the agent uses, and track how paper trades perform over time."
    )

    # ── Regime & Risk side by side ───────────────────────────────
    col_regime, col_risk = st.columns(2)

    with col_regime:
        st.subheader("Market Regime")
        if isinstance(regime_data, dict) and regime_data:
            regime_name = regime_data.get("regime", "unknown").replace("_", " ").upper()
            confidence = regime_data.get("confidence", 0)
            st.markdown(f"### {regime_name}")
            st.progress(confidence, text=f"Confidence: {confidence:.0%}")

            r1, r2, r3 = st.columns(3)
            r1.metric("ADX", f"{regime_data.get('adx', 0):.1f}")
            r2.metric("VIX", f"{regime_data.get('vix', 0):.1f}")
            r3.metric("Size Mod", f"{regime_data.get('position_size_modifier', 1.0):.0%}")

            strategies = regime_data.get("active_strategies", [])
            if strategies:
                st.markdown(f"**Active:** {', '.join(s.replace('_', ' ').title() for s in strategies)}")

            # VIX sparkline
            vix_hist = regime_data.get("vix_history", [])
            if vix_hist and len(vix_hist) > 2:
                fig = go.Figure(go.Scatter(y=vix_hist, mode="lines", line=dict(color="red", width=1)))
                fig.update_layout(height=80, margin=dict(l=0, r=0, t=10, b=0), showlegend=False,
                                  yaxis=dict(showticklabels=False), xaxis=dict(showticklabels=False))
                st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No regime data. Run the pipeline first.")

    with col_risk:
        st.subheader("Risk Grade")
        if isinstance(risk_data, dict) and risk_data:
            composite = risk_data.get("composite_score", 0)
            level = risk_data.get("risk_level", "unknown").upper()
            st.markdown(f"### {composite:.1f}/10 — {level}")
            st.progress(min(composite / 10, 1.0))

            dims = risk_data.get("dimensions", {})
            if dims:
                dim_df = pd.DataFrame([{"Dimension": k.title(), "Score": v} for k, v in dims.items()])
                fig = px.bar(dim_df, x="Dimension", y="Score", color="Score",
                             color_continuous_scale=["green", "yellow", "red"], range_y=[0, 10], height=200)
                fig.update_layout(showlegend=False, margin=dict(t=10, b=10))
                st.plotly_chart(fig, use_container_width=True)

            alerts = risk_data.get("alerts", [])
            for alert in alerts[:3]:
                sev = alert.get("severity", "info").upper()
                st.markdown(f"**[{sev}]** {alert.get('message', '')}")
        else:
            st.info("No risk data. Run the pipeline first.")

    # ── Portfolio snapshot ────────────────────────────────────────
    st.divider()
    st.subheader("Portfolio Snapshot")

    if isinstance(performance, dict) and performance:
        balance = performance.get("virtual_balance", 500)
        starting = performance.get("starting_balance", 500)
        pnl = balance - starting

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Balance", f"${balance:.2f}", f"{pnl:+.2f}")
        m2.metric("Win Rate", f"{performance.get('win_rate', 0) * 100:.1f}%")
        m3.metric("Open", f"{len(positions_data)}/3")
        m4.metric("Total Trades", f"{performance.get('total_trades', 0)}")
        m5.metric("Profit Factor", f"{performance.get('profit_factor', 0):.2f}")

        if positions_data:
            pos_rows = []
            for pos in positions_data:
                pnl_val = pos.get("unrealized_pnl", 0)
                pos_rows.append({
                    "Ticker": pos["ticker"],
                    "Dir": pos["direction"],
                    "Strategy": pos.get("strategy", ""),
                    "Entry": f"${pos['entry_price']:.2f}",
                    "P&L": f"${pnl_val:+.2f}",
                    "Day": f"{pos.get('days_held', 0)}/{pos.get('max_hold_days', 10)}",
                })
            st.dataframe(pd.DataFrame(pos_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No performance data. Run the pipeline first.")

    # ── AI Summary ───────────────────────────────────────────────
    ai_summary = today_findings.get("ai_summary")
    if ai_summary:
        st.divider()
        st.subheader("AI Daily Summary")
        st.markdown(ai_summary)

    # ── After-Hours ──────────────────────────────────────────────
    if modules.get("after_hours", True):
        after_hours = today_findings.get("after_hours", {})
        if after_hours:
            st.divider()
            session = after_hours.get("session", "").replace("_", " ").title()
            st.subheader(f"After-Hours ({session})")

            gaps = after_hours.get("earnings_gaps", [])
            movers = after_hours.get("pre_market_movers", [])
            crypto_night = after_hours.get("crypto_overnight", [])

            if gaps:
                st.markdown("**Earnings Gaps**")
                for g in gaps[:5]:
                    gap = g.get("gap_pct", 0)
                    direction = "⬆️" if gap > 0 else "⬇️"
                    st.markdown(f"  {direction} **{g.get('ticker', '')}**: {gap:+.1f}%")

            if movers:
                st.markdown("**Pre-Market Movers**")
                mover_rows = []
                for m in movers[:5]:
                    mover_rows.append({
                        "Ticker": m.get("ticker", ""),
                        "Change": f"{m.get('gap_pct', m.get('change_pct', 0)):+.1f}%",
                        "Vol Ratio": f"{m.get('volume_ratio', 0):.1f}x",
                        "Catalyst": m.get("catalyst", ""),
                    })
                st.dataframe(pd.DataFrame(mover_rows), use_container_width=True, hide_index=True)

            if crypto_night and modules.get("crypto", False):
                st.markdown("**Crypto Overnight**")
                for s in crypto_night[:3]:
                    st.markdown(f"  {s.get('symbol', '')}: {s.get('signal_type', '').replace('_', ' ').title()}")

            if not gaps and not movers and not crypto_night:
                st.caption("No notable after-hours activity.")


elif page == "Stocks":
    st.title("📈 Stocks")

    # ── Today's Stock Signals ────────────────────────────────────
    st.subheader("Today's Signals")

    all_signals = today_findings.get("signals", today_report.get("signals", []))
    stock_signals = [s for s in all_signals if s.get("ticker", "") not in {"BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT"}]

    if stock_signals:
        available_slots = 3 - len(positions_data)
        st.caption(f"{available_slots} position slot{'s' if available_slots != 1 else ''} available")

        for sig in stock_signals[:config.get("max_signals_displayed", 5)]:
            action = sig.get("action", "skip")
            ticker = sig.get("ticker", "")
            score = sig.get("score", 0)
            signal_type = sig.get("signal", "NEUTRAL")

            with st.expander(
                f"{'🟢' if action == 'enter_now' else '🟡' if action == 'watch' else '⚪'} "
                f"{ticker} — {signal_type} (Score: {score:.2f})",
                expanded=(action == "enter_now"),
            ):
                st.markdown(
                    f"**Strategy:** {sig.get('strategy', '').replace('_', ' ').title()} · "
                    f"**Direction:** {sig.get('direction', '')} · "
                    f"**Action:** {action.replace('_', ' ').title()}"
                )
                entry_price = sig.get("entry_price", 0)
                sl = sig.get("stop_loss", 0)
                tp = sig.get("take_profit", 0)
                if entry_price:
                    st.markdown(f"**Entry:** ${entry_price:,.2f} · **SL:** ${sl:,.2f} · **TP:** ${tp:,.2f}")
                    if sl and entry_price and tp:
                        risk = abs(entry_price - sl)
                        reward = abs(tp - entry_price)
                        rr = reward / risk if risk > 0 else 0
                        st.markdown(f"**R:R** = 1:{rr:.1f}")

                # AI analysis if present
                ai = sig.get("ai_analysis", {})
                if ai:
                    st.markdown(f"**AI:** {ai.get('recommendation', '')} (confidence: {ai.get('confidence', 0):.0%})")
                    st.markdown(f"*Bull:* {ai.get('bull_case', '')}")
                    st.markdown(f"*Bear:* {ai.get('bear_case', '')}")

                # Decision buttons for actionable signals
                if action == "enter_now":
                    col_enter, col_watch, col_skip = st.columns(3)
                    btn_key = f"btn_{ticker}_{date.today()}"
                    if col_enter.button("ENTER", key=f"{btn_key}_enter", type="primary"):
                        _log_decision(ticker, "entry", sig.get("strategy", ""), "Entered from dashboard")
                        st.success(f"Logged ENTER for {ticker}")
                    if col_watch.button("WATCHLIST", key=f"{btn_key}_watch"):
                        _log_decision(ticker, "watchlist", sig.get("strategy", ""), "Added to watchlist")
                        st.info(f"Logged WATCHLIST for {ticker}")
                    if col_skip.button("SKIP", key=f"{btn_key}_skip"):
                        _log_decision(ticker, "skip", sig.get("strategy", ""), "Skipped from dashboard")
                        st.warning(f"Logged SKIP for {ticker}")
    else:
        st.info("No stock signals today. Run the pipeline to generate signals.")

    st.divider()

    # ── Stock Intelligence ───────────────────────────────────────
    stock_intel = today_findings.get("stock_intelligence", {})

    if stock_intel:
        col_earn, col_breadth = st.columns(2)

        # Earnings Calendar
        earnings = stock_intel.get("upcoming_earnings", [])
        with col_earn:
            st.subheader("Earnings Calendar")
            if earnings:
                ear_rows = []
                for e in earnings[:8]:
                    timing = e.get("time", "")
                    timing_label = {"bmo": "Pre-Market", "amc": "After Close"}.get(timing, timing)
                    ear_rows.append({
                        "Ticker": e.get("ticker", ""),
                        "Date": e.get("date", ""),
                        "Timing": timing_label,
                        "Days": e.get("days_until", 0),
                    })
                st.dataframe(pd.DataFrame(ear_rows), use_container_width=True, hide_index=True)
            else:
                st.caption("No upcoming earnings for watched tickers.")

        # Market Breadth
        breadth = stock_intel.get("market_breadth", {})
        with col_breadth:
            st.subheader("Market Breadth")
            if breadth:
                b1, b2 = st.columns(2)
                b1.metric("A/D Ratio", f"{breadth.get('advance_decline_ratio', 0):.2f}")
                b2.metric("McClellan", f"{breadth.get('mcclellan_oscillator', 0):+.1f}")
                b1.metric("Above 200 SMA", f"{breadth.get('pct_above_200sma', 0):.0f}%")
                b2.metric("Above 50 SMA", f"{breadth.get('pct_above_50sma', 0):.0f}%")
                st.markdown(f"New Highs: {breadth.get('new_highs', 0)} | New Lows: {breadth.get('new_lows', 0)}")
            else:
                st.caption("No breadth data available.")

        # Sector Performance
        sectors = stock_intel.get("sector_performance", [])
        if sectors:
            st.subheader("Sector Performance")
            sec_rows = []
            for s in sectors[:10]:
                sec_rows.append({
                    "Sector": s.get("sector", "").replace("_", " ").title(),
                    "1D": f"{s.get('change_1d', 0):+.2f}%",
                    "1W": f"{s.get('change_1w', 0):+.2f}%",
                    "1M": f"{s.get('change_1m', 0):+.2f}%",
                })
            st.dataframe(pd.DataFrame(sec_rows), use_container_width=True, hide_index=True)

        # Insider Trades
        insiders = stock_intel.get("insider_trades", [])
        if insiders:
            with st.expander("Insider Trading Activity"):
                buys = [t for t in insiders if t.get("transaction_type") == "buy"]
                sells = [t for t in insiders if t.get("transaction_type") == "sell"]
                st.markdown(f"**Buys:** {len(buys)} | **Sells:** {len(sells)}")
                insider_rows = []
                for t in insiders[:10]:
                    insider_rows.append({
                        "Ticker": t.get("ticker", ""),
                        "Name": t.get("insider_name", ""),
                        "Type": t.get("transaction_type", "").upper(),
                        "Shares": f"{t.get('shares', 0):,}",
                        "Value": f"${t.get('value', 0):,.0f}",
                        "Date": t.get("date", ""),
                    })
                st.dataframe(pd.DataFrame(insider_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No stock intelligence data. Run the pipeline with the stocks module enabled.")


elif page == "Crypto":
    st.title("🪙 Crypto")

    crypto_intel = today_findings.get("crypto_intelligence", {})

    if not crypto_intel:
        st.info("No crypto data. Run the pipeline with the crypto module enabled.")
    else:
        # ── Fear & Greed + Dominance ─────────────────────────────
        col_fg, col_dom = st.columns(2)

        fg = crypto_intel.get("fear_greed", {})
        with col_fg:
            st.subheader("Fear & Greed Index")
            if fg:
                fg_val = fg.get("value", 0)
                fg_class = fg.get("classification", "N/A")
                if fg_val <= 25:
                    color = "🔴"
                elif fg_val <= 45:
                    color = "🟠"
                elif fg_val <= 55:
                    color = "🟡"
                else:
                    color = "🟢"
                st.markdown(f"### {color} {fg_val}/100 — {fg_class}")
                st.progress(fg_val / 100)

                fg_hist = fg.get("history_7d", [])
                if fg_hist and len(fg_hist) > 1:
                    vals = []
                    for h in fg_hist[-7:]:
                        vals.append(h.get("value", h) if isinstance(h, dict) else int(h))
                    fig = go.Figure(go.Scatter(y=vals, mode="lines+markers",
                                               line=dict(color="orange", width=2), marker=dict(size=4)))
                    fig.update_layout(height=120, margin=dict(l=0, r=0, t=5, b=0),
                                      showlegend=False, yaxis=dict(range=[0, 100]), xaxis=dict(showticklabels=False))
                    st.plotly_chart(fig, use_container_width=True)
                    st.caption("7-day history")
            else:
                st.caption("No fear & greed data.")

        dom = crypto_intel.get("dominance", {})
        with col_dom:
            st.subheader("Market Dominance")
            if dom:
                d1, d2 = st.columns(2)
                d1.metric("BTC", f"{dom.get('btc_dominance', 0):.1f}%")
                d2.metric("ETH", f"{dom.get('eth_dominance', 0):.1f}%")
                total_cap = dom.get("total_market_cap", 0)
                if total_cap:
                    st.metric("Total Market Cap", f"${total_cap / 1e12:.2f}T")
            else:
                st.caption("No dominance data.")

        st.divider()

        # ── Funding Rates & Open Interest ────────────────────────
        st.subheader("Derivatives")
        col_fund, col_oi = st.columns(2)

        btc_f = crypto_intel.get("btc_funding", {})
        eth_f = crypto_intel.get("eth_funding", {})
        with col_fund:
            st.markdown("**Funding Rates**")
            if btc_f:
                rate = btc_f.get("rate", 0)
                direction = btc_f.get("direction", "neutral")
                col_fund.metric("BTC Funding", f"{rate:.4%}", direction.replace("_", " "))
            if eth_f:
                rate = eth_f.get("rate", 0)
                direction = eth_f.get("direction", "neutral")
                col_fund.metric("ETH Funding", f"{rate:.4%}", direction.replace("_", " "))

        btc_oi = crypto_intel.get("btc_open_interest", {})
        eth_oi = crypto_intel.get("eth_open_interest", {})
        with col_oi:
            st.markdown("**Open Interest**")
            if btc_oi:
                oi_usd = btc_oi.get("open_interest_usd", 0)
                col_oi.metric("BTC OI", f"${oi_usd / 1e9:.2f}B",
                              f"{btc_oi.get('change_24h_pct', 0):+.1f}% 24h")
            if eth_oi:
                oi_usd = eth_oi.get("open_interest_usd", 0)
                col_oi.metric("ETH OI", f"${oi_usd / 1e9:.2f}B",
                              f"{eth_oi.get('change_24h_pct', 0):+.1f}% 24h")

        st.divider()

        # ── DeFi, Gas, Whale, Stablecoins ────────────────────────
        col_defi, col_whale = st.columns(2)

        defi = crypto_intel.get("defi", {})
        gas = crypto_intel.get("gas", {})
        with col_defi:
            st.subheader("DeFi & Gas")
            if defi:
                st.metric("Total DeFi TVL", f"${defi.get('total_tvl', 0) / 1e9:.1f}B")
                top_protocols = defi.get("top_protocols", [])
                if top_protocols:
                    proto_rows = []
                    for p in top_protocols[:5]:
                        proto_rows.append({
                            "Protocol": p.get("name", ""),
                            "TVL": f"${p.get('tvl', 0) / 1e9:.2f}B",
                            "1d": f"{p.get('change_1d', p.get('change_24h', 0)):+.1f}%",
                        })
                    st.dataframe(pd.DataFrame(proto_rows), use_container_width=True, hide_index=True)
            if gas:
                gas_price = gas.get("gas_price_gwei", 0)
                st.metric("ETH Gas", f"{gas_price:.2f} Gwei")

        whale = crypto_intel.get("whale_activity", {})
        with col_whale:
            st.subheader("Whale Activity")
            if whale:
                txns = whale.get("large_txns_24h", 0)
                flow = whale.get("net_exchange_flow", "unknown")
                flow_icon = {"inflow": "🔴", "outflow": "🟢", "neutral": "🟡"}.get(flow, "⚪")
                st.metric("Large Txns (24h)", f"{txns:,}")
                st.markdown(f"**Net Exchange Flow:** {flow_icon} {flow.title()}")

                liq = crypto_intel.get("liquidation_estimate", {})
                if liq:
                    st.metric("Liquidation Risk", liq.get("risk_level", "N/A").upper())
                    st.caption(f"Bias: {liq.get('bias', 'N/A')}")
            else:
                st.caption("No whale data available.")

        # Stablecoins & Correlations
        stable = crypto_intel.get("stablecoin_supply", {})
        corr = crypto_intel.get("correlations", {})
        if stable or corr:
            with st.expander("Stablecoins & Correlations"):
                if stable:
                    total_stable = stable.get("total_stablecoin_cap", 0)
                    st.markdown(f"**Stablecoin Supply:** ${total_stable / 1e9:.1f}B (USDT dominance: {stable.get('usdt_dominance', 0):.1f}%)")
                if corr and corr.get("pairs"):
                    st.markdown(f"**Correlations ({corr.get('period_days', 30)}d):**")
                    for pair, val in sorted(corr["pairs"].items()):
                        strength = "strong" if abs(val) > 0.7 else "moderate" if abs(val) > 0.4 else "weak"
                        st.markdown(f"- {pair}: {val:+.3f} ({strength})")

        # Crypto signals from today's findings
        all_signals = today_findings.get("signals", [])
        crypto_signals = [s for s in all_signals if s.get("ticker", "") in {"BTCUSD", "ETHUSD", "BTCUSDT", "ETHUSDT"}]
        if crypto_signals:
            st.divider()
            st.subheader("Crypto Signals")
            for sig in crypto_signals:
                action = sig.get("action", "skip")
                ticker = sig.get("ticker", "")
                action_icon = {"enter_now": "🟢", "watch": "🟡"}.get(action, "⚪")
                st.markdown(
                    f"{action_icon} **{ticker}** — {sig.get('signal', '')} (Score: {sig.get('score', 0):.2f}) · "
                    f"{sig.get('strategy', '').replace('_', ' ').title()} · "
                    f"Entry: ${sig.get('entry_price', 0):,.2f}"
                )


elif page == "Portfolio":
    st.title("💼 Paper Trading Simulation")
    st.caption(
        "Track your $500 paper portfolio in real time. The agent recommends trades daily "
        "using 5 strategies — this page shows how those recommendations perform so you can "
        "evaluate results before committing real money."
    )

    if isinstance(performance, dict) and performance:
        balance = performance.get("virtual_balance", 500)
        starting = performance.get("starting_balance", 500)
        pnl = balance - starting
        total_ret = ((balance - starting) / starting * 100) if starting else 0
        total_trades = performance.get("total_trades", 0)
        wins = performance.get("wins", 0)
        losses = performance.get("losses", 0)
        win_rate = performance.get("win_rate", 0)

        # ── ROI & Key Metrics ─────────────────────────────────────
        st.subheader("Return on Investment")

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Starting Capital", f"${starting:.2f}")
        m2.metric("Current Balance", f"${balance:.2f}", f"{pnl:+.2f}")
        m3.metric("ROI", f"{total_ret:+.2f}%")
        m4.metric("Win Rate", f"{win_rate * 100:.1f}%")
        m5.metric("Total Trades", f"{total_trades}")

        # ROI context for learners
        if total_trades > 0:
            if total_ret > 0:
                st.success(
                    f"Your paper portfolio is up **${pnl:+.2f}** ({total_ret:+.2f}%) from the "
                    f"${starting:.0f} starting balance after {total_trades} trades."
                )
            elif total_ret < 0:
                st.warning(
                    f"Your paper portfolio is down **${pnl:+.2f}** ({total_ret:+.2f}%). "
                    f"This is normal during learning — review which strategies are losing below."
                )
            else:
                st.info("Portfolio is flat so far. Trades are being executed — results will show soon.")

        st.divider()

        # ── Daily P&L Progression ─────────────────────────────────
        st.subheader("Daily P&L Progression")
        st.caption("How your balance changes day by day — the goal is a steady upward trend.")

        if not trades_df.empty and "pnl" in trades_df.columns and "exit_date" in trades_df.columns:
            daily_df = trades_df.copy()
            daily_df["pnl"] = daily_df["pnl"].astype(float)
            daily_df["exit_date"] = pd.to_datetime(daily_df["exit_date"], errors="coerce")
            daily_df = daily_df.dropna(subset=["exit_date"])

            if not daily_df.empty:
                daily_pnl = daily_df.groupby(daily_df["exit_date"].dt.date).agg(
                    day_pnl=("pnl", "sum"),
                    trades=("pnl", "count"),
                    wins=("pnl", lambda x: (x > 0).sum()),
                ).reset_index()
                daily_pnl.columns = ["Date", "Day P&L", "Trades", "Wins"]
                daily_pnl = daily_pnl.sort_values("Date")
                daily_pnl["Balance"] = daily_pnl["Day P&L"].cumsum() + starting
                daily_pnl["Cumulative P&L"] = daily_pnl["Day P&L"].cumsum()
                daily_pnl["ROI %"] = (daily_pnl["Balance"] - starting) / starting * 100
                daily_pnl["Date"] = pd.to_datetime(daily_pnl["Date"])

                # Balance over time chart
                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=daily_pnl["Date"], y=daily_pnl["Balance"],
                    mode="lines+markers", name="Balance",
                    line=dict(color="blue", width=2), marker=dict(size=5),
                ))
                fig.add_hline(y=starting, line_dash="dash", line_color="gray",
                              annotation_text=f"Starting ${starting:.0f}")
                fig.update_layout(
                    height=300, margin=dict(t=30, b=20),
                    title="Portfolio Balance Over Time",
                    xaxis_title="Date", yaxis_title="Balance ($)",
                    hovermode="x unified",
                )
                st.plotly_chart(fig, use_container_width=True)

                # Daily P&L bar chart
                colors = ["green" if v >= 0 else "red" for v in daily_pnl["Day P&L"]]
                fig_daily = go.Figure(go.Bar(
                    x=daily_pnl["Date"], y=daily_pnl["Day P&L"],
                    marker_color=colors, name="Daily P&L",
                ))
                fig_daily.update_layout(
                    height=200, margin=dict(t=30, b=20),
                    title="Daily Gains / Losses",
                    xaxis_title="Date", yaxis_title="P&L ($)",
                )
                st.plotly_chart(fig_daily, use_container_width=True)

                # Daily summary table
                with st.expander("Daily Breakdown"):
                    display_daily = daily_pnl.copy()
                    display_daily["Date"] = display_daily["Date"].dt.strftime("%Y-%m-%d")
                    display_daily["Day P&L"] = display_daily["Day P&L"].apply(lambda x: f"${x:+.2f}")
                    display_daily["Balance"] = display_daily["Balance"].apply(lambda x: f"${x:.2f}")
                    display_daily["ROI %"] = display_daily["ROI %"].apply(lambda x: f"{x:+.2f}%")
                    st.dataframe(
                        display_daily[["Date", "Day P&L", "Balance", "ROI %", "Trades", "Wins"]].iloc[::-1],
                        use_container_width=True, hide_index=True,
                    )
        else:
            st.info("No completed trades yet. Daily P&L will appear after the first trade closes.")

        st.divider()

        # ── Strategy Accuracy ─────────────────────────────────────
        st.subheader("Strategy Recommendation Accuracy")
        st.caption(
            "How often each strategy's 'enter now' recommendations resulted in a profit. "
            "A strategy with >50% accuracy and positive P&L is doing its job."
        )

        if not trades_df.empty and "strategy" in trades_df.columns and "pnl" in trades_df.columns:
            acc_df = trades_df.copy()
            acc_df["pnl"] = acc_df["pnl"].astype(float)
            acc_df["profitable"] = acc_df["pnl"] > 0

            strat_acc = acc_df.groupby("strategy").agg(
                total=("pnl", "count"),
                wins=("profitable", "sum"),
                total_pnl=("pnl", "sum"),
                avg_pnl=("pnl", "mean"),
            ).reset_index()
            strat_acc["accuracy"] = (strat_acc["wins"] / strat_acc["total"] * 100).round(1)
            strat_acc = strat_acc.sort_values("accuracy", ascending=False)

            # Accuracy bar chart
            fig_acc = go.Figure()
            fig_acc.add_trace(go.Bar(
                x=strat_acc["strategy"].str.replace("_", " ").str.title(),
                y=strat_acc["accuracy"],
                marker_color=["green" if a >= 50 else "orange" if a >= 40 else "red"
                               for a in strat_acc["accuracy"]],
                text=strat_acc["accuracy"].apply(lambda x: f"{x:.0f}%"),
                textposition="auto",
            ))
            fig_acc.add_hline(y=50, line_dash="dash", line_color="gray",
                              annotation_text="50% breakeven line")
            fig_acc.update_layout(
                height=250, margin=dict(t=30, b=20),
                title="Win Rate by Strategy",
                xaxis_title="Strategy", yaxis_title="Accuracy %",
                yaxis=dict(range=[0, 100]),
            )
            st.plotly_chart(fig_acc, use_container_width=True)

            # Strategy accuracy table
            acc_rows = []
            for _, row in strat_acc.iterrows():
                verdict = "Profitable" if row["total_pnl"] > 0 else "Losing"
                acc_rows.append({
                    "Strategy": row["strategy"].replace("_", " ").title(),
                    "Trades": int(row["total"]),
                    "Wins": int(row["wins"]),
                    "Accuracy": f"{row['accuracy']:.0f}%",
                    "Total P&L": f"${row['total_pnl']:+.2f}",
                    "Avg P&L": f"${row['avg_pnl']:+.2f}",
                    "Verdict": verdict,
                })
            st.dataframe(pd.DataFrame(acc_rows), use_container_width=True, hide_index=True)
        else:
            st.info("No trades yet. Strategy accuracy will appear after trades are completed.")

        st.divider()

        # ── Open Positions ────────────────────────────────────────
        st.subheader("Open Positions")
        if positions_data:
            pos_rows = []
            for pos in positions_data:
                pnl_val = pos.get("unrealized_pnl", 0)
                trail = f"${pos['trailing_stop']:.4f}" if pos.get("trailing_stop", 0) > 0 else "—"
                pos_rows.append({
                    "Ticker": pos["ticker"],
                    "Direction": pos["direction"],
                    "Strategy": pos.get("strategy", ""),
                    "Entry": f"${pos['entry_price']:.2f}",
                    "P&L": f"${pnl_val:+.2f}",
                    "Day": f"{pos.get('days_held', 0)}/{pos.get('max_hold_days', 10)}",
                    "SL": f"${pos['stop_loss']:.4f}",
                    "TP": f"${pos['take_profit']:.4f}",
                    "Trail": trail,
                })
            st.dataframe(pd.DataFrame(pos_rows), use_container_width=True, hide_index=True)
        else:
            st.caption("No open positions.")

        st.divider()

        # ── Trade History ─────────────────────────────────────────
        st.subheader("Recent Trades")
        if not trades_df.empty:
            display_cols = [c for c in ["ticker", "direction", "strategy", "entry_price", "exit_price",
                                         "pnl", "exit_reason", "exit_date"] if c in trades_df.columns]
            st.dataframe(trades_df[display_cols].tail(10).iloc[::-1], use_container_width=True, hide_index=True)
        else:
            st.caption("No trade history yet.")

        st.markdown(
            f"**Expectancy:** ${performance.get('expectancy', 0):.2f}/trade · "
            f"**Avg R:** {performance.get('avg_r_multiple', 0):.2f} · "
            f"**Max Drawdown:** {performance.get('max_drawdown_pct', 0):.1f}%"
        )

        st.divider()

        # ── Go Live Readiness ─────────────────────────────────────
        st.subheader("Go Live Readiness")
        st.caption(
            "Paper trade for at least 30 days before considering real money. "
            "This checklist helps you evaluate whether the system is ready."
        )

        # Calculate readiness criteria
        days_active = 0
        if not trades_df.empty and "entry_date" in trades_df.columns:
            dates = pd.to_datetime(trades_df["entry_date"], errors="coerce").dropna()
            if not dates.empty:
                days_active = (date.today() - dates.min().date()).days

        checks = {
            "30+ days of paper trading": days_active >= 30,
            "20+ completed trades": total_trades >= 20,
            "Win rate above 45%": win_rate > 0.45,
            "Positive total P&L": pnl > 0,
            "Max drawdown under 15%": performance.get("max_drawdown_pct", 100) < 15,
            "Profit factor above 1.2": performance.get("profit_factor", 0) > 1.2,
        }

        passed = sum(checks.values())
        total_checks = len(checks)

        col_ready, col_progress = st.columns([2, 1])

        with col_ready:
            for label, ok in checks.items():
                icon = "✅" if ok else "⬜"
                st.markdown(f"{icon} {label}")

        with col_progress:
            pct = passed / total_checks
            if pct >= 0.8:
                st.success(f"**{passed}/{total_checks} passed**\n\nLooking good! Review results carefully before going live.")
            elif pct >= 0.5:
                st.warning(f"**{passed}/{total_checks} passed**\n\nGetting there — keep paper trading.")
            else:
                st.info(f"**{passed}/{total_checks} passed**\n\nStill early — let the simulation run longer.")

            st.metric("Days Active", f"{days_active}/30")

        # Learning tips
        with st.expander("What to look for before going live"):
            st.markdown("""
**Consistency matters more than big wins:**
- A steady equity curve with small gains is better than volatile swings
- Watch for strategies that win often but lose big (low R:R)
- Check that your max drawdown stays manageable

**Key metrics to understand:**
- **Win Rate** — % of trades that made money. Above 45% is good for most strategies
- **Profit Factor** — gross profits / gross losses. Above 1.2 means you earn more than you lose
- **Expectancy** — average $ per trade. Positive = the system makes money over time
- **Max Drawdown** — largest peak-to-trough decline. Keep under 15% for safety
- **Sharpe Ratio** — risk-adjusted return. Above 1.0 is acceptable, 2.0+ is excellent

**When you're ready:**
1. Start with a small real account (same $500)
2. Use the same strategies the paper trader validated
3. Never risk more than 2% per trade
4. Keep running paper trading alongside real trading to compare
""")

    else:
        st.info(
            "No portfolio data yet. Run the pipeline to start paper trading with a $500 virtual balance. "
            "The system will automatically enter and exit trades based on its strategy recommendations."
        )


elif page == "Performance":
    st.title("📐 Performance & Analytics")

    # ── Portfolio Analytics ───────────────────────────────────────
    if portfolio_analytics:
        st.subheader("Risk Metrics")
        pa1, pa2, pa3, pa4 = st.columns(4)
        pa1.metric("Sharpe Ratio", f"{portfolio_analytics.get('sharpe_ratio', 0):.2f}")
        pa2.metric("Sortino Ratio", f"{portfolio_analytics.get('sortino_ratio', 0):.2f}")
        pa3.metric("Calmar Ratio", f"{portfolio_analytics.get('calmar_ratio', 0):.2f}")
        pa4.metric("Max Drawdown", f"{portfolio_analytics.get('max_drawdown_pct', 0):.1f}%")

        pa5, pa6, pa7, pa8 = st.columns(4)
        pa5.metric("Current DD", f"{portfolio_analytics.get('current_drawdown_pct', 0):.1f}%")
        pa6.metric("Avg Hold Days", f"{portfolio_analytics.get('avg_hold_days', 0):.1f}")
        pa7.metric("Best Day", f"${portfolio_analytics.get('best_day_pnl', 0):+.2f}")
        pa8.metric("Worst Day", f"${portfolio_analytics.get('worst_day_pnl', 0):+.2f}")

        # Equity curve with drawdown
        equity = portfolio_analytics.get("equity_curve", [])
        if equity and len(equity) > 1:
            eq_df = pd.DataFrame(equity)
            eq_df["trade_num"] = range(1, len(eq_df) + 1)

            fig = go.Figure()
            fig.add_trace(go.Scatter(x=eq_df["trade_num"], y=eq_df["balance"],
                                      mode="lines", name="Balance", line=dict(color="blue", width=2)))
            fig.add_trace(go.Scatter(x=eq_df["trade_num"], y=eq_df["peak"],
                                      mode="lines", name="Peak", line=dict(color="gray", width=1, dash="dash")))
            fig.update_layout(height=250, margin=dict(t=30, b=20), title="Equity Curve & Peak",
                              xaxis_title="Trade #", yaxis_title="Balance ($)")
            st.plotly_chart(fig, use_container_width=True)

            fig_dd = go.Figure()
            fig_dd.add_trace(go.Scatter(x=eq_df["trade_num"], y=eq_df["drawdown_pct"],
                                         mode="lines", fill="tozeroy", name="Drawdown",
                                         line=dict(color="red", width=1)))
            fig_dd.update_layout(height=150, margin=dict(t=20, b=20), title="Drawdown %",
                                 xaxis_title="Trade #", yaxis_title="DD %")
            st.plotly_chart(fig_dd, use_container_width=True)

        st.divider()

        # Monthly returns
        monthly = portfolio_analytics.get("monthly_returns", {})
        if monthly:
            st.subheader("Monthly Returns")
            month_df = pd.DataFrame([{"Month": k, "P&L": v} for k, v in monthly.items()])
            fig = px.bar(month_df, x="Month", y="P&L", color="P&L",
                         color_continuous_scale=["red", "gray", "green"])
            fig.update_layout(height=200, margin=dict(t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

        # Direction stats
        dir_stats = portfolio_analytics.get("direction_stats", {})
        if dir_stats:
            st.subheader("Long vs Short")
            for dir_name, stats in dir_stats.items():
                st.markdown(
                    f"**{dir_name}**: {stats.get('total_trades', 0)} trades, "
                    f"{stats.get('win_rate', 0):.0%} win rate, "
                    f"${stats.get('total_pnl', 0):+.2f} total P&L"
                )
    else:
        st.info("No analytics data. Run the pipeline first.")

    st.divider()

    # ── Strategy Performance ─────────────────────────────────────
    if not trades_df.empty and "strategy" in trades_df.columns:
        st.subheader("Strategy Performance")
        strat_metrics = performance.get("strategy_metrics", {}) if isinstance(performance, dict) else {}
        if strat_metrics:
            rows = []
            for strat, m in strat_metrics.items():
                rows.append({
                    "Strategy": strat.replace("_", " ").title(),
                    "Trades": m.get("total_trades", 0),
                    "Win Rate": f"{m.get('win_rate', 0) * 100:.0f}%",
                    "P&L": f"${m.get('pnl', 0):+.2f}",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            chart_data = pd.DataFrame([
                {"Strategy": k.replace("_", " ").title(), "P&L": v.get("pnl", 0)}
                for k, v in strat_metrics.items()
            ])
            fig = px.bar(chart_data, x="Strategy", y="P&L", color="P&L",
                         color_continuous_scale=["red", "gray", "green"])
            fig.update_layout(height=250, margin=dict(t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

        # Exit reasons
        if "exit_reason" in trades_df.columns:
            st.subheader("Exit Reasons")
            exit_counts = trades_df["exit_reason"].value_counts()
            fig = px.pie(values=exit_counts.values, names=exit_counts.index, height=300)
            fig.update_layout(margin=dict(t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

    # ── Behavioral Summary ───────────────────────────────────────
    behavior_log = []
    if behavior_log_path.exists():
        behavior_log = json.loads(behavior_log_path.read_text())

    if behavior_log:
        st.divider()
        st.subheader("Behavioral Summary (7 days)")
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        recent = [e for e in behavior_log if e.get("date", "") >= cutoff]
        entries = len([e for e in recent if e.get("action") == "entry"])
        skips = len([e for e in recent if e.get("action") == "skip"])
        plan_aligned = len([e for e in recent if e.get("plan_aligned", True)])
        adherence = plan_aligned / len(recent) if recent else 1.0
        disciplines = [e["discipline_rating"] for e in recent if e.get("discipline_rating")]
        avg_discipline = sum(disciplines) / len(disciplines) if disciplines else 0

        bc1, bc2, bc3 = st.columns(3)
        bc1.metric("Entries", entries)
        bc2.metric("Plan Adherence", f"{adherence:.0%}")
        bc3.metric("Avg Discipline", f"{avg_discipline:.1f}/5" if avg_discipline > 0 else "N/A")


elif page == "System":
    st.title("⚙️ System")

    # API Health
    st.subheader("API Health")
    if api_health:
        if isinstance(api_health, list):
            health_rows = []
            for h in api_health:
                state = h.get("state", "unknown")
                icon = {"closed": "🟢", "open": "🔴", "half_open": "🟡"}.get(state, "⚪")
                health_rows.append({
                    "API": h.get("name", ""),
                    "Status": f"{icon} {state.upper()}",
                    "Calls": h.get("total_calls", 0),
                    "Failures": h.get("failures", 0),
                    "Fail Rate": f"{h.get('failure_rate', 0):.0%}",
                })
            st.dataframe(pd.DataFrame(health_rows), use_container_width=True, hide_index=True)
        elif isinstance(api_health, dict):
            for api, status in api_health.items():
                if isinstance(status, dict):
                    state = status.get("state", status.get("status", "unknown"))
                    failures = status.get("failure_count", status.get("failures", 0))
                    icon = "🟢" if state in ("closed", "ok", "healthy") else "🔴"
                    st.markdown(f"{icon} **{api}:** {state}" + (f" ({failures} failures)" if failures else ""))
                else:
                    st.markdown(f"**{api}:** {status}")
    else:
        st.caption("No API health data. Run the pipeline first.")

    st.divider()

    # Configuration overview
    st.subheader("Configuration")

    dep = prefs.get("deployment", {})
    sched = prefs.get("schedule", {})

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Deployment**")
        st.markdown(f"- Mode: `{dep.get('mode', 'local')}`")
        st.markdown(f"- Push data: `{dep.get('push_data_after_run', False)}`")
        st.markdown(f"- Telegram: `{prefs.get('telegram', {}).get('mode', 'polling')}`")
        repo = dep.get("github_repo", "")
        if repo:
            st.markdown(f"- GitHub: `{repo}`")

    with c2:
        st.markdown("**Schedule**")
        st.markdown(f"- Timezone: `{sched.get('timezone', 'US/Eastern')}`")
        st.markdown(f"- Morning: `{sched.get('morning_run', '09:00')}`")
        st.markdown(f"- Afternoon: `{sched.get('afternoon_run', '15:00')}`")
        if modules.get("crypto", False):
            st.markdown(f"- Crypto AM: `{sched.get('crypto_morning', '08:00')}`")
            st.markdown(f"- Crypto PM: `{sched.get('crypto_evening', '20:00')}`")

    st.divider()

    # Regime history
    if regime_daily_log:
        st.subheader("Regime History")
        reg_df = pd.DataFrame(regime_daily_log)
        if "date" in reg_df.columns and "regime" in reg_df.columns:
            st.dataframe(reg_df.tail(14).iloc[::-1], use_container_width=True, hide_index=True)


# ── Auto-refresh ─────────────────────────────────────────────────

refresh_seconds = config.get("auto_refresh_seconds", 60)
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=refresh_seconds * 1000, key="data_refresh")
except ImportError:
    pass

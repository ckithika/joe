"""Tier 1 Research Agent — Streamlit Monitoring Dashboard."""

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

st.set_page_config(page_title="Tier 1 Research Agent", page_icon="📊", layout="wide")

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


config = load_config()
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

# Load new data sources
today_findings = load_json(FINDINGS_DIR / f"{date.today()}.json")
if not isinstance(today_findings, dict):
    today_findings = {}
portfolio_analytics = load_json(DATA_DIR / "portfolio_analytics.json")
if not isinstance(portfolio_analytics, dict):
    portfolio_analytics = {}
api_health = load_json(DATA_DIR / "api_health.json")
if not isinstance(api_health, list):
    api_health = []


# ── Header ───────────────────────────────────────────────────────


st.title("📊 Tier 1 Research Agent")
timestamp = regime_data.get("timestamp", "No data yet") if isinstance(regime_data, dict) else "No data yet"
st.caption(f"Last updated: {timestamp}")


# ── Section 1: Market Session Timers ─────────────────────────────


def get_session_status(session_config: dict) -> dict:
    """Determine if a market session is open/closed and countdown."""
    tz_name = session_config.get("timezone", "UTC")
    tz = pytz.timezone(tz_name)
    now = datetime.now(tz)

    if session_config.get("always_open"):
        return {"status": "24/7", "color": "green", "note": session_config.get("note", "")}

    days = session_config.get("days", [0, 1, 2, 3, 4])
    if now.weekday() not in days:
        return {"status": "CLOSED", "color": "red", "note": "Weekend"}

    # Check holidays
    holidays = config.get("holidays_2026", [])
    if now.strftime("%Y-%m-%d") in holidays:
        return {"status": "CLOSED", "color": "red", "note": "Holiday"}

    regular_open = session_config.get("regular_open", "09:30")
    regular_close = session_config.get("regular_close", "16:00")
    premarket_open = session_config.get("premarket_open")
    afterhours_close = session_config.get("afterhours_close")

    open_h, open_m = map(int, regular_open.split(":"))
    close_h, close_m = map(int, regular_close.split(":"))
    open_time = now.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    close_time = now.replace(hour=close_h, minute=close_m, second=0, microsecond=0)

    # Regular session
    if open_time <= now <= close_time:
        remaining = close_time - now
        hours, rem = divmod(int(remaining.total_seconds()), 3600)
        minutes = rem // 60
        return {
            "status": "OPEN",
            "color": "green",
            "note": f"Closes in {hours}h {minutes}m",
        }

    # After-hours session
    if afterhours_close:
        ah_h, ah_m = map(int, afterhours_close.split(":"))
        ah_time = now.replace(hour=ah_h, minute=ah_m, second=0, microsecond=0)
        if close_time < now <= ah_time:
            remaining = ah_time - now
            hours, rem = divmod(int(remaining.total_seconds()), 3600)
            minutes = rem // 60
            return {
                "status": "AFTER-HOURS",
                "color": "orange",
                "note": f"Ends in {hours}h {minutes}m",
            }

    # Pre-market session
    if premarket_open:
        pm_h, pm_m = map(int, premarket_open.split(":"))
        pm_time = now.replace(hour=pm_h, minute=pm_m, second=0, microsecond=0)
        if pm_time <= now < open_time:
            remaining = open_time - now
            hours, rem = divmod(int(remaining.total_seconds()), 3600)
            minutes = rem // 60
            return {
                "status": "PRE-MARKET",
                "color": "orange",
                "note": f"Regular in {hours}h {minutes}m",
            }

    # Closed — calculate time to next open
    if now > close_time:
        next_open = open_time + timedelta(days=1)
    else:
        next_open = open_time
    remaining = next_open - now
    hours, rem = divmod(int(remaining.total_seconds()), 3600)
    minutes = rem // 60
    return {
        "status": "CLOSED",
        "color": "red",
        "note": f"Opens in {hours}h {minutes}m",
    }


st.header("Market Sessions")
sessions = config.get("market_sessions", {})
if sessions:
    cols = st.columns(len(sessions))
    for i, (key, sess) in enumerate(sessions.items()):
        status = get_session_status(sess)
        with cols[i]:
            color_map = {"green": "🟢", "orange": "🟡", "red": "🔴"}
            icon = color_map.get(status["color"], "⚪")
            st.metric(
                label=sess.get("name", key),
                value=f"{icon} {status['status']}",
                delta=status["note"],
            )
else:
    st.info("No market session config found. Add sessions to config/dashboard.yaml.")


# ── Section 2: Regime & Risk ─────────────────────────────────────


st.header("Regime & Risk")
col_regime, col_risk = st.columns(2)

with col_regime:
    st.subheader("Market Regime")
    if isinstance(regime_data, dict) and regime_data:
        regime_name = regime_data.get("regime", "unknown").replace("_", " ").upper()
        confidence = regime_data.get("confidence", 0)
        st.markdown(f"### {regime_name}")
        st.progress(confidence, text=f"Confidence: {confidence:.0%}")
        st.markdown(
            f"**ADX:** {regime_data.get('adx', 0):.1f} · "
            f"**VIX:** {regime_data.get('vix', 0):.1f} · "
            f"**Breadth:** {regime_data.get('breadth', 0):.0f}%"
        )
        strategies = regime_data.get("active_strategies", [])
        if strategies:
            st.markdown(
                f"**Active:** {', '.join(s.replace('_', ' ').title() for s in strategies)}"
            )
        size_mod = regime_data.get("position_size_modifier", 1.0)
        st.markdown(f"**Position sizing:** {size_mod:.0%}")

        # VIX sparkline
        vix_hist = regime_data.get("vix_history", [])
        if vix_hist and len(vix_hist) > 2:
            fig = go.Figure(go.Scatter(y=vix_hist, mode="lines", name="VIX", line=dict(color="red", width=1)))
            fig.update_layout(height=100, margin=dict(l=0, r=0, t=15, b=0), title="VIX (30d)", title_font_size=10, showlegend=False, yaxis=dict(showticklabels=False), xaxis=dict(showticklabels=False))
            st.plotly_chart(fig, use_container_width=True)

        # ADX sparkline
        adx_hist = regime_data.get("adx_history", [])
        if adx_hist and len(adx_hist) > 2:
            fig = go.Figure(go.Scatter(y=adx_hist, mode="lines", name="ADX", line=dict(color="blue", width=1)))
            fig.update_layout(height=100, margin=dict(l=0, r=0, t=15, b=0), title="ADX (30d)", title_font_size=10, showlegend=False, yaxis=dict(showticklabels=False), xaxis=dict(showticklabels=False))
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No regime data. Run the agent first.")

with col_risk:
    st.subheader("Risk Grade")
    if isinstance(risk_data, dict) and risk_data:
        composite = risk_data.get("composite_score", 0)
        level = risk_data.get("risk_level", "unknown").upper()
        st.markdown(f"### {composite:.1f}/10 — {level}")
        st.progress(min(composite / 10, 1.0))

        dims = risk_data.get("dimensions", {})
        if dims:
            dim_df = pd.DataFrame(
                [{"Dimension": k.title(), "Score": v} for k, v in dims.items()]
            )
            fig = px.bar(
                dim_df,
                x="Dimension",
                y="Score",
                color="Score",
                color_continuous_scale=["green", "yellow", "red"],
                range_y=[0, 10],
                height=250,
            )
            fig.update_layout(showlegend=False, margin=dict(t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

        alerts = risk_data.get("alerts", [])
        max_alerts = config.get("max_alerts_displayed", 5)
        for alert in alerts[:max_alerts]:
            sev = alert.get("severity", "info").upper()
            st.markdown(f"**[{sev}]** {alert.get('message', '')}")
    else:
        st.info("No risk data. Run the agent first.")


# ── Section 3: Paper Portfolio ───────────────────────────────────


st.header("Paper Portfolio")

if isinstance(performance, dict) and performance:
    balance = performance.get("virtual_balance", 500)
    starting = performance.get("starting_balance", 500)
    pnl = balance - starting

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Balance", f"${balance:.2f}", f"{pnl:+.2f}")
    m2.metric("Win Rate", f"{performance.get('win_rate', 0) * 100:.1f}%")
    m3.metric("Profit Factor", f"{performance.get('profit_factor', 0):.2f}")
    m4.metric("Sharpe", f"{performance.get('sharpe_ratio', 0):.2f}")
    m5.metric(
        "Open Positions",
        f"{performance.get('open_positions', len(positions_data))}/3",
    )

    # Equity curve from trade history
    if not trades_df.empty and "pnl" in trades_df.columns:
        max_trades = config.get("equity_curve_trades", 100)
        recent_trades = trades_df.tail(max_trades).copy()
        recent_trades["cumulative_pnl"] = recent_trades["pnl"].astype(float).cumsum() + starting
        recent_trades["trade_num"] = range(1, len(recent_trades) + 1)

        fig = px.line(
            recent_trades,
            x="trade_num",
            y="cumulative_pnl",
            title="Equity Curve",
            labels={"trade_num": "Trade #", "cumulative_pnl": "Balance ($)"},
        )
        fig.add_hline(y=starting, line_dash="dash", line_color="gray", annotation_text="Starting Balance")
        fig.update_layout(height=300, margin=dict(t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

    # Open positions table
    if positions_data:
        st.subheader("Open Positions")
        pos_rows = []
        for pos in positions_data:
            pnl_val = pos.get("unrealized_pnl", 0)
            trail = f"${pos['trailing_stop']:.4f}" if pos.get("trailing_stop", 0) > 0 else "—"
            pos_rows.append(
                {
                    "Ticker": pos["ticker"],
                    "Direction": pos["direction"],
                    "Strategy": pos.get("strategy", ""),
                    "Entry": f"${pos['entry_price']:.2f}",
                    "P&L": f"${pnl_val:+.2f}",
                    "Day": f"{pos.get('days_held', 0)}/{pos.get('max_hold_days', 10)}",
                    "SL": f"${pos['stop_loss']:.4f}",
                    "TP": f"${pos['take_profit']:.4f}",
                    "Trail": trail,
                }
            )
        st.dataframe(pd.DataFrame(pos_rows), use_container_width=True, hide_index=True)

    # Performance summary
    st.markdown(
        f"**Expectancy:** ${performance.get('expectancy', 0):.2f}/trade · "
        f"**Avg R:** {performance.get('avg_r_multiple', 0):.2f} · "
        f"**Max Drawdown:** {performance.get('max_drawdown_pct', 0):.1f}% · "
        f"**Total Trades:** {performance.get('total_trades', 0)}"
    )
else:
    st.info("No performance data. Run the agent first.")


# ── Section 4: Today's Signals ───────────────────────────────────


st.header("Today's Signals")

signals = today_report.get("signals", [])
max_signals = config.get("max_signals_displayed", 5)

if signals:
    available_slots = 3 - len(positions_data)
    st.caption(f"{available_slots} slot{'s' if available_slots != 1 else ''} available")

    for sig in signals[:max_signals]:
        action = sig.get("action", "skip")
        direction = sig.get("direction", "")
        ticker = sig.get("ticker", "")
        score = sig.get("score", 0)
        signal_type = sig.get("signal", "NEUTRAL")

        # Risk grade info
        risk_grade = sig.get("risk_grade")
        risk_level = sig.get("risk_level", "")
        risk_tag = f" · Risk: {risk_grade:.1f} {risk_level.upper()}" if risk_grade is not None else ""

        with st.expander(
            f"#{sig.get('rank', '?')}  {ticker}  —  Score: {score:.2f}  [{signal_type}]{risk_tag}",
            expanded=(action == "enter_now"),
        ):
            st.markdown(f"**Strategy:** {sig.get('strategy_label', sig.get('strategy', ''))}")
            st.markdown(f"**Setup:** {sig.get('setup', '')}")

            if action == "enter_now":
                st.markdown(
                    f"**Plan:** {direction} @ ${sig.get('entry_price', 0):.2f} · "
                    f"SL: ${sig.get('stop_loss', 0):.2f} · "
                    f"TP: ${sig.get('take_profit', 0):.2f}"
                )
                st.markdown(f"**R:R** = 1:{sig.get('risk_reward', 0):.1f}")

                if risk_grade is not None:
                    st.markdown(f"**Risk Grade:** {risk_grade:.1f}/10 — {risk_level.upper()}")

                # Decision buttons
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

            elif action == "watchlist":
                st.markdown("**Watching** — not yet triggered")
else:
    st.info("No signals for today. Run the agent to generate today's report.")


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


# ── Section 5: Crypto Intelligence ───────────────────────────────


crypto_intel = today_findings.get("crypto_intelligence", {})
if crypto_intel:
    st.header("Crypto Intelligence")

    col_fg, col_dom, col_fund, col_oi = st.columns(4)

    # Fear & Greed
    fg = crypto_intel.get("fear_greed", {})
    if fg:
        fg_val = fg.get("value", 0)
        fg_class = fg.get("classification", "N/A")
        col_fg.metric("Fear & Greed", f"{fg_val}/100", fg_class)

        # Sparkline of 7-day history
        fg_hist = fg.get("history_7d", [])
        if fg_hist and len(fg_hist) > 1:
            fig = go.Figure(go.Scatter(y=[fg_val] + fg_hist, mode="lines+markers",
                                       line=dict(color="orange", width=2), marker=dict(size=4)))
            fig.update_layout(height=80, margin=dict(l=0, r=0, t=5, b=0),
                              showlegend=False, yaxis=dict(range=[0, 100], showticklabels=False),
                              xaxis=dict(showticklabels=False))
            col_fg.plotly_chart(fig, use_container_width=True)

    # Dominance
    dom = crypto_intel.get("dominance", {})
    if dom:
        col_dom.metric("BTC Dominance", f"{dom.get('btc_dominance', 0):.1f}%")
        col_dom.metric("ETH Dominance", f"{dom.get('eth_dominance', 0):.1f}%")
        total_cap = dom.get("total_market_cap", 0)
        if total_cap:
            col_dom.caption(f"Total: ${total_cap / 1e12:.2f}T")

    # Funding Rates
    btc_f = crypto_intel.get("btc_funding", {})
    eth_f = crypto_intel.get("eth_funding", {})
    if btc_f:
        rate = btc_f.get("rate", 0)
        direction = btc_f.get("direction", "neutral")
        col_fund.metric("BTC Funding", f"{rate:.4%}", direction.replace("_", " "))
    if eth_f:
        rate = eth_f.get("rate", 0)
        direction = eth_f.get("direction", "neutral")
        col_fund.metric("ETH Funding", f"{rate:.4%}", direction.replace("_", " "))

    # Open Interest
    btc_oi = crypto_intel.get("btc_open_interest", {})
    eth_oi = crypto_intel.get("eth_open_interest", {})
    if btc_oi:
        oi_usd = btc_oi.get("open_interest_usd", 0)
        col_oi.metric("BTC Open Interest", f"${oi_usd / 1e9:.2f}B",
                      f"{btc_oi.get('change_24h_pct', 0):+.1f}% 24h")
    if eth_oi:
        oi_usd = eth_oi.get("open_interest_usd", 0)
        col_oi.metric("ETH Open Interest", f"${oi_usd / 1e9:.2f}B",
                      f"{eth_oi.get('change_24h_pct', 0):+.1f}% 24h")

    # Tier 2 & 3 in expandable section
    with st.expander("Advanced Crypto Metrics (Tier 2 & 3)"):
        t2_col1, t2_col2, t2_col3 = st.columns(3)

        # Stablecoin Supply
        stable = crypto_intel.get("stablecoin_supply", {})
        if stable:
            total_stable = stable.get("total_stablecoin_cap", 0)
            t2_col1.metric("Stablecoin Supply", f"${total_stable / 1e9:.1f}B")
            t2_col1.caption(f"USDT dominance: {stable.get('usdt_dominance', 0):.1f}%")

        # Hash Rate
        hr = crypto_intel.get("hash_rate", {})
        if hr:
            t2_col2.metric("BTC Hash Rate", f"{hr.get('hash_rate', 0):,.1f} TH/s")
            t2_col2.caption(f"Block: {hr.get('block_height', 0):,}")

        # Liquidation
        liq = crypto_intel.get("liquidation_estimate", {})
        if liq:
            t2_col3.metric("Liquidation Risk", liq.get("risk_level", "N/A").upper())
            t2_col3.caption(f"Bias: {liq.get('bias', 'N/A')}")

        # DeFi
        defi = crypto_intel.get("defi", {})
        if defi:
            st.markdown(f"**DeFi TVL:** ${defi.get('total_tvl', 0) / 1e9:,.1f}B | "
                        f"ETH TVL: ${defi.get('eth_tvl', 0) / 1e9:,.1f}B")
            top_protocols = defi.get("top_protocols", [])
            if top_protocols:
                proto_rows = []
                for p in top_protocols[:5]:
                    proto_rows.append({
                        "Protocol": p.get("name", ""),
                        "TVL": f"${p.get('tvl', 0) / 1e9:.2f}B",
                        "1d Change": f"{p.get('change_1d', 0):+.1f}%",
                    })
                st.dataframe(pd.DataFrame(proto_rows), use_container_width=True, hide_index=True)

        # Gas
        gas = crypto_intel.get("gas", {})
        if gas:
            gas_price = gas.get("gas_price_gwei", 0)
            fmt = ".1f" if gas_price >= 1 else ".3f"
            st.markdown(f"**ETH Gas:** {gas_price:{fmt}} Gwei "
                        f"(base: {gas.get('base_fee_gwei', 0):{fmt}}, "
                        f"tip: {gas.get('priority_fee_gwei', 0):{fmt}})")

        # Correlations
        corr = crypto_intel.get("correlations", {})
        if corr and corr.get("pairs"):
            st.markdown(f"**Correlations ({corr.get('period_days', 30)}d):**")
            for pair, val in sorted(corr["pairs"].items()):
                strength = "strong" if abs(val) > 0.7 else "moderate" if abs(val) > 0.4 else "weak"
                st.markdown(f"- {pair}: {val:+.3f} ({strength})")


# ── Section 6: Stock Intelligence ────────────────────────────────


stock_intel = today_findings.get("stock_intelligence", {})
if stock_intel:
    st.header("Stock Intelligence")

    col_earn, col_breadth = st.columns(2)

    # Earnings Calendar
    earnings = stock_intel.get("upcoming_earnings", [])
    with col_earn:
        st.subheader("Upcoming Earnings")
        if earnings:
            ear_rows = []
            for e in earnings[:8]:
                timing = e.get("time", "")
                timing_label = {"bmo": "Pre-Market", "amc": "After Close"}.get(timing, timing)
                eps = f"${e.get('estimate_eps', 0):.2f}" if e.get("estimate_eps") else "N/A"
                ear_rows.append({
                    "Ticker": e.get("ticker", ""),
                    "Date": e.get("date", ""),
                    "Timing": timing_label,
                    "Days": e.get("days_until", 0),
                    "Est. EPS": eps,
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

    # Options Flow & Sector Performance in expandable
    with st.expander("Options Flow & Sectors"):
        opt_col, sec_col = st.columns(2)

        options = stock_intel.get("options_flow", {})
        if options:
            with opt_col:
                st.markdown("**Options Flow**")
                st.metric("Put/Call Ratio", f"{options.get('put_call_ratio', 0):.2f}")
                st.metric("VIX", f"{options.get('vix', 0):.1f}")
                st.caption(f"Term: {options.get('vix_term_structure', 'N/A')} | Skew: {options.get('skew', 'N/A')}")

        sectors = stock_intel.get("sector_performance", [])
        if sectors:
            with sec_col:
                st.markdown("**Sector Performance**")
                sec_rows = []
                for s in sectors[:8]:
                    rs = s.get("relative_strength", 0)
                    sec_rows.append({
                        "Sector": s.get("sector", "").replace("_", " ").title(),
                        "1d": f"{s.get('change_1d', 0):+.2f}%",
                        "1w": f"{s.get('change_1w', 0):+.2f}%",
                        "RS": f"{rs:+.2f}%",
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


# ── Section 7: After-Hours Intelligence ──────────────────────────


after_hours = today_findings.get("after_hours", {})
if after_hours:
    session = after_hours.get("session", "").replace("_", " ").title()
    st.header(f"After-Hours ({session})")

    # Earnings Gaps
    gaps = after_hours.get("earnings_gaps", [])
    if gaps:
        st.subheader("Earnings Gap Signals")
        for g in gaps:
            gap_dir = "UP" if g.get("gap_direction") == "up" else "DOWN"
            vol = "Confirmed" if g.get("volume_confirmation") else "Not confirmed"
            with st.expander(f"{g.get('ticker', '')} — Gap {gap_dir} {abs(g.get('gap_pct', 0)):.1f}% ({g.get('gap_size', '')})"):
                st.markdown(f"**Strategy:** {g.get('strategy', '').replace('_', ' ').title()} | **Direction:** {g.get('direction', '')}")
                st.markdown(f"**Entry:** ${g.get('entry_price', 0):.2f} | **SL:** ${g.get('stop_loss', 0):.2f} | **TP:** ${g.get('take_profit', 0):.2f}")
                st.markdown(f"**Confidence:** {g.get('confidence', 0):.0%} | **Volume:** {vol}")
                st.markdown(f"_{g.get('reasoning', '')}_")

    # Crypto Overnight
    crypto_night = after_hours.get("crypto_overnight", [])
    if crypto_night:
        st.subheader("Crypto Overnight Signals")
        for s in crypto_night:
            with st.expander(f"{s.get('symbol', '')} — {s.get('signal_type', '').replace('_', ' ').title()} ({s.get('strength', '')})"):
                st.markdown(f"**{s.get('direction', '')}** @ ${s.get('current_price', 0):,.2f} | Change: {s.get('price_change_pct', 0):+.1f}%")
                st.markdown(f"**Entry:** ${s.get('entry_price', 0):,.2f} | **SL:** ${s.get('stop_loss', 0):,.2f} | **TP:** ${s.get('take_profit', 0):,.2f}")
                st.markdown(f"_{s.get('reasoning', '')}_")

    # Pre-Market Movers
    movers = after_hours.get("premarket_movers", [])
    if movers:
        st.subheader("Pre-Market Movers")
        mover_rows = []
        for m in movers[:10]:
            mover_rows.append({
                "Ticker": m.get("ticker", ""),
                "Gap": f"{m.get('gap_pct', 0):+.1f}%",
                "Vol Ratio": f"{m.get('volume_ratio', 0):.1f}x",
                "Catalyst": m.get("catalyst", ""),
                "Action": m.get("action", "").replace("_", " ").title(),
            })
        st.dataframe(pd.DataFrame(mover_rows), use_container_width=True, hide_index=True)

    if not (gaps or crypto_night or movers):
        st.caption("No significant after-hours signals detected.")


# ── Section 8: AI Daily Summary ──────────────────────────────────


ai_summary = today_findings.get("ai_summary")
if ai_summary:
    st.header("AI Daily Summary")
    st.markdown(ai_summary)


# ── Section 9: Performance & Behavior ────────────────────────────


st.header("Performance")

if not trades_df.empty and "strategy" in trades_df.columns:
    col_strat, col_exit = st.columns(2)

    with col_strat:
        st.subheader("Strategy Performance")
        strat_metrics = performance.get("strategy_metrics", {}) if isinstance(performance, dict) else {}
        if strat_metrics:
            rows = []
            for strat, m in strat_metrics.items():
                rows.append(
                    {
                        "Strategy": strat.replace("_", " ").title(),
                        "Trades": m.get("total_trades", 0),
                        "Win Rate": f"{m.get('win_rate', 0) * 100:.0f}%",
                        "P&L": f"${m.get('pnl', 0):+.2f}",
                    }
                )
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            # Strategy P&L chart
            chart_data = pd.DataFrame(
                [
                    {"Strategy": k.replace("_", " ").title(), "P&L": v.get("pnl", 0)}
                    for k, v in strat_metrics.items()
                ]
            )
            fig = px.bar(chart_data, x="Strategy", y="P&L", color="P&L",
                         color_continuous_scale=["red", "gray", "green"])
            fig.update_layout(height=250, margin=dict(t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

    with col_exit:
        st.subheader("Exit Reasons")
        if "exit_reason" in trades_df.columns:
            exit_counts = trades_df["exit_reason"].value_counts()
            fig = px.pie(
                values=exit_counts.values,
                names=exit_counts.index,
                title="",
                height=300,
            )
            fig.update_layout(margin=dict(t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

    # Behavioral summary
    st.subheader("Behavioral Summary")
    behavior_log = []
    if behavior_log_path.exists():
        behavior_log = json.loads(behavior_log_path.read_text())

    if behavior_log:
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        recent = [e for e in behavior_log if e.get("date", "") >= cutoff]
        entries = len([e for e in recent if e.get("action") == "entry"])
        skips = len([e for e in recent if e.get("action") == "skip"])
        plan_aligned = len([e for e in recent if e.get("plan_aligned", True)])
        adherence = plan_aligned / len(recent) if recent else 1.0
        disciplines = [e["discipline_rating"] for e in recent if e.get("discipline_rating")]
        avg_discipline = sum(disciplines) / len(disciplines) if disciplines else 0

        bc1, bc2, bc3 = st.columns(3)
        bc1.metric("Entries (7d)", entries)
        bc2.metric("Plan Adherence", f"{adherence:.0%}")
        bc3.metric("Avg Discipline", f"{avg_discipline:.1f}/5" if avg_discipline > 0 else "N/A")
else:
    st.info("No trade history yet for performance charts.")


# ── Section 10: Portfolio Analytics ──────────────────────────────


if portfolio_analytics:
    st.header("Portfolio Analytics")

    pa_col1, pa_col2, pa_col3, pa_col4 = st.columns(4)
    pa_col1.metric("Sortino Ratio", f"{portfolio_analytics.get('sortino_ratio', 0):.2f}")
    pa_col2.metric("Max Drawdown", f"{portfolio_analytics.get('max_drawdown_pct', 0):.1f}%")
    pa_col3.metric("Calmar Ratio", f"{portfolio_analytics.get('calmar_ratio', 0):.2f}")
    pa_col4.metric("Avg Hold", f"{portfolio_analytics.get('avg_hold_days', 0):.1f}d")

    pa2_col1, pa2_col2, pa2_col3, pa2_col4 = st.columns(4)
    pa2_col1.metric("Best Day", f"${portfolio_analytics.get('best_day_pnl', 0):+.2f}")
    pa2_col2.metric("Worst Day", f"${portfolio_analytics.get('worst_day_pnl', 0):+.2f}")
    pa2_col3.metric("Max Win Streak", f"{portfolio_analytics.get('max_consecutive_wins', 0)}")
    pa2_col4.metric("Max Loss Streak", f"{portfolio_analytics.get('max_consecutive_losses', 0)}")

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

        # Drawdown chart
        fig_dd = go.Figure()
        fig_dd.add_trace(go.Scatter(x=eq_df["trade_num"], y=eq_df["drawdown_pct"],
                                     mode="lines", fill="tozeroy", name="Drawdown",
                                     line=dict(color="red", width=1)))
        fig_dd.update_layout(height=150, margin=dict(t=20, b=20), title="Drawdown %",
                             xaxis_title="Trade #", yaxis_title="DD %")
        st.plotly_chart(fig_dd, use_container_width=True)

    # Monthly returns
    monthly = portfolio_analytics.get("monthly_returns", {})
    if monthly:
        with st.expander("Monthly Returns"):
            month_df = pd.DataFrame([{"Month": k, "P&L": v} for k, v in monthly.items()])
            fig = px.bar(month_df, x="Month", y="P&L", color="P&L",
                         color_continuous_scale=["red", "gray", "green"])
            fig.update_layout(height=200, margin=dict(t=10, b=10))
            st.plotly_chart(fig, use_container_width=True)

    # Direction stats
    dir_stats = portfolio_analytics.get("direction_stats", {})
    if dir_stats:
        with st.expander("Long vs Short Performance"):
            for dir_name, stats in dir_stats.items():
                st.markdown(
                    f"**{dir_name}**: {stats.get('total_trades', 0)} trades, "
                    f"{stats.get('win_rate', 0):.0%} win rate, "
                    f"${stats.get('total_pnl', 0):+.2f} total P&L"
                )


# ── Section 11: API Health ───────────────────────────────────────


if api_health:
    with st.expander("API Health Status"):
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


# ── Tomorrow's Prep ──────────────────────────────────────────────


tomorrow_items = today_report.get("tomorrow_prep", [])
watchlist_signals = [s for s in signals if s.get("action") == "watchlist"]

if tomorrow_items or watchlist_signals:
    st.header("Tomorrow's Prep")

    for item in tomorrow_items:
        st.markdown(f"- {item}")

    if watchlist_signals:
        st.subheader("Watchlist")
        for sig in watchlist_signals:
            st.markdown(f"- **{sig['ticker']}** — {sig.get('strategy_label', '')} ({sig.get('setup', '')})")


# ── Auto-refresh ─────────────────────────────────────────────────

refresh_seconds = config.get("auto_refresh_seconds", 60)
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=refresh_seconds * 1000, key="data_refresh")
except ImportError:
    pass  # streamlit-autorefresh is optional

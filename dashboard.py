"""Joe AI — Day Trading Dashboard.

Run with: streamlit run dashboard.py
"""

import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import yaml
from streamlit_autorefresh import st_autorefresh

# ── Configuration ────────────────────────────────────────────────────────────

DATA_DIR = Path("data/paper")
CONFIG_DIR = Path("config")


def _load_dashboard_config() -> dict:
    path = CONFIG_DIR / "dashboard.yaml"
    if path.exists():
        try:
            return yaml.safe_load(path.read_text()).get("dashboard", {})
        except Exception:
            return {}
    return {}


def _load_paper_trader_config() -> dict:
    path = CONFIG_DIR / "paper_trader.yaml"
    if path.exists():
        try:
            return yaml.safe_load(path.read_text()).get("paper_trader", {})
        except Exception:
            return {}
    return {}


# ── Data Loaders ─────────────────────────────────────────────────────────────


def load_performance() -> dict:
    path = DATA_DIR / "performance.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def load_portfolio_analytics() -> dict:
    path = DATA_DIR / "portfolio_analytics.json"
    if path.exists():
        try:
            text = path.read_text()
            # Handle Infinity values in JSON (non-standard)
            text = text.replace(": Infinity", ": 0")
            text = text.replace(":-Infinity", ": 0")
            text = text.replace(": -Infinity", ": 0")
            return json.loads(text)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def load_open_positions() -> list[dict]:
    path = DATA_DIR / "open_positions.json"
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []
    return []


def load_session_state() -> dict:
    path = DATA_DIR / "session_state.json"
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def load_trade_history() -> pd.DataFrame:
    path = DATA_DIR / "trade_history.csv"
    if path.exists():
        try:
            df = pd.read_csv(path)
            if not df.empty:
                # Ensure numeric columns
                for col in ["pnl", "pnl_pct", "entry_price", "exit_price",
                            "position_size", "r_multiple", "signal_score",
                            "days_held", "time_held_minutes", "spread_cost"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
                return df
        except Exception:
            pass
    return pd.DataFrame()


# ── Helpers ──────────────────────────────────────────────────────────────────


def fmt_pnl(val: float) -> str:
    return f"${val:+,.2f}"


def fmt_pct(val: float) -> str:
    return f"{val:+.2f}%"


def pnl_color(val: float) -> str:
    if val > 0:
        return "green"
    elif val < 0:
        return "red"
    return "gray"


# ── Page: Overview ───────────────────────────────────────────────────────────


def page_overview():
    perf = load_performance()
    analytics = load_portfolio_analytics()
    positions = load_open_positions()
    session = load_session_state()
    trades_df = load_trade_history()
    pt_config = _load_paper_trader_config()

    # Top metrics
    balance = perf.get("virtual_balance", 0)
    starting = perf.get("starting_balance", balance)
    total_pnl = balance - starting
    win_rate = perf.get("win_rate", 0) * 100
    total_trades = perf.get("total_trades", 0)
    sharpe = perf.get("sharpe_ratio", 0)

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Balance", f"${balance:,.2f}", fmt_pnl(total_pnl))
    col2.metric("Total P&L", fmt_pnl(total_pnl), fmt_pct(total_pnl / starting * 100 if starting else 0))
    col3.metric("Win Rate", f"{win_rate:.1f}%")
    col4.metric("Total Trades", total_trades)
    col5.metric("Sharpe Ratio", f"{sharpe:.2f}")

    st.divider()

    # Equity curve from portfolio_analytics
    equity_data = analytics.get("equity_curve", [])
    if equity_data:
        eq_df = pd.DataFrame(equity_data)
        if not eq_df.empty and "date" in eq_df.columns and "balance" in eq_df.columns:
            fig = px.line(
                eq_df, x="date", y="balance",
                title="Equity Curve",
                labels={"date": "Date", "balance": "Balance ($)"},
            )
            fig.update_layout(hovermode="x unified", height=350)
            fig.update_traces(line_color="#1f77b4", fill="tozeroy", fillcolor="rgba(31,119,180,0.1)")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No equity curve data yet.")

    # Open positions
    st.subheader("Open Positions")
    if positions:
        rows = []
        for p in positions:
            entry = p.get("entry_price", 0)
            direction = p.get("direction", "")
            upnl = p.get("unrealized_pnl", 0)
            entry_time = p.get("entry_time", p.get("entry_date", ""))
            # Calculate time held
            time_held = ""
            if entry_time:
                try:
                    et = datetime.fromisoformat(entry_time)
                    delta = datetime.now() - et
                    hours = delta.total_seconds() / 3600
                    if hours < 1:
                        time_held = f"{delta.total_seconds() / 60:.0f}m"
                    elif hours < 24:
                        time_held = f"{hours:.1f}h"
                    else:
                        time_held = f"{delta.days}d {hours % 24:.0f}h"
                except (ValueError, TypeError):
                    time_held = f"{p.get('days_held', 0)}d"

            rows.append({
                "Ticker": p.get("ticker", ""),
                "Direction": direction,
                "Strategy": p.get("strategy", ""),
                "Entry Price": f"${entry:.2f}",
                "Unrealized P&L": fmt_pnl(upnl),
                "Time Held": time_held,
                "Stop Loss": f"${p.get('stop_loss', 0):.2f}",
                "Take Profit": f"${p.get('take_profit', 0):.2f}",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.info("No open positions.")

    # Today's session
    st.subheader("Today's Session")
    today_pnl = session.get("today_pnl", 0)
    today_trades = session.get("today_trades", 0)
    today_wins = session.get("today_wins", 0)
    today_losses = session.get("today_losses", 0)
    consec_losses = session.get("consecutive_losses", 0)

    daily_gain_target = pt_config.get("daily_gain_target", 50.0)
    daily_loss_limit = pt_config.get("daily_loss_limit", 30.0)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Today P&L", fmt_pnl(today_pnl))
    col2.metric("Trades Today", today_trades)
    col3.metric("W / L", f"{today_wins} / {today_losses}")
    col4.metric("Consec. Losses", consec_losses)

    # Gain target progress
    if daily_gain_target > 0:
        progress = max(0.0, min(1.0, today_pnl / daily_gain_target)) if today_pnl > 0 else 0.0
        st.caption(f"Daily Gain Target: ${daily_gain_target:.0f}")
        st.progress(progress, text=f"{fmt_pnl(today_pnl)} / ${daily_gain_target:.0f}")

    # Loss limit warning
    if today_pnl < 0 and daily_loss_limit > 0:
        loss_pct = abs(today_pnl) / daily_loss_limit
        if loss_pct >= 0.8:
            st.warning(f"Approaching daily loss limit: {fmt_pnl(today_pnl)} / -${daily_loss_limit:.0f}")

    if session.get("paused_until"):
        st.error(f"Trading paused until {session['paused_until']}")


# ── Page: Trade History ──────────────────────────────────────────────────────


def page_trade_history():
    df = load_trade_history()

    if df.empty:
        st.info("No trade history yet.")
        return

    # Filters
    st.subheader("Filters")
    fcol1, fcol2, fcol3, fcol4 = st.columns(4)

    with fcol1:
        if "exit_date" in df.columns:
            dates = pd.to_datetime(df["exit_date"], errors="coerce").dropna()
            if not dates.empty:
                min_date = dates.min().date()
                max_date = dates.max().date()
                date_range = st.date_input(
                    "Date Range",
                    value=(min_date, max_date),
                    min_value=min_date,
                    max_value=max_date,
                )
            else:
                date_range = None
        else:
            date_range = None

    with fcol2:
        strategies = ["All"] + sorted(df["strategy"].dropna().unique().tolist()) if "strategy" in df.columns else ["All"]
        strategy_filter = st.selectbox("Strategy", strategies)

    with fcol3:
        tickers = ["All"] + sorted(df["ticker"].dropna().unique().tolist()) if "ticker" in df.columns else ["All"]
        ticker_filter = st.selectbox("Ticker", tickers)

    with fcol4:
        result_filter = st.selectbox("Result", ["All", "Win", "Loss", "Flat"])

    # Apply filters
    filtered = df.copy()

    if date_range and isinstance(date_range, tuple) and len(date_range) == 2:
        start_str = date_range[0].isoformat()
        end_str = date_range[1].isoformat()
        if "exit_date" in filtered.columns:
            filtered = filtered[
                (filtered["exit_date"] >= start_str) & (filtered["exit_date"] <= end_str)
            ]

    if strategy_filter != "All" and "strategy" in filtered.columns:
        filtered = filtered[filtered["strategy"] == strategy_filter]

    if ticker_filter != "All" and "ticker" in filtered.columns:
        filtered = filtered[filtered["ticker"] == ticker_filter]

    if result_filter != "All" and "pnl" in filtered.columns:
        if result_filter == "Win":
            filtered = filtered[filtered["pnl"] > 0]
        elif result_filter == "Loss":
            filtered = filtered[filtered["pnl"] < 0]
        elif result_filter == "Flat":
            filtered = filtered[filtered["pnl"] == 0]

    # Display columns
    display_cols = [
        c for c in [
            "exit_date", "ticker", "direction", "setup_type", "strategy",
            "entry_price", "exit_price", "pnl", "pnl_pct", "days_held",
            "time_held_minutes", "session_window", "exit_type", "exit_reason",
        ] if c in filtered.columns
    ]

    st.subheader(f"Trades ({len(filtered)})")
    if not filtered.empty:
        st.dataframe(
            filtered[display_cols].sort_values("exit_date", ascending=False),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No trades match the selected filters.")

    # Summary stats
    st.subheader("Summary Statistics")
    if not filtered.empty and "pnl" in filtered.columns:
        wins = filtered[filtered["pnl"] > 0]
        losses = filtered[filtered["pnl"] < 0]
        total_pnl = filtered["pnl"].sum()
        win_rate = len(wins) / len(filtered) * 100 if len(filtered) > 0 else 0
        avg_win = wins["pnl"].mean() if not wins.empty else 0
        avg_loss = losses["pnl"].mean() if not losses.empty else 0
        gross_wins = wins["pnl"].sum() if not wins.empty else 0
        gross_losses = abs(losses["pnl"].sum()) if not losses.empty else 0
        profit_factor = gross_wins / gross_losses if gross_losses > 0 else 0

        scol1, scol2, scol3, scol4, scol5 = st.columns(5)
        scol1.metric("Total P&L", fmt_pnl(total_pnl))
        scol2.metric("Win Rate", f"{win_rate:.1f}%")
        scol3.metric("Avg Win", fmt_pnl(avg_win))
        scol4.metric("Avg Loss", fmt_pnl(avg_loss))
        scol5.metric("Profit Factor", f"{profit_factor:.2f}")


# ── Page: Strategy Analysis ─────────────────────────────────────────────────


def page_strategy_analysis():
    analytics = load_portfolio_analytics()
    df = load_trade_history()

    strategy_stats = analytics.get("strategy_stats", [])

    if not strategy_stats and df.empty:
        st.info("No strategy data yet.")
        return

    # Strategy P&L bar chart
    if strategy_stats:
        strat_df = pd.DataFrame(strategy_stats)
        if not strat_df.empty and "name" in strat_df.columns:
            st.subheader("P&L by Strategy")
            colors = ["green" if v >= 0 else "red" for v in strat_df.get("total_pnl", [])]
            fig = go.Figure(go.Bar(
                x=strat_df["name"],
                y=strat_df["total_pnl"],
                marker_color=colors,
                text=[fmt_pnl(v) for v in strat_df["total_pnl"]],
                textposition="outside",
            ))
            fig.update_layout(
                title="Total P&L by Strategy",
                xaxis_title="Strategy",
                yaxis_title="P&L ($)",
                height=350,
            )
            st.plotly_chart(fig, use_container_width=True)

            # Win rate by strategy
            st.subheader("Win Rate by Strategy")
            fig2 = go.Figure(go.Bar(
                x=strat_df["name"],
                y=strat_df.get("win_rate", [0] * len(strat_df)) if "win_rate" in strat_df.columns else [0] * len(strat_df),
                marker_color="#1f77b4",
                text=[f"{v:.0%}" if isinstance(v, float) else str(v) for v in strat_df.get("win_rate", [])],
                textposition="outside",
            ))
            fig2.update_layout(
                title="Win Rate by Strategy",
                xaxis_title="Strategy",
                yaxis_title="Win Rate",
                yaxis_tickformat=".0%",
                height=350,
            )
            st.plotly_chart(fig2, use_container_width=True)

    # Session performance
    st.subheader("Session Performance")
    if not df.empty and "session_window" in df.columns:
        session_groups = df.groupby("session_window").agg(
            total_pnl=("pnl", "sum"),
            trades=("pnl", "count"),
            wins=("pnl", lambda x: (x > 0).sum()),
        ).reset_index()
        session_groups["win_rate"] = session_groups["wins"] / session_groups["trades"]

        session_order = ["pre_market", "opening", "midday", "closing", "after_hours", "crypto_overnight", "unknown"]
        session_groups["order"] = session_groups["session_window"].apply(
            lambda x: session_order.index(x) if x in session_order else len(session_order)
        )
        session_groups = session_groups.sort_values("order")

        colors = ["green" if v >= 0 else "red" for v in session_groups["total_pnl"]]
        fig3 = go.Figure(go.Bar(
            x=session_groups["session_window"],
            y=session_groups["total_pnl"],
            marker_color=colors,
            text=[fmt_pnl(v) for v in session_groups["total_pnl"]],
            textposition="outside",
        ))
        fig3.update_layout(
            title="P&L by Session Window",
            xaxis_title="Session",
            yaxis_title="P&L ($)",
            height=350,
        )
        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("No session data available.")

    # Best / Worst trades
    st.subheader("Best & Worst Trades")
    if not df.empty and "pnl" in df.columns:
        col1, col2 = st.columns(2)
        with col1:
            st.caption("Top 5 Winners")
            top = df.nlargest(5, "pnl")
            display_cols = [c for c in ["ticker", "direction", "strategy", "pnl", "exit_date"] if c in top.columns]
            st.dataframe(top[display_cols], use_container_width=True, hide_index=True)

        with col2:
            st.caption("Top 5 Losers")
            bottom = df.nsmallest(5, "pnl")
            display_cols = [c for c in ["ticker", "direction", "strategy", "pnl", "exit_date"] if c in bottom.columns]
            st.dataframe(bottom[display_cols], use_container_width=True, hide_index=True)


# ── Page: Risk & Controls ───────────────────────────────────────────────────


def page_risk_controls():
    perf = load_performance()
    analytics = load_portfolio_analytics()
    session = load_session_state()
    positions = load_open_positions()
    df = load_trade_history()
    pt_config = _load_paper_trader_config()

    # Current risk state
    st.subheader("Current Risk State")
    daily_gain_target = pt_config.get("daily_gain_target", 50.0)
    daily_loss_limit = pt_config.get("daily_loss_limit", 30.0)
    today_pnl = session.get("today_pnl", 0)
    consec_losses = session.get("consecutive_losses", 0)

    col1, col2, col3 = st.columns(3)
    col1.metric("Daily P&L", fmt_pnl(today_pnl))
    col2.metric("Loss Limit", f"-${daily_loss_limit:.0f}")
    col3.metric("Consecutive Losses", consec_losses)

    # Gain target progress
    if daily_gain_target > 0:
        progress = max(0.0, min(1.0, today_pnl / daily_gain_target)) if today_pnl > 0 else 0.0
        st.progress(progress, text=f"Gain target: {fmt_pnl(today_pnl)} / ${daily_gain_target:.0f}")

    # Loss limit status
    if today_pnl <= -daily_loss_limit:
        st.error("Daily loss limit reached. Trading should be paused.")
    elif today_pnl < 0 and abs(today_pnl) >= daily_loss_limit * 0.7:
        st.warning(f"Approaching loss limit ({fmt_pnl(today_pnl)} / -${daily_loss_limit:.0f})")

    st.divider()

    # Correlation exposure
    st.subheader("Open Position Exposure")
    if positions:
        exposure_rows = []
        for p in positions:
            sector = p.get("sector", "") or "Unknown"
            notional = abs(p.get("entry_price", 0) * p.get("position_size", 0))
            exposure_rows.append({
                "Ticker": p.get("ticker", ""),
                "Direction": p.get("direction", ""),
                "Sector": sector,
                "Strategy": p.get("strategy", ""),
                "Notional": f"${notional:,.2f}",
            })
        st.dataframe(pd.DataFrame(exposure_rows), use_container_width=True, hide_index=True)
    else:
        st.info("No open positions.")

    st.divider()

    # Drawdown chart
    st.subheader("Drawdown Over Time")
    equity_data = analytics.get("equity_curve", [])
    if equity_data:
        eq_df = pd.DataFrame(equity_data)
        if not eq_df.empty and "drawdown_pct" in eq_df.columns:
            fig = px.area(
                eq_df, x="date", y="drawdown_pct",
                title="Drawdown (%)",
                labels={"date": "Date", "drawdown_pct": "Drawdown (%)"},
            )
            fig.update_layout(height=300)
            fig.update_traces(line_color="red", fillcolor="rgba(255,0,0,0.1)")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No drawdown data yet.")

    st.divider()

    # Go Live Readiness Checklist
    st.subheader("Go Live Readiness Checklist")
    st.caption("Targets for transitioning from paper to live trading (after 30 days)")

    total_trades = perf.get("total_trades", 0)
    win_rate = perf.get("win_rate", 0) * 100
    sharpe = perf.get("sharpe_ratio", 0)
    max_dd = abs(analytics.get("max_drawdown_pct", 0))

    # Calculate profitable days percentage
    profitable_days_pct = 0
    if not df.empty and "exit_date" in df.columns:
        daily_pnl = df.groupby("exit_date")["pnl"].sum()
        profitable_days = (daily_pnl > 0).sum()
        total_days = len(daily_pnl)
        profitable_days_pct = profitable_days / total_days * 100 if total_days > 0 else 0

    # Max single trade as % of portfolio
    max_single_trade_pct = 0
    starting_balance = perf.get("starting_balance", 500)
    if not df.empty and "pnl" in df.columns and starting_balance > 0:
        max_single_trade_pct = abs(df["pnl"].min()) / starting_balance * 100

    # Calculate days since start
    days_active = 0
    if not df.empty and "entry_date" in df.columns:
        first_trade = pd.to_datetime(df["entry_date"], errors="coerce").min()
        if pd.notna(first_trade):
            days_active = (datetime.now() - first_trade).days

    checks = [
        ("Win rate > 40%", win_rate > 40, f"{win_rate:.1f}%"),
        ("Sharpe ratio > 0.5", sharpe > 0.5, f"{sharpe:.2f}"),
        ("Max drawdown < 15%", max_dd < 15, f"{max_dd:.1f}%"),
        ("At least 50 trades", total_trades >= 50, f"{total_trades} trades"),
        ("Profitable 60%+ of days", profitable_days_pct >= 60, f"{profitable_days_pct:.0f}%"),
        ("No single trade > 5% of portfolio", max_single_trade_pct < 5, f"{max_single_trade_pct:.1f}%"),
        ("30+ days of paper trading", days_active >= 30, f"{days_active} days"),
    ]

    passed = 0
    for label, ok, value in checks:
        icon = ":white_check_mark:" if ok else ":x:"
        status = "PASS" if ok else "FAIL"
        st.markdown(f"{icon} **{label}** — {value} ({status})")
        if ok:
            passed += 1

    st.divider()
    st.metric("Readiness Score", f"{passed}/{len(checks)}")
    if passed == len(checks):
        st.success("All criteria met. Ready to go live!")
    elif passed >= len(checks) - 2:
        st.warning("Almost there. A few criteria still need improvement.")
    else:
        st.error("Not ready for live trading. Keep paper trading.")


# ── Main App ─────────────────────────────────────────────────────────────────


def main():
    st.set_page_config(
        page_title="Joe AI — Day Trading Dashboard",
        page_icon=":chart_with_upwards_trend:",
        layout="wide",
    )

    dash_config = _load_dashboard_config()
    refresh_seconds = dash_config.get("auto_refresh_seconds", 60)

    # Auto-refresh
    st_autorefresh(interval=refresh_seconds * 1000, key="auto_refresh")

    # Header
    st.title("Joe AI — Day Trading Dashboard")
    st.caption(f"{date.today().strftime('%A, %B %d, %Y')}")

    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Go to",
        ["Overview", "Trade History", "Strategy Analysis", "Risk & Controls"],
        label_visibility="collapsed",
    )

    # Last updated
    perf = load_performance()
    last_updated = perf.get("last_updated", "")
    if last_updated:
        try:
            ts = datetime.fromisoformat(last_updated)
            st.sidebar.caption(f"Data updated: {ts.strftime('%b %d, %H:%M')}")
        except (ValueError, TypeError):
            pass

    st.sidebar.divider()

    # Quick stats in sidebar
    balance = perf.get("virtual_balance", 0)
    starting = perf.get("starting_balance", balance)
    st.sidebar.metric("Balance", f"${balance:,.2f}")
    st.sidebar.metric("Total Return", fmt_pct((balance - starting) / starting * 100 if starting else 0))

    # Page routing
    if page == "Overview":
        page_overview()
    elif page == "Trade History":
        page_trade_history()
    elif page == "Strategy Analysis":
        page_strategy_analysis()
    elif page == "Risk & Controls":
        page_risk_controls()


if __name__ == "__main__":
    main()

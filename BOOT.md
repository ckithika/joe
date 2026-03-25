# Boot Checklist

Run through this once on gateway startup. This verifies the environment is ready.

## 1. Verify Environment

- [ ] Confirm project files exist in workspace: `ls main.py monitor.py telegram_bot.py`
- [ ] Confirm Python works: `python --version` (expect 3.13+)
- [ ] Confirm dependencies are installed: `python -c "import pandas, ib_insync, yaml; print('deps OK')"`
- [ ] Confirm `.env` exists and has non-placeholder values: `grep -c 'your_' .env` (should be 0 if fully configured)

## 2. Verify IBKR Gateway Connectivity

- [ ] Test socket to IB Gateway:
```bash
python -c "
import socket; s = socket.socket(); s.settimeout(5)
try: s.connect(('host.docker.internal', 4002)); print('Gateway reachable')
except: print('Gateway NOT reachable - IBC may still be starting')
finally: s.close()
"
```
- [ ] If Gateway is not reachable, wait 60 seconds and retry — IBC may still be starting up. If still unreachable after 3 retries, alert owner via Telegram. IB Gateway is managed by IBC with launchd auto-restart, so it should come up automatically.

## 3. Verify Data Directories

- [ ] Ensure data directories exist: `mkdir -p data/paper data/findings data/reports data/cache`

## 4. Start Telegram Bot

- [ ] Start the Telegram bot in the background: `python telegram_bot.py &`
- [ ] Verify it started: `sleep 3 && ps aux | grep telegram_bot`

## 5. Determine Trading State

- [ ] What day/time is it in US Eastern? `python -c "from datetime import datetime; import pytz; print(datetime.now(pytz.timezone('US/Eastern')).strftime('%A %Y-%m-%d %H:%M ET'))"`
- [ ] Is it a trading day? Check against `config/trading.yaml` holidays.
- [ ] If it's before 09:00 ET on a trading day — wait for pipeline time.
- [ ] If it's between 09:00-09:30 ET — run the pipeline if it hasn't run today.
- [ ] If it's between 09:30-16:00 ET — run the pipeline if needed, then start the monitor.
- [ ] If it's after 16:00 ET — run post-close review (read findings + P&L).
- [ ] If it's a weekend — no trading. Optionally review weekly analytics.

## 6. Read Last Known State

- [ ] Read the most recent findings file to understand current market regime and positions.
- [ ] Read `data/paper/performance.json` for portfolio status.
- [ ] Note any open positions in `data/paper/positions.json`.

Boot complete. Transition to normal heartbeat cycle.

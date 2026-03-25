# Heartbeat Checklist

Run through this checklist on every heartbeat cycle. Report anomalies to the owner via Telegram.

## 1. Process Health

- [ ] Is the Telegram bot process running? If not, restart: `python telegram_bot.py &`
- [ ] During market hours (9:30-16:00 ET, weekdays): is the monitor running? If not, restart: `python monitor.py --broker ibkr &`
- [ ] Check for any orphaned/zombie Python processes: `ps aux | grep python`

## 2. IBKR Connectivity

- [ ] Can we reach IB Gateway? Run the socket check:
```bash
python -c "
import socket; s = socket.socket(); s.settimeout(3)
try: s.connect(('host.docker.internal', 4002)); print('OK')
except: print('UNREACHABLE')
finally: s.close()
"
```
- [ ] If unreachable and it's a trading day during market hours, alert the owner. IBC should auto-recover — check again in 5 minutes before escalating.

## 3. Data Freshness

- [ ] If it's after 09:30 ET on a trading day, does today's findings file exist? (`data/findings/YYYY-MM-DD.json`)
- [ ] If no findings file exists and it's past 09:30, the pipeline didn't run. Run it: `python main.py --once --broker ibkr`
- [ ] Are open positions stale? Check `data/paper/positions.json` — if last modified >4 hours ago during market hours, something is wrong.

## 4. Portfolio Status

- [ ] Read `data/paper/performance.json` — note current balance and daily P&L.
- [ ] If daily loss limit ($30) has been hit, no further trading today. Confirm monitor has stopped opening new positions.
- [ ] Check for any positions held overnight unexpectedly (max_hold_days exceeded).

## 5. API Health

- [ ] Read `data/paper/api_health.json` — any circuit breakers tripped?
- [ ] If a data API is failing, note which one and whether it affects the pipeline.

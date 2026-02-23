#!/bin/bash
set -e

# Cloud Run entrypoint
# For the bot service: starts the Telegram bot in webhook mode
# For the pipeline job: runs main.py with args from CMD override

if [ "$DEPLOYMENT_MODE" = "cloud" ]; then
    echo "Running in cloud mode"

    # Configure git for push operations
    if [ -n "$GITHUB_TOKEN" ] && [ -n "$GITHUB_REPO" ]; then
        git config --global user.email "bot@joeai.local"
        git config --global user.name "Joe AI Bot"
        git config --global credential.helper store
        echo "https://x-access-token:${GITHUB_TOKEN}@github.com" > ~/.git-credentials
    fi
fi

# Route based on RUN_MODE
if [ "$RUN_MODE" = "pipeline" ]; then
    echo "Running pipeline..."
    exec python main.py "$@"
elif [ "$RUN_MODE" = "monitor" ]; then
    echo "Running monitor cycle..."
    cd /app
    git pull --rebase 2>/dev/null || true
    python monitor.py "$@"
    git add data/paper/ 2>/dev/null
    git diff --cached --quiet || git commit -m "data: monitor cycle $(date +%H:%M)" && git push || true
else
    echo "Starting Telegram bot..."
    exec python telegram_bot.py
fi

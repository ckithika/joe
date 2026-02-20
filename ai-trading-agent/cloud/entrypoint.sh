#!/bin/bash
set -e

# Cloud Run entrypoint
# For the bot service: starts the Telegram bot in webhook mode
# For the pipeline job: runs main.py with args from CMD override

if [ "$DEPLOYMENT_MODE" = "cloud" ]; then
    echo "Running in cloud mode"

    # Configure git for push operations
    if [ -n "$GITHUB_TOKEN" ] && [ -n "$GITHUB_REPO" ]; then
        git config --global user.email "bot@trading-agent.local"
        git config --global user.name "Trading Agent Bot"
        git config --global credential.helper store
        echo "https://x-access-token:${GITHUB_TOKEN}@github.com" > ~/.git-credentials
    fi
fi

# If RUN_MODE is "pipeline", run the pipeline instead of the bot
if [ "$RUN_MODE" = "pipeline" ]; then
    echo "Running pipeline..."
    exec python main.py "$@"
else
    echo "Starting Telegram bot..."
    exec python telegram_bot.py
fi

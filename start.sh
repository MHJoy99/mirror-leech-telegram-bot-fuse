#!/usr/bin/env bash
set -e

# Activate virtual environment if present
if [ -f "mltbenv/bin/activate" ]; then
    . mltbenv/bin/activate
fi

# Run updater / config sync
python3 update.py

# Launch bot using exec to handle termination signals properly
exec python3 -m bot

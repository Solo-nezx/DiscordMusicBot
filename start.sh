#!/bin/bash
set -e

echo "🔑 Starting PO token provider..."
node $(npm root -g)/@imputnet/bgutil-ytdlp-pot-provider/dist/server.js &
POT_PID=$!

echo "⏳ Waiting for PO token server..."
sleep 4

echo "🚀 Starting Music Bot…"
python bot.py

kill $POT_PID 2>/dev/null || true

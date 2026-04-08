#!/bin/bash
set -e

echo "🔑 Starting PO token server..."
BGU_PATH=$(npm root -g)/@imputnet/bgutil-ytdlp-pot-provider/dist/server.js
node "$BGU_PATH" &
BGU_PID=$!

echo "⏳ Waiting for PO token server (5s)..."
sleep 5

echo "🚀 Starting Music Bot…"
exec python bot.py

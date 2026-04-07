#!/bin/bash

echo ""
echo "╔══════════════════════════════════════╗"
echo "║      Discord Music Bot Setup         ║"
echo "╚══════════════════════════════════════╝"
echo ""

# ── Check Python ──────────────────────────────
if ! command -v python3 &>/dev/null; then
    echo "❌  Python3 غير مثبت! قم بتثبيته أولاً."
    exit 1
fi
echo "✅  Python3 موجود: $(python3 --version)"

# ── Check FFmpeg ──────────────────────────────
if ! command -v ffmpeg &>/dev/null; then
    echo "⚙️  جاري تثبيت FFmpeg..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew install ffmpeg
    else
        sudo apt-get install -y ffmpeg
    fi
fi
echo "✅  FFmpeg موجود"

# ── Install packages ──────────────────────────
echo ""
echo "📦  جاري تثبيت المكتبات..."
pip3 install -q -r requirements.txt
echo "✅  تم التثبيت"

# ── Run ───────────────────────────────────────
echo ""
echo "🚀  البوت يعمل الآن! استخدم /play في ديسكورد"
echo "⛔  اضغط Ctrl+C لإيقاف البوت"
echo ""
python3 bot.py

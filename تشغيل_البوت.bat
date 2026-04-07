@echo off
chcp 65001 >nul
title Discord Music Bot 🎵
color 0A

echo.
echo  ╔══════════════════════════════════════╗
echo  ║      Discord Music Bot Setup         ║
echo  ╚══════════════════════════════════════╝
echo.

REM ── Check Python ──────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ❌  Python غير مثبت!
    echo  📥  يرجى تحميله من: https://www.python.org/downloads/
    echo      ✅ تأكد من تفعيل "Add Python to PATH" عند التثبيت
    pause
    exit /b 1
)
echo  ✅  Python موجود

REM ── Check / Install FFmpeg ─────────────────────
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  ⚙️  جاري تثبيت FFmpeg تلقائياً...
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements >nul 2>&1
    ffmpeg -version >nul 2>&1
    if %errorlevel% neq 0 (
        echo  ❌  فشل تثبيت FFmpeg تلقائياً.
        echo  📥  يرجى تحميله يدوياً من: https://ffmpeg.org/download.html
        echo      واستخرج المجلد وأضف مسار bin إلى PATH
        pause
        exit /b 1
    )
)
echo  ✅  FFmpeg موجود

REM ── Install Python packages ────────────────────
echo.
echo  📦  جاري تثبيت المكتبات المطلوبة...
pip install -q -r requirements.txt
if %errorlevel% neq 0 (
    echo  ❌  فشل تثبيت المكتبات!
    pause
    exit /b 1
)
echo  ✅  تم تثبيت المكتبات بنجاح

REM ── Run the bot ────────────────────────────────
echo.
echo  ╔══════════════════════════════════════╗
echo  ║    🚀  البوت يعمل الآن!              ║
echo  ║    🎵  استخدم /play في ديسكورد       ║
echo  ║    ⛔  أغلق هذه النافذة لإيقافه      ║
echo  ╚══════════════════════════════════════╝
echo.
python bot.py

echo.
echo  ⚠️  توقف البوت. اضغط أي زر للخروج.
pause

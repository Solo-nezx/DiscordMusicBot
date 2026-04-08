@echo off
chcp 65001 >nul
title Discord Music Bot 🎵 - تشغيل 24/7
color 0A

echo.
echo  ╔══════════════════════════════════════════════╗
echo  ║      Discord Music Bot - وضع 24/7           ║
echo  ╚══════════════════════════════════════════════╝
echo.

REM ── Check Python ──────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ❌  Python غير مثبت!
    echo  📥  يرجى تحميله من: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM ── Check FFmpeg ──────────────────────────────
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo  ⚙️  جاري تثبيت FFmpeg تلقائياً...
    winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements >nul 2>&1
    ffmpeg -version >nul 2>&1
    if %errorlevel% neq 0 (
        echo  ❌  فشل تثبيت FFmpeg. يرجى تثبيته يدوياً من: https://ffmpeg.org/download.html
        pause
        exit /b 1
    )
)

REM ── Install packages once ─────────────────────
echo  📦  جاري التحقق من المكتبات...
pip install -q -r requirements.txt
echo  ✅  المكتبات جاهزة

echo.
echo  ╔══════════════════════════════════════════════╗
echo  ║  🚀  البوت يعمل في وضع 24/7               ║
echo  ║  ♻️   سيعيد التشغيل تلقائياً لو وقع       ║
echo  ║  ⛔  أغلق هذه النافذة لإيقافه نهائياً     ║
echo  ╚══════════════════════════════════════════════╝
echo.

REM ── Infinite restart loop ─────────────────────
:restart_loop
set CRASH_TIME=%time%
echo  [%date% %time%]  🟢  بدء تشغيل البوت...
python bot.py

echo.
echo  [%date% %time%]  🔴  البوت وقف! سيعيد التشغيل خلال 10 ثواني...
echo  (أغلق النافذة الآن لو تريد إيقافه)
echo.
timeout /t 10 /nobreak >nul
echo  [%date% %time%]  ♻️  إعادة التشغيل...
echo.
goto restart_loop

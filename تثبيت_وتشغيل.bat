@echo off
chcp 65001 >nul
title Discord Music Bot - الإعداد الكامل
color 0B

echo.
echo  ╔══════════════════════════════════════════════════╗
echo  ║   Discord Music Bot - الإعداد الكامل 24/7      ║
echo  ╚══════════════════════════════════════════════════╝
echo.

REM ── تأكد من صلاحيات المسؤول ───────────────────────
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo  ⚠️  يحتاج صلاحيات Administrator
    echo  سيطلب منك Windows الإذن...
    echo.
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo  ✅  تم التحقق من الصلاحيات

REM ── تشغيل سكريبت الإعداد ──────────────────────────
echo.
echo  ⚙️  جاري إعداد اللابتوب كسيرفر 24/7...
echo.

powershell -ExecutionPolicy Bypass -File "%~dp0اعداد_السيرفر.ps1"

echo.
echo  🚀  هل تريد تشغيل البوت الآن؟ (Y/N)
set /p choice=  اختيارك:
if /i "%choice%"=="Y" (
    start "" "%~dp0تشغيل_24_7.bat"
)

echo.
echo  ✅  انتهى الإعداد. يمكنك إغلاق هذه النافذة.
pause

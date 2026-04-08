# ══════════════════════════════════════════════════════
#  Discord Music Bot - إعداد اللابتوب كسيرفر 24/7
#  شغّل هذا السكريبت مرة واحدة فقط كـ Administrator
# ══════════════════════════════════════════════════════

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "  ║   إعداد اللابتوب كسيرفر 24/7               ║" -ForegroundColor Cyan
Write-Host "  ╚══════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── 1. منع السكون والإسبات ──────────────────────────
Write-Host "  ⚙️  تعطيل وضع السكون والإسبات..." -ForegroundColor Yellow

# منع السكون عند توصيل الكهرباء
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 0

# منع السكون على البطارية (مهم لو انقطع الكهرباء)
powercfg /change standby-timeout-dc 0
powercfg /change hibernate-timeout-dc 0

# تعطيل الإسبات نهائياً
powercfg /hibernate off

Write-Host "  ✅  تم تعطيل السكون والإسبات" -ForegroundColor Green

# ── 2. إعداد إغلاق الغطاء لا يوقف الجهاز ───────────
Write-Host "  ⚙️  إعداد إغلاق الغطاء (لا يوقف الجهاز)..." -ForegroundColor Yellow

# عند توصيل الكهرباء: إغلاق الغطاء = لا شيء
powercfg /SETACVALUEINDEX SCHEME_CURRENT 4f971e89-eebd-4455-a8de-9e59040e7347 5ca83367-6e45-459f-a27b-476b1d01c936 0
# على البطارية: إغلاق الغطاء = لا شيء
powercfg /SETDCVALUEINDEX SCHEME_CURRENT 4f971e89-eebd-4455-a8de-9e59040e7347 5ca83367-6e45-459f-a27b-476b1d01c936 0

powercfg /SETACTIVE SCHEME_CURRENT

Write-Host "  ✅  إغلاق الغطاء لن يوقف الجهاز" -ForegroundColor Green

# ── 3. Task Scheduler: تشغيل البوت عند بدء Windows ──
Write-Host "  ⚙️  إضافة البوت لبدء التشغيل التلقائي..." -ForegroundColor Yellow

$BotDir  = Split-Path -Parent $MyInvocation.MyCommand.Path
$BatFile = Join-Path $BotDir "تشغيل_24_7.bat"

# حذف المهمة القديمة لو موجودة
Unregister-ScheduledTask -TaskName "DiscordMusicBot" -Confirm:$false -ErrorAction SilentlyContinue

$Action  = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$BatFile`"" -WorkingDirectory $BotDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable

Register-ScheduledTask `
    -TaskName "DiscordMusicBot" `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -RunLevel Highest `
    -Description "Discord Music Bot - يعمل 24/7 ويعيد التشغيل تلقائياً" | Out-Null

Write-Host "  ✅  البوت سيبدأ تلقائياً عند تسجيل الدخول" -ForegroundColor Green

# ── 4. تفعيل الحفاظ على الشبكة أثناء السكون ─────────
Write-Host "  ⚙️  الحفاظ على اتصال الشبكة..." -ForegroundColor Yellow
powercfg /SETACVALUEINDEX SCHEME_CURRENT 19caa586-e017-445d-88e4-6a2f6c6f5f52 12bbebe6-58d6-4636-95bb-3217ef867c1a 1
Write-Host "  ✅  الشبكة ستبقى متصلة" -ForegroundColor Green

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║  ✅  الإعداد اكتمل بنجاح!                  ║" -ForegroundColor Green
Write-Host "  ║                                              ║" -ForegroundColor Green
Write-Host "  ║  📋  ملخص ما تم:                           ║" -ForegroundColor Green
Write-Host "  ║   • السكون والإسبات: معطّل                 ║" -ForegroundColor Green
Write-Host "  ║   • إغلاق الغطاء: لا يوقف الجهاز          ║" -ForegroundColor Green
Write-Host "  ║   • البوت يبدأ تلقائياً عند تشغيل Windows ║" -ForegroundColor Green
Write-Host "  ║                                              ║" -ForegroundColor Green
Write-Host "  ║  🚀  الخطوة الأخيرة:                       ║" -ForegroundColor Green
Write-Host "  ║   شغّل تشغيل_24_7.bat الآن                 ║" -ForegroundColor Green
Write-Host "  ╚══════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""

Read-Host "  اضغط Enter للخروج"

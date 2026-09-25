# LogChain Windows Stop Script
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  STOPPING ALL LOGCHAIN SERVICES      " -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan

Get-Process geth -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -match "app_auth|watcher_multiuser|app.py|watcher.py"
} | Stop-Process -Force -ErrorAction SilentlyContinue

Write-Host "Geth Node 1 and Python services stopped." -ForegroundColor Green

# LogChain Stop Script for Node 2
Write-Host "Stopping Geth Node 2..." -ForegroundColor Cyan
Get-Process geth -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Host "Geth stopped." -ForegroundColor Green

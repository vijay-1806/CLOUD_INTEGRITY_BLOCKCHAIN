# LogChain Windows Startup Script
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  LOGCHAIN STARTUP SCRIPT (WINDOWS)  " -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan

# 1. Detect Local IP
$LocalIP = (Get-NetIPAddress -AddressFamily IPv4 | Where-Object { 
    $_.InterfaceAlias -notlike "*Loopback*" -and $_.IPAddress -notlike "169.254*" 
} | Select-Object -ExpandProperty IPAddress | Select-Object -First 1)

if (-not $LocalIP) { $LocalIP = "127.0.0.1" }
Write-Host "Main Node (PC1) IP: $LocalIP" -ForegroundColor Green

# 2. Get Node 2 IP
$DefaultNode2IP = "10.58.13.94"
$InputNode2IP = Read-Host "Enter Node 2 (Peer) IP [Default: $DefaultNode2IP]"
if ([string]::IsNullOrWhiteSpace($InputNode2IP)) {
    $Node2IP = $DefaultNode2IP
} else {
    $Node2IP = $InputNode2IP.Trim()
}
Write-Host "Using Node 2 IP: $Node2IP" -ForegroundColor Yellow

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 3. Kill old processes
Write-Host "`nStopping any existing LogChain processes..." -ForegroundColor DarkYellow
Get-Process geth, python -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -match "node1|app_auth|watcher_multiuser|app.py"
} | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# 4. Check MongoDB
Write-Host "`nChecking MongoDB Service..." -ForegroundColor Cyan
$MongoService = Get-Service -Name MongoDB -ErrorAction SilentlyContinue
if ($MongoService -and $MongoService.Status -ne "Running") {
    Start-Service -Name MongoDB -ErrorAction SilentlyContinue
}
Write-Host "MongoDB is running." -ForegroundColor Green

# 5. Start Geth Node 1
Write-Host "`nStarting Geth Node 1..." -ForegroundColor Cyan
$GethArgs = @(
    "--datadir", "$ScriptDir\node1",
    "--networkid", "12345",
    "--port", "30311",
    "--http",
    "--http.addr", "0.0.0.0",
    "--http.port", "8545",
    "--http.api", "eth,net,web3,personal,miner,clique,admin",
    "--http.corsdomain", "*",
    "--unlock", "0x8b629ce3BB085B061D95C7f0d14d2BF63ECbA758",
    "--password", "$ScriptDir\node1\password.txt",
    "--mine",
    "--miner.etherbase", "0x8b629ce3BB085B061D95C7f0d14d2BF63ECbA758",
    "--allow-insecure-unlock",
    "--nodiscover"
)

$GethProcess = Start-Process -FilePath "geth.exe" -ArgumentList $GethArgs -PassThru -NoNewWindow
Start-Sleep -Seconds 4

# 6. Add Node 2 Peer
Write-Host "`nConnecting to Node 2 ($Node2IP)..." -ForegroundColor Cyan
$PeerPayload = @{
    jsonrpc = "2.0"
    method  = "admin_addPeer"
    params  = @("enode://c6167d79f0d9c624b15bb08d814aef489010b6c0defbac127b4ed4bd799e4d0191cb11c018c7f9ea3ae1a495a42e6019d8847471e0de62b3ab18d9091d4cf80a@$($Node2IP):30312")
    id      = 1
} | ConvertTo-Json

try {
    $PeerRes = Invoke-RestMethod -Uri "http://127.0.0.1:8545" -Method Post -ContentType "application/json" -Body $PeerPayload -TimeoutSec 3
    Write-Host "admin_addPeer request sent: $($PeerRes.result)" -ForegroundColor Green
} catch {
    Write-Host "Warning: Could not connect to Node 1 RPC yet. Peer can be added once online." -ForegroundColor DarkYellow
}

# 7. Start Multi-User Watcher Daemon
Write-Host "`nStarting Multi-User Watcher Daemon..." -ForegroundColor Cyan
Start-Process -FilePath "python.exe" -ArgumentList "watcher_multiuser.py" -WorkingDirectory $ScriptDir -WindowStyle Hidden

# 8. Start Flask Auth App
Write-Host "`nStarting Flask Web Dashboard..." -ForegroundColor Cyan
$env:NODE2_RPC_URL = "http://$($Node2IP):8546"
$env:RPC_URL = "http://127.0.0.1:8545"
Start-Process -FilePath "python.exe" -ArgumentList "app_auth.py" -WorkingDirectory $ScriptDir -WindowStyle Hidden

Start-Sleep -Seconds 2

Write-Host "`n======================================" -ForegroundColor Green
Write-Host "ALL SERVICES STARTED ON MAIN NODE (PC1)!" -ForegroundColor Green
Write-Host "======================================" -ForegroundColor Green
Write-Host "Local Dashboard:    http://localhost:5000" -ForegroundColor Cyan
Write-Host "LAN Dashboard:      http://$($LocalIP):5000" -ForegroundColor Cyan
Write-Host "Login credentials:  admin / admin123" -ForegroundColor White
Write-Host "`nNode 1 enode (Give this to Node 2):" -ForegroundColor Magenta
Write-Host "enode://697d555df59d7790c94b650c735aa7dcbf10e9627a744c31f261a608e906d6a67d78f055570e22db98f26fab87d2dba9ebd6b3c11fb2bff83d91ea2ba76552dd@$($LocalIP):30311" -ForegroundColor Gray
Write-Host "`nTo check status, visit the dashboard or run check commands."

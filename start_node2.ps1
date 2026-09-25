# LogChain Node 2 Windows Startup Script
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  LOGCHAIN NODE 2 STARTUP SCRIPT      " -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# 1. Ensure directory and password file exist
$Node2Dir = Join-Path $ScriptDir "node2"
if (-not (Test-Path $Node2Dir)) {
    New-Item -ItemType Directory -Path $Node2Dir -Force | Out-Null
}

$PasswordFile = Join-Path $Node2Dir "password.txt"
if (-not (Test-Path $PasswordFile)) {
    Set-Content -Path $PasswordFile -Value "node2" -NoNewline
}

# 2. Check and initialize genesis if needed
$GethDataDir = Join-Path $Node2Dir "geth"
$GenesisFile = Join-Path $ScriptDir "genesis.json"
if (-not (Test-Path $GethDataDir)) {
    Write-Host "`nInitializing genesis block for Node 2..." -ForegroundColor Yellow
    & geth --datadir $Node2Dir init $GenesisFile
    Start-Sleep -Seconds 2
}

# 3. Kill existing geth processes on Node 2
Write-Host "`nStopping any running Geth processes..." -ForegroundColor DarkYellow
Get-Process geth -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# 4. Check if validator account exists
Write-Host "`nChecking Node 2 accounts..." -ForegroundColor Cyan
$AccountOutput = & geth --datadir $Node2Dir account list 2>&1
Write-Host "$AccountOutput"

$AccountAddress = "0x853402246552c3F46C3738a56109E2dcdb6cdCE3"
$HasAccount = $AccountOutput -match "853402246552c3F46C3738a56109E2dcdb6cdCE3"

if (-not $HasAccount) {
    Write-Host "`nValidator account 0x853402246552c3F46C3738a56109E2dcdb6cdCE3 not found in node2\keystore." -ForegroundColor Yellow
    Write-Host "Creating a local node account..." -ForegroundColor Yellow
    $NewAcc = & geth --datadir $Node2Dir account new --password $PasswordFile 2>&1
    Write-Host "$NewAcc"
}

# 5. Launch Geth Node 2
Write-Host "`nStarting Geth Node 2 on Port 30312 / RPC 8546..." -ForegroundColor Cyan

$GethArgs = @(
    "--datadir", $Node2Dir,
    "--networkid", "12345",
    "--port", "30312",
    "--http",
    "--http.addr", "0.0.0.0",
    "--http.port", "8546",
    "--http.api", "eth,net,web3,personal,miner,clique,admin",
    "--http.corsdomain", "*",
    "--password", $PasswordFile,
    "--allow-insecure-unlock",
    "--nodiscover"
)

if ($HasAccount) {
    $GethArgs += @(
        "--unlock", $AccountAddress,
        "--mine",
        "--miner.etherbase", $AccountAddress
    )
}

$GethProc = Start-Process -FilePath "geth.exe" -ArgumentList $GethArgs -PassThru -NoNewWindow
Start-Sleep -Seconds 4

# 6. Connect to Node 1 (Main Node)
$Node1IP = "10.58.12.19"
Write-Host "`nConnecting to Node 1 at $Node1IP..." -ForegroundColor Cyan

$PeerPayload = @{
    jsonrpc = "2.0"
    method  = "admin_addPeer"
    params  = @("enode://697d555df59d7790c94b650c735aa7dcbf10e9627a744c31f261a608e906d6a67d78f055570e22db98f26fab87d2dba9ebd6b3c11fb2bff83d91ea2ba76552dd@$($Node1IP):30311")
    id      = 1
} | ConvertTo-Json

try {
    $PeerRes = Invoke-RestMethod -Uri "http://127.0.0.1:8546" -Method Post -ContentType "application/json" -Body $PeerPayload -TimeoutSec 3
    Write-Host "admin_addPeer to Node 1 sent: $($PeerRes.result)" -ForegroundColor Green
} catch {
    Write-Host "Warning: Could not connect to Node 2 RPC. It may still be starting." -ForegroundColor Yellow
}

Start-Sleep -Seconds 2

# Check peer count
try {
    $PeerCountRes = Invoke-RestMethod -Uri "http://127.0.0.1:8546" -Method Post -ContentType "application/json" -Body '{"jsonrpc":"2.0","method":"net_peerCount","params":[],"id":1}' -TimeoutSec 3
    Write-Host "`nCurrent Peer Count: $($PeerCountRes.result)" -ForegroundColor White
} catch {}

Write-Host "`n======================================" -ForegroundColor Green
Write-Host "NODE 2 IS RUNNING ON WINDOWS!" -ForegroundColor Green
Write-Host "RPC Endpoint: http://127.0.0.1:8546" -ForegroundColor Cyan
Write-Host "P2P Port:     30312" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Green

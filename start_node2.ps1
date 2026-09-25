param(
    [switch]$Reset
)

# LogChain Node 2 Windows Startup Script
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  LOGCHAIN NODE 2 STARTUP SCRIPT      " -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Node2Dir = Join-Path $ScriptDir "node2"
$GethDataDir = Join-Path $Node2Dir "geth"
$GenesisFile = Join-Path $ScriptDir "genesis.json"
$BinDir = Join-Path $ScriptDir "bin"
$LocalGeth = Join-Path $BinDir "geth.exe"
$Node1IP = "10.58.12.19"
$Node1Enode = "enode://d8f8982805ac294c6773c1b9c436f77e994a4575aebf04ae61369e1e9858e1509461d8cab8b8d40d61e962f881a05dba378bbdc754d31096dd69f5382a9c824b@$($Node1IP):30311"

# 1. Ensure compatible Geth v1.13.14
$GethExe = "geth.exe"
if (Test-Path $LocalGeth) {
    $GethExe = $LocalGeth
} else {
    $VerStr = & geth version 2>&1 | Select-String "Version:"
    if ($VerStr -notmatch "1\.13\.") {
        Write-Host "`n[!] Detected Geth version without Clique PoA support ($VerStr)." -ForegroundColor Yellow
        Write-Host "--> Automatically downloading compatible Geth v1.13.14 (official archive)..." -ForegroundColor Cyan
        
        New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
        $ZipPath = Join-Path $BinDir "geth-1.13.14.zip"
        
        try {
            curl.exe -L -o $ZipPath "https://gethstore.blob.core.windows.net/builds/geth-windows-amd64-1.13.14-2bd6bd01.zip"
        } catch {
            Invoke-WebRequest -Uri "https://gethstore.blob.core.windows.net/builds/geth-windows-amd64-1.13.14-2bd6bd01.zip" -OutFile $ZipPath
        }
        
        Write-Host "Extracting Geth v1.13.14..." -ForegroundColor Cyan
        Expand-Archive -Path $ZipPath -DestinationPath $BinDir -Force
        
        $Extracted = Get-ChildItem -Path $BinDir -Recurse -Filter "geth.exe" | Where-Object { $_.FullName -ne $LocalGeth } | Select-Object -First 1
        if ($Extracted) {
            Copy-Item -Path $Extracted.FullName -Destination $LocalGeth -Force
            $GethExe = $LocalGeth
            Write-Host "Successfully installed Geth v1.13.14 to: $LocalGeth" -ForegroundColor Green
        }
        
        # Clean incompatible database from v1.14 run
        if (Test-Path $GethDataDir) {
            Write-Host "Cleaning incompatible database from previous run..." -ForegroundColor Yellow
            Remove-Item -Path $GethDataDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
}

# 2. Stop running Geth processes cleanly & free ports
Write-Host "`nStopping any running Geth processes and freeing ports..." -ForegroundColor DarkYellow
Get-Process geth -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

$busyPorts = Get-NetTCPConnection -LocalPort 8546, 30312 -ErrorAction SilentlyContinue
if ($busyPorts) {
    $busyPorts | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
        Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
    }
    Start-Sleep -Seconds 1
}

while (Get-Process geth -ErrorAction SilentlyContinue) {
    Start-Sleep -Milliseconds 500
}

# 3. Ensure directory and password file exist
if (-not (Test-Path $Node2Dir)) {
    New-Item -ItemType Directory -Path $Node2Dir -Force | Out-Null
}

$PasswordFile = Join-Path $Node2Dir "password.txt"
if (-not (Test-Path $PasswordFile)) {
    Set-Content -Path $PasswordFile -Value "node2" -NoNewline
}

if ($Reset -and (Test-Path $GethDataDir)) {
    Write-Host "`n-Reset flag passed: Wiping existing Node 2 chain database..." -ForegroundColor Yellow
    Remove-Item -Path $GethDataDir -Recurse -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

# 4. Check and initialize genesis with v1.13.14
Write-Host "`nInitializing genesis block..." -ForegroundColor Cyan
$InitOutput = & $GethExe --datadir $Node2Dir init $GenesisFile 2>&1
Write-Host "$InitOutput"

if ("$InitOutput" -match "incompatible genesis|Failed to write genesis block") {
    Write-Host "`n[!] Incompatible genesis detected in database." -ForegroundColor Yellow
    Write-Host "--> Automatically wiping outdated node2/geth database and re-initializing with new genesis..." -ForegroundColor Yellow
    Remove-Item -Path $GethDataDir -Recurse -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    $InitOutput = & $GethExe --datadir $Node2Dir init $GenesisFile 2>&1
    Write-Host "$InitOutput"
}

# 5. Check if accounts exist
Write-Host "`nChecking Node 2 accounts..." -ForegroundColor Cyan
$AccountOutput = & $GethExe --datadir $Node2Dir account list 2>&1
Write-Host "$AccountOutput"

$AccountAddress = "0x853402246552c3F46C3738a56109E2dcdb6cdCE3"
$HasAccount = $AccountOutput -match "853402246552c3F46C3738a56109E2dcdb6cdCE3"

if (-not $HasAccount) {
    Write-Host "`nCreating local account for Node 2 peer..." -ForegroundColor Yellow
    $NewAcc = & $GethExe --datadir $Node2Dir account new --password $PasswordFile 2>&1
    Write-Host "$NewAcc"
}

# 6. Launch Geth Node 2 in a dedicated window
Write-Host "`nStarting Geth Node 2 on Port 30312 / RPC 8546 in separate window..." -ForegroundColor Cyan

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

$GethProc = Start-Process -FilePath $GethExe -ArgumentList $GethArgs -PassThru
Start-Sleep -Seconds 4

# 7. Connect to Node 1 (Main Node)
Write-Host "`nConnecting to Main Node 1 at $Node1IP..." -ForegroundColor Cyan

$PeerPayload = @{
    jsonrpc = "2.0"
    method  = "admin_addPeer"
    params  = @($Node1Enode)
    id      = 1
} | ConvertTo-Json

try {
    $PeerRes = Invoke-RestMethod -Uri "http://127.0.0.1:8546" -Method Post -ContentType "application/json" -Body $PeerPayload -TimeoutSec 3
    Write-Host "admin_addPeer to Node 1 response: $($PeerRes.result)" -ForegroundColor Green
} catch {
    Write-Host "Warning: Could not connect to Node 2 RPC yet. Retrying in 2 seconds..." -ForegroundColor Yellow
    Start-Sleep -Seconds 2
    try {
        $PeerRes = Invoke-RestMethod -Uri "http://127.0.0.1:8546" -Method Post -ContentType "application/json" -Body $PeerPayload -TimeoutSec 3
        Write-Host "admin_addPeer to Node 1 response: $($PeerRes.result)" -ForegroundColor Green
    } catch {}
}

Start-Sleep -Seconds 2

# Check peer count
try {
    $PeerCountRes = Invoke-RestMethod -Uri "http://127.0.0.1:8546" -Method Post -ContentType "application/json" -Body '{"jsonrpc":"2.0","method":"net_peerCount","params":[],"id":1}' -TimeoutSec 3
    Write-Host "`nCurrent Peer Count on Node 2: $($PeerCountRes.result)" -ForegroundColor White
} catch {}

Write-Host "`n======================================" -ForegroundColor Green
Write-Host "NODE 2 IS RUNNING ON WINDOWS!" -ForegroundColor Green
Write-Host "RPC Endpoint: http://127.0.0.1:8546" -ForegroundColor Cyan
Write-Host "P2P Port:     30312" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Green

# Remove the separate iroad_admin Docker stack (redis on 6380, web on 8000).
# Leaves iroad-client-test (iroad-redis / iroad-web on 6379 / 8001) running.
#
# Usage: .\scripts\stop-admin-stack.ps1

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$IroadAdminRepo = "D:\iroad"

Write-Host "Stopping iroad_admin Docker stack..." -ForegroundColor Cyan

# By compose project name (covers iroad-admin-redis-1, iroad-admin-web-1, etc.)
docker compose -p iroad_admin down --remove-orphans
if ($LASTEXITCODE -ne 0) {
    Write-Host "Project iroad_admin down failed or was not running (continuing)." -ForegroundColor Yellow
}

# Admin compose file (redis-only stack in D:\iroad)
$adminCompose = Join-Path $IroadAdminRepo "docker-compose.admin.yml"
if (Test-Path $adminCompose) {
    docker compose -f $adminCompose down --remove-orphans
}

# Force-remove leftover admin containers if any remain
$adminContainers = @(
    "iroad-admin-redis-1",
    "iroad-admin-web-1",
    "iroad-admin-redis",
    "iroad-admin-web"
)
foreach ($name in $adminContainers) {
    $exists = docker ps -a --filter "name=^/${name}$" --format "{{.Names}}" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Docker is not reachable. Start Docker Desktop and run this script again." -ForegroundColor Red
        exit 1
    }
    if ($exists) {
        Write-Host "Removing container $name..." -ForegroundColor Yellow
        docker rm -f $name | Out-Null
    }
}

Write-Host ""
Write-Host "Starting iroad-client-test (redis + web)..." -ForegroundColor Cyan
Push-Location $Root
try {
    docker compose up -d redis web
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Failed to start iroad-client-test. Check Docker Desktop is running." -ForegroundColor Red
        exit 1
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "Waiting for Redis on localhost:6379..." -ForegroundColor Cyan
$ready = $false
for ($i = 0; $i -lt 20; $i++) {
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("127.0.0.1", 6379)
        $tcp.Close()
        $ready = $true
        break
    } catch {
        Start-Sleep -Seconds 1
    }
}

if ($ready) {
    Write-Host "Redis is ready on 127.0.0.1:6379" -ForegroundColor Green
} else {
    Write-Host "Redis not responding on 6379 yet. Run docker ps to check." -ForegroundColor Yellow
}

Write-Host ""
docker ps --filter "name=iroad-" --format "table {{.Names}}\t{{.Ports}}\t{{.Status}}"
Write-Host ""
Write-Host "Done. iroad_admin removed. App URL: http://127.0.0.1:8001" -ForegroundColor Green

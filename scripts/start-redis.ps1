# Start Redis for local Django development (docker-compose service).
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

Write-Host "Starting Redis from docker-compose..." -ForegroundColor Cyan
docker compose -f "$Root\docker-compose.yml" up -d redis
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Failed to start Redis. Ensure Docker Desktop is running, then retry." -ForegroundColor Red
    exit 1
}

Write-Host "Waiting for Redis on localhost:6379..." -ForegroundColor Cyan
$ready = $false
for ($i = 0; $i -lt 15; $i++) {
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

if (-not $ready) {
    Write-Host "Redis container started but port 6379 is not accepting connections yet." -ForegroundColor Yellow
    exit 1
}

Write-Host "Redis is ready on 127.0.0.1:6379" -ForegroundColor Green
Push-Location $Root
python manage.py check_redis
Pop-Location

# Delete all round-trip bookings (trip_type = Round) from the tenant database.
#
# Preview (no deletes):
#   .\scripts\delete_round_trip_jobs.ps1 -DryRun
#
# Delete:
#   .\scripts\delete_round_trip_jobs.ps1
#
# Custom schema:
#   .\scripts\delete_round_trip_jobs.ps1 -Schema "t_bb773f861f3048748c0a7f0ffbee0df6"

param(
    [string]$Schema = "t_bb773f861f3048748c0a7f0ffbee0df6",
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$argsList = @("manage.py", "delete_round_trip_jobs", "--schema=$Schema")
if ($DryRun) {
    $argsList += "--dry-run"
} else {
    $argsList += "--confirm"
}

Write-Host "Running: python $($argsList -join ' ')"
python @argsList
exit $LASTEXITCODE

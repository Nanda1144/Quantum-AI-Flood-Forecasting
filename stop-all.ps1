#!/usr/bin/env pwsh
# =============================================================================
# Q-FLARE — Stop All Services
# Kills all processes running on ports 8000, 8100, 3000, 5173.
# =============================================================================

Write-Host ""
Write-Host "Stopping Q-FLARE services..." -ForegroundColor Red

$ports = @(8000, 8100, 3000, 5173)

foreach ($port in $ports) {
  $pid = (Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue).OwningProcess | Select-Object -First 1
  if ($pid) {
    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
    if ($proc) {
      Write-Host "  ✖  Stopping port $port (PID $pid — $($proc.ProcessName))" -ForegroundColor Yellow
      Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    }
  } else {
    Write-Host "  –  Port $port not in use" -ForegroundColor DarkGray
  }
}

Write-Host ""
Write-Host "All Q-FLARE services stopped." -ForegroundColor Green
Write-Host ""

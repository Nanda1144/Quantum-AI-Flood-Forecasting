#!/usr/bin/env pwsh
# =============================================================================
# Q-FLARE — One-Click Full Platform Launcher
# Starts all 4 microservices in separate PowerShell windows simultaneously.
#
# Usage:  .\start-all.ps1
# Stop:   Close each window, or run  .\stop-all.ps1
# =============================================================================

$root = $PSScriptRoot

Write-Host ""
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "   Q-FLARE Quantum-AI Flood Forecasting Platform" -ForegroundColor Cyan
Write-Host "   Starting all services..." -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""

# ── Helper: open a new PowerShell window with a title ────────────────────────
function Start-Service {
  param(
    [string]$Title,
    [string]$WorkDir,
    [string]$Command,
    [string]$Color
  )
  Write-Host "  ▶  Starting $Title ..." -ForegroundColor $Color
  Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "& { `$host.UI.RawUI.WindowTitle = '$Title'; cd '$WorkDir'; $Command }"
}

# ── 1. AI Forecasting Service (FastAPI :8000) ─────────────────────────────────
Start-Service `
  -Title   "Q-FLARE | AI Service :8000" `
  -WorkDir "$root\ai-service" `
  -Command "if (-not (Test-Path .venv)) { python -m venv .venv }; .venv\Scripts\Activate.ps1; pip install -r requirements.txt -q; python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload" `
  -Color   "Green"

Start-Sleep -Seconds 2

# ── 2. Quantum Optimization Service (FastAPI :8100) ───────────────────────────
Start-Service `
  -Title   "Q-FLARE | Quantum Service :8100" `
  -WorkDir "$root\quantum-service" `
  -Command "if (-not (Test-Path .venv)) { python -m venv .venv }; .venv\Scripts\Activate.ps1; pip install -r requirements.txt -q; python -m uvicorn app.main:app --host 0.0.0.0 --port 8100 --reload" `
  -Color   "Magenta"

Start-Sleep -Seconds 2

# ── 3. Node.js API Gateway (Express :3000) ────────────────────────────────────
Start-Service `
  -Title   "Q-FLARE | Backend Gateway :3000" `
  -WorkDir "$root\backend" `
  -Command "npm install --silent; npm run dev" `
  -Color   "Yellow"

Start-Sleep -Seconds 3

# ── 4. React / Vite Frontend (dev server :5173) ───────────────────────────────
Start-Service `
  -Title   "Q-FLARE | Frontend UI :5173" `
  -WorkDir "$root\frontend" `
  -Command "npm install --silent; npm run dev" `
  -Color   "Cyan"

Start-Sleep -Seconds 4

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "========================================================" -ForegroundColor Green
Write-Host "   All 4 services are starting in separate windows!" -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Service Endpoints:" -ForegroundColor White
Write-Host "  ┌─────────────────────────────────────────────────┐" -ForegroundColor DarkGray
Write-Host "  │  AI Service       →  http://localhost:8000      │" -ForegroundColor Green
Write-Host "  │  Quantum Service  →  http://localhost:8100      │" -ForegroundColor Magenta
Write-Host "  │  Backend Gateway  →  http://localhost:3000      │" -ForegroundColor Yellow
Write-Host "  │  Frontend UI      →  http://localhost:5173      │" -ForegroundColor Cyan
Write-Host "  └─────────────────────────────────────────────────┘" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  ✅ Open your browser at:" -ForegroundColor Green
Write-Host "     http://localhost:5173/Quantum-AI-Flood-Forecasting/" -ForegroundColor White
Write-Host ""
Write-Host "  Health checks:" -ForegroundColor DarkGray
Write-Host "     http://localhost:8000/health  (AI Service)" -ForegroundColor DarkGray
Write-Host "     http://localhost:8100/health  (Quantum Service)" -ForegroundColor DarkGray
Write-Host "     http://localhost:3000/api/ai/status  (Backend)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  To stop all services: run .\stop-all.ps1 or close each window." -ForegroundColor DarkYellow
Write-Host ""

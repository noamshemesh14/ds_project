# PowerShell script to run uvicorn
Write-Host "Starting server with uvicorn..." -ForegroundColor Green
Write-Host ""

# Change to script directory
Set-Location $PSScriptRoot

# Run uvicorn
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000


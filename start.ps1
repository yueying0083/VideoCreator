$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "=== Starting Video Creator Studio ===" -ForegroundColor Cyan

$VenvPython = Join-Path $Root "apps\api\.venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Host "[1/2] Creating Python venv and installing backend deps..." -ForegroundColor Yellow
    if (Get-Command py -ErrorAction SilentlyContinue) {
        try {
            py -3.11 -m venv (Join-Path $Root "apps\api\.venv")
        } catch {
            python -m venv (Join-Path $Root "apps\api\.venv")
        }
    } else {
        python -m venv (Join-Path $Root "apps\api\.venv")
    }
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install -r (Join-Path $Root "apps\api\requirements.txt")
}

$WebModules = Join-Path $Root "apps\web\node_modules"
if (-not (Test-Path $WebModules)) {
    Write-Host "[2/2] Installing frontend dependencies..." -ForegroundColor Yellow
    Push-Location (Join-Path $Root "apps\web")
    npm install
    Pop-Location
}

Write-Host "Launching FastAPI backend on http://127.0.0.1:8000 ..." -ForegroundColor Green
$ApiProc = Start-Process -FilePath $VenvPython `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000", "--reload" `
    -WorkingDirectory (Join-Path $Root "apps\api") `
    -PassThru

Write-Host "Launching Vite frontend on http://localhost:3000 ..." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop both services." -ForegroundColor Gray

try {
    Push-Location (Join-Path $Root "apps\web")
    npm run dev
} finally {
    Pop-Location
    if ($ApiProc -and -not $ApiProc.HasExited) {
        Write-Host "Stopping FastAPI backend..." -ForegroundColor Yellow
        Stop-Process -Id $ApiProc.Id -Force -ErrorAction SilentlyContinue
    }
}

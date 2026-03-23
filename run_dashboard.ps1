# Ignis-Twin dashboard launcher - run in normal PowerShell (outside Cursor sandbox if needed).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "Missing .venv. Run first (uses GIL Python 3.13, not 3.13t):"
    Write-Host "  .\setup_venv.ps1"
    Write-Host "  .\.venv\Scripts\python.exe -m pip install -r requirements-ui.txt"
    exit 1
}

# Streamlit needs pandas 2.x; free-threaded Python 3.13 has no pandas 2.x wheels - source build fails.
$checkPy = @'
import sys
if hasattr(sys, "_is_gil_enabled") and not sys._is_gil_enabled():
    raise SystemExit(2)
raise SystemExit(0)
'@
& $py -c $checkPy 2>$null
if ($LASTEXITCODE -eq 2) {
    Write-Host ""
    Write-Host 'This venv uses FREE-THREADED Python 3.13. Streamlit needs pandas 2.x wheels; this build has none - pip tries to compile pandas and needs MSVC.' -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Fix: recreate venv with Python 3.12:" -ForegroundColor Cyan
    Write-Host "  Remove-Item -Recurse -Force .\.venv"
    Write-Host "  py -3.12 -m venv .venv"
    Write-Host "  .\.venv\Scripts\python.exe -m pip install -U pip"
    Write-Host "  .\.venv\Scripts\python.exe -m pip install -r requirements-ui.txt"
    Write-Host "  .\.venv\Scripts\python.exe -m streamlit run dashboard.py"
    Write-Host ""
    exit 1
}

Write-Host "Installing UI dependencies..."
& $py -m pip install -U pip
& $py -m pip install -r requirements-ui.txt
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Starting Streamlit..."
& $py -m streamlit run dashboard.py

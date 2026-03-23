# Create .venv with standard (GIL) Python 3.13 — avoids free-threading 3.13t as default `py`.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (Test-Path .\.venv) { Remove-Item -Recurse -Force .\.venv }

$gil = "C:\Program Files\Python313\python.exe"
if (-not (Test-Path $gil)) {
    Write-Host "Standard Python not at $gil — trying: py -3.13 -m venv .venv"
    py -3.13 -m venv .venv
    if (-not (Test-Path .\.venv\Scripts\python.exe)) {
        Write-Host "Failed. Install Python 3.13 (64-bit) from python.org or use py -3.12 -m venv .venv"
        exit 1
    }
} else {
    & $gil -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install -U pip
Write-Host "OK: .venv created. Verify (should be False):"
.\.venv\Scripts\python.exe -c "import sys; print('free-threaded:', hasattr(sys,'_is_gil_enabled') and not sys._is_gil_enabled())"
Write-Host "Pipeline:  .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
Write-Host "Dashboard: .\.venv\Scripts\python.exe -m pip install -r requirements-ui.txt"

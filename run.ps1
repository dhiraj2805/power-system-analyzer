# Power System Analysis AI Tool - Launch Script
# Run this from the project root: .\run.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot

Write-Host "=== Power System Analysis AI Tool ===" -ForegroundColor Cyan
Write-Host "Checking / installing dependencies..." -ForegroundColor Yellow

# Install / upgrade requirements
python -m pip install -r "$ProjectRoot\requirements.txt" --quiet

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: pip install failed. Make sure Python 3.9+ is on PATH." -ForegroundColor Red
    exit 1
}

Write-Host "Starting Streamlit application..." -ForegroundColor Green
Write-Host "Open http://localhost:8501 in your browser.`n" -ForegroundColor Cyan

python -m streamlit run "$ProjectRoot\app.py" --server.port 8501

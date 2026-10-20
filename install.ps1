# One-time setup on Windows. Double-click install.bat, which runs this.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "Installing uv (Python manager)..."
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    $env:Path = "$env:USERPROFILE\.local\bin;$env:Path"
}

Write-Host "Installing Python and dependencies..."
uv sync

Write-Host "Installing the browser used to fill HRStop..."
uv run playwright install chromium

Write-Host ""
Write-Host "Done. Double-click start.bat to open Timesheet Filler."

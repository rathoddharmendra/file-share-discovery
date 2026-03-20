#requires -Version 5.1

param(
  [int]$Port = 5000,
  [string]$Host = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvPath = Join-Path $repoRoot ".venv"

if (-not (Test-Path (Join-Path $venvPath "Scripts\\python.exe"))) {
  Write-Host "Virtualenv not found. Run: .\scripts\setup_windows.ps1"
  exit 1
}

$envPath = Join-Path ([Environment]::GetFolderPath("UserProfile")) ".isilon_discovery.env"
if (Test-Path $envPath) {
  $env:ISILON_ENV_FILE = $envPath
}

$python = Join-Path $venvPath "Scripts\\python.exe"
$flask = Join-Path $venvPath "Scripts\\flask.exe"

Write-Host "Starting web app (Flask dev server):"
Write-Host "  http://$Host`:$Port"

& $python -m flask --app webapp.app run --host $Host --port $Port --debug


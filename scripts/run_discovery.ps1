#requires -Version 5.1

param(
  [string]$Inventory = ".\\inventory.yaml",
  [string]$Node = ""
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

$py = Join-Path $venvPath "Scripts\\python.exe"

$args = @("main.py", "--inventory", $Inventory)
if ($Node -and $Node.Trim().Length -gt 0) {
  $args += @("--node", $Node)
}

Write-Host "Running discovery:"
Write-Host "  $py $($args -join ' ')"

& $py $args


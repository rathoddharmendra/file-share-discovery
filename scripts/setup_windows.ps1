#requires -Version 5.1

<#
Windows setup script for local use.

What it does:
  - Ensures the required Python version exists (best-effort; prompts if needed)
  - Creates a local virtualenv (.venv) inside this repo
  - Installs Python dependencies from requirements.txt
  - Creates ~/.isilon_discovery.env from examples/.env.example (if missing)
  - Creates inventory.yaml from examples/inventory.yaml.example (if missing)
  - Creates a default snapshots/ folder

Run from PowerShell:
  .\scripts\setup_windows.ps1
#>

param(
  [string]$RequiredPython = "3.11",
  [string]$RequiredPythonFull = "3.11.9",
  [switch]$SkipPythonInstall
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot

function Get-UserHome {
  return [Environment]::GetFolderPath("UserProfile")
}

function Test-PythonVersion {
  param([string]$MajorMinor)

  # Uses the Windows Python launcher when available.
  try {
    $code = "import sys; print('.'.join(map(str, sys.version_info[:2])))"
    $out = & py -$MajorMinor -c $code 2>$null
    if ($LASTEXITCODE -eq 0 -and $out) { return $out.Trim() }
  } catch {
    # ignore
  }

  try {
    $out = & python -c "import sys; print('.'.join(map(str, sys.version_info[:2])))" 2>$null
    if ($LASTEXITCODE -eq 0 -and $out) { return $out.Trim() }
  } catch {
    # ignore
  }

  return $null
}

function Ensure-Python {
  param([string]$MajorMinor, [string]$FullVersion, [switch]$SkipInstall)

  $current = Test-PythonVersion -MajorMinor $MajorMinor
  if ($current) {
    Write-Host "Python detected: $current"
    return
  }

  if ($SkipInstall) {
    throw "Python $MajorMinor is not detected. Install Python and rerun, or run with -SkipPythonInstall:$false."
  }

  Write-Warning "Python $MajorMinor is not detected. Attempting to install Python $FullVersion (amd64) from python.org."

  $installerUrl = "https://www.python.org/ftp/python/$FullVersion/python-$FullVersion-amd64.exe"
  $installerPath = Join-Path $env:TEMP ("python-" + $FullVersion + "-amd64.exe")

  try {
    Write-Host "Downloading: $installerUrl"
    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing

    # Silent install (per-user). If this fails, rerun and install manually.
    $silentArgs = "/quiet InstallAllUsers=0 PrependPath=1 Include_test=0"
    Write-Host "Installing Python $FullVersion..."
    $proc = Start-Process -FilePath $installerPath -ArgumentList $silentArgs -Wait -PassThru
    if ($proc.ExitCode -ne 0) {
      throw "Installer exit code: $($proc.ExitCode)"
    }
  } catch {
    Write-Warning "Auto-install failed: $($_.Exception.Message)"
    Write-Host "Please install Python $MajorMinor manually from https://www.python.org/ and rerun."
    throw
  } finally {
    if (Test-Path $installerPath) {
      Remove-Item -Force $installerPath -ErrorAction SilentlyContinue
    }
  }

  $after = Test-PythonVersion -MajorMinor $MajorMinor
  if (-not $after) {
    throw "Python install completed, but Python $MajorMinor is still not detected."
  }
  Write-Host "Python installed successfully: $after"
}

function Ensure-Venv {
  param([string]$VenvPath)

  if (-not (Test-Path $VenvPath)) {
    Write-Host "Creating virtual environment: $VenvPath"
    & py -$RequiredPython -m venv $VenvPath
  } else {
    Write-Host "Using existing virtual environment: $VenvPath"
  }
}

function Invoke-VenvPip {
  param([string]$VenvPath, [string[]]$Args)
  $pip = Join-Path $VenvPath "Scripts\\pip.exe"
  if (-not (Test-Path $pip)) {
    throw "pip not found at: $pip"
  }
  & $pip @Args
}

function Copy-IfMissing {
  param([string]$SourcePath, [string]$TargetPath)

  if (-not (Test-Path $TargetPath)) {
    Write-Host "Creating: $TargetPath"
    Copy-Item -Force $SourcePath $TargetPath
  }
}

# --- Python ---
Ensure-Python -MajorMinor $RequiredPython -FullVersion $RequiredPythonFull -SkipInstall:$SkipPythonInstall

# --- Virtualenv + dependencies ---
$venvPath = Join-Path $repoRoot ".venv"
Ensure-Venv -VenvPath $venvPath

Invoke-VenvPip -VenvPath $venvPath -Args @("install", "--upgrade", "pip", "setuptools", "wheel")
Invoke-VenvPip -VenvPath $venvPath -Args @("install", "-r", (Join-Path $repoRoot "requirements.txt"))

# --- Config files ---
$home = Get-UserHome
$envTarget = Join-Path $home ".isilon_discovery.env"
$envExample = Join-Path $repoRoot "examples/.env.example"
Copy-IfMissing -SourcePath $envExample -TargetPath $envTarget

$inventoryTarget = Join-Path $repoRoot "inventory.yaml"
$inventoryExample = Join-Path $repoRoot "examples/inventory.yaml.example"
Copy-IfMissing -SourcePath $inventoryExample -TargetPath $inventoryTarget

# --- Runtime folders ---
$snapshotsDir = Join-Path $repoRoot "snapshots"
if (-not (Test-Path $snapshotsDir)) {
  New-Item -ItemType Directory -Path $snapshotsDir | Out-Null
}

Write-Host "`nSetup completed."
Write-Host "Next:"
Write-Host "  1) Edit $envTarget and set ISILON_PASSWORD + FLASK_SECRET_KEY"
Write-Host "  2) Edit $inventoryTarget with your Isilon nodes"
Write-Host "  3) Run: .\scripts\run_discovery.ps1"
Write-Host "  4) Run: .\scripts\run_webapp.ps1"

# --- PowerShell module checks (needed for ps_enricher.ps1) ---
Write-Host "`nModule checks for PowerShell enrichment:"
try {
  $hasPssqlite = @(Get-Module -ListAvailable -Name "PSSQLite" -ErrorAction SilentlyContinue).Count -gt 0
  $hasAd = @(Get-Module -ListAvailable -Name "ActiveDirectory" -ErrorAction SilentlyContinue).Count -gt 0

  if (-not $hasPssqlite) {
    Write-Host "  - Missing module: PSSQLite"
    Write-Host "    Install example: Install-Module PSSQLite -Scope CurrentUser"
  } else {
    Write-Host "  - PSSQLite: OK"
  }

  if (-not $hasAd) {
    Write-Host "  - Missing module: ActiveDirectory"
    Write-Host "    Enable RSAT-AD-PowerShell on Windows (client) or install RSAT."
  } else {
    Write-Host "  - ActiveDirectory: OK"
  }
} catch {
  Write-Warning "Could not check PowerShell modules: $($_.Exception.Message)"
}


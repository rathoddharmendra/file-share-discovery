#requires -Version 5.1

param(
  [string]$Inventory = ".\\inventory.yaml",
  [string]$Node = "",
  [switch]$SkipWebApp
)

$ErrorActionPreference = "Stop"

Write-Host "Step 1/3: Running Python discovery..."
if ($Node -and $Node.Trim().Length -gt 0) {
  .\scripts\run_discovery.ps1 -Inventory $Inventory -Node $Node
} else {
  .\scripts\run_discovery.ps1 -Inventory $Inventory
}

Write-Host "Step 2/3: Running PowerShell AD enricher..."
Write-Host "  Note: assumes shares.db at .\\shares.db (edit if your inventory uses a different db_path)."
.\\scripts\\ps_enricher.ps1 -DbPath ".\shares.db"

if (-not $SkipWebApp) {
  Write-Host "Step 3/3: Starting web app..."
  .\scripts\run_webapp.ps1
} else {
  Write-Host "Web app skipped (--SkipWebApp)."
}


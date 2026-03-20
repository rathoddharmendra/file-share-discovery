#requires -Version 5.1

<#
.SYNOPSIS
    PowerShell AD enricher for the Isilon file share discovery database.
    Reads shares and security groups from SQLite, resolves AD group members
    and email addresses, and writes results back.

.DESCRIPTION
    This script is the PowerShell half of the enrichment pipeline.
    Python cannot reliably resolve AD group membership or user emails
    without native AD tooling, so this script handles:
      - Resolving security group SIDs to full AD objects (DN, member count)
      - Enumerating group members (Get-ADGroupMember, recursive)
      - Fetching user email / UPN from AD or Microsoft Graph API
      - Writing back to ad_members and group_members tables
      - Optionally filling dfs_pseudo_path if a DFS namespace is available

    Schedule this as a Windows Task Scheduler job AFTER the Python enricher.
    Point it at the same shares.db file (UNC path if on a shared drive).

.PARAMETER DbPath
    Full path (local or UNC) to shares.db. Default: .\shares.db

.PARAMETER UseGraph
    Switch: use Microsoft Graph API for email resolution (hybrid Azure AD).
    Requires GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET in .env
    OR as environment variables set before running.

.PARAMETER DryRun
    Switch: print what would be written without modifying the database.

.EXAMPLE
    .\scripts\ps_enricher.ps1 -DbPath "\\fileserver\discovery\shares.db"
    .\scripts\ps_enricher.ps1 -DbPath "C:\discovery\shares.db" -UseGraph -DryRun

.NOTES
    Requirements:
      - Windows PowerShell 5.1+ or PowerShell 7+
      - ActiveDirectory module (RSAT-AD-PowerShell)
      - PSSQLite module: Install-Module PSSQLite
      - Optional: MSAL.PS for Graph auth: Install-Module MSAL.PS
#>

[CmdletBinding()]
param(
    [string]$DbPath = ".\shares.db",
    [switch]$UseGraph,
    [switch]$DryRun,
    [switch]$AutoInstallModules
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

#region ── Module checks ─────────────────────────────────────────────────────

function Assert-Module {
    param([string]$Name, [switch]$AutoInstall = $false)
    if (-not (Get-Module -ListAvailable -Name $Name)) {
        if ($AutoInstall) {
            if ($Name -eq "ActiveDirectory") {
                throw "Module '$Name' is not installed. Install RSAT-AD-PowerShell (RSAT) on Windows, then rerun."
            }

            Write-Host "Installing PowerShell module: $Name"
            # Use CurrentUser so it works without admin rights.
            Install-Module $Name -Scope CurrentUser -Force -AllowClobber
        }
        else {
            throw "Required module '$Name' is not installed. Run: Install-Module $Name"
        }
    }
    Import-Module $Name -ErrorAction Stop
}

Assert-Module "PSSQLite" -AutoInstall:$AutoInstallModules
Assert-Module "ActiveDirectory" -AutoInstall:$AutoInstallModules
if ($UseGraph) { Assert-Module "MSAL.PS" -AutoInstall:$AutoInstallModules }

#endregion

#region ── Database helpers ──────────────────────────────────────────────────

function Invoke-Query {
    param([string]$Sql, [hashtable]$Params = @{})
    Invoke-SqliteQuery -DataSource $DbPath -Query $Sql -SqlParameters $Params
}

function Invoke-NonQuery {
    param([string]$Sql, [hashtable]$Params = @{})
    if ($DryRun) {
        Write-Verbose "[DRY RUN] $Sql | params: $($Params | ConvertTo-Json -Compress)"
        return
    }
    Invoke-SqliteQuery -DataSource $DbPath -Query $Sql -SqlParameters $Params
}

#endregion

#region ── Graph authentication ──────────────────────────────────────────────

$script:GraphToken = $null

function Get-GraphToken {
    $tenantId  = $env:GRAPH_TENANT_ID
    $clientId  = $env:GRAPH_CLIENT_ID
    $clientSec = $env:GRAPH_CLIENT_SECRET
    if (-not ($tenantId -and $clientId -and $clientSec)) {
        throw "Graph credentials not found. Set GRAPH_TENANT_ID, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET."
    }
    $tokenResp = Get-MsalToken `
        -TenantId $tenantId `
        -ClientId $clientId `
        -ClientSecret (ConvertTo-SecureString $clientSec -AsPlainText -Force) `
        -Scopes "https://graph.microsoft.com/.default"
    return $tokenResp.AccessToken
}

function Invoke-GraphGet {
    param([string]$Url)
    if (-not $script:GraphToken) { $script:GraphToken = Get-GraphToken }
    $resp = Invoke-RestMethod -Uri $Url -Headers @{
        Authorization = "Bearer $script:GraphToken"
        ConsistencyLevel = "eventual"
    } -Method Get
    return $resp
}

function Get-UserEmailFromGraph {
    param([string]$SamAccountName)
    try {
        $url = "https://graph.microsoft.com/v1.0/users?`$filter=onPremisesSamAccountName eq '$SamAccountName'&`$select=mail,userPrincipalName"
        $resp = Invoke-GraphGet -Url $url
        $user = $resp.value | Select-Object -First 1
        return @{ Email = $user.mail; UPN = $user.userPrincipalName }
    } catch {
        Write-Warning "Graph lookup failed for $SamAccountName : $_"
        return @{ Email = $null; UPN = $null }
    }
}

#endregion

#region ── AD resolution ─────────────────────────────────────────────────────

function Resolve-SecurityGroup {
    param([string]$GroupSid, [string]$GroupName)

    try {
        # Try by SID first (most reliable), fall back to name
        $adGroup = try {
            Get-ADGroup -Identity $GroupSid -Properties DistinguishedName, SamAccountName
        } catch {
            Get-ADGroup -Filter "Name -eq '$GroupName'" -Properties DistinguishedName
        }

        return @{
            DistinguishedName = $adGroup.DistinguishedName
            SamAccountName    = $adGroup.SamAccountName
            Resolved          = $true
        }
    } catch {
        Write-Warning "Could not resolve group '$GroupName' (SID: $GroupSid): $_"
        return @{ Resolved = $false }
    }
}

function Get-GroupMembersResolved {
    param([string]$GroupDN)
    # Recursive=true expands nested groups flat
    try {
        $members = Get-ADGroupMember -Identity $GroupDN -Recursive |
            Where-Object { $_.objectClass -eq "user" }
        return $members
    } catch {
        Write-Warning "Could not enumerate members of '$GroupDN': $_"
        return @()
    }
}

function Resolve-UserEmail {
    param([Microsoft.ActiveDirectory.Management.ADAccount]$AdUser)
    if ($UseGraph) {
        return Get-UserEmailFromGraph -SamAccountName $AdUser.SamAccountName
    }
    # On-prem AD path
    try {
        $full = Get-ADUser -Identity $AdUser.SamAccountName -Properties EmailAddress, UserPrincipalName
        return @{ Email = $full.EmailAddress; UPN = $full.UserPrincipalName }
    } catch {
        Write-Warning "Could not get email for $($AdUser.SamAccountName): $_"
        return @{ Email = $null; UPN = $null }
    }
}

#endregion

#region ── Main enrichment loop ──────────────────────────────────────────────

$timestamp = (Get-Date -Format "o")
Write-Host "`n=== PowerShell AD Enricher ===" -ForegroundColor Cyan
Write-Host "DB: $DbPath"
Write-Host "Use Graph: $UseGraph"
Write-Host "Dry run: $DryRun`n"

# Upsert run_log entry
$runId = $null
if (-not $DryRun) {
    Invoke-NonQuery -Sql @"
INSERT INTO run_log (run_type, started_at, shares_enriched, errors)
VALUES ('ps_enricher', @started_at, 0, 0)
"@ -Params @{ started_at = $timestamp }
    $runId = (Invoke-Query -Sql "SELECT last_insert_rowid() AS id").id
}

$stats = @{ GroupsResolved = 0; MembersResolved = 0; Errors = 0 }

# Load all unresolved or stale security groups
$groups = Invoke-Query -Sql @"
SELECT id, group_name, group_sid, domain
FROM security_groups
WHERE ps_resolved_at IS NULL
   OR ps_resolved_at < datetime('now', '-7 days')
ORDER BY group_name
"@

Write-Host "Groups to resolve: $($groups.Count)"

foreach ($group in $groups) {
    Write-Host "  Resolving: $($group.group_name) [$($group.group_sid)]" -ForegroundColor Gray

    $resolved = Resolve-SecurityGroup -GroupSid $group.group_sid -GroupName $group.group_name
    if (-not $resolved.Resolved) { $stats.Errors++; continue }

    # Update the security_groups row with AD details
    Invoke-NonQuery -Sql @"
UPDATE security_groups
SET distinguished_name = @dn,
    ps_resolved_at     = @ts
WHERE id = @id
"@ -Params @{ dn = $resolved.DistinguishedName; ts = $timestamp; id = $group.id }

    # Enumerate members
    $members = Get-GroupMembersResolved -GroupDN $resolved.DistinguishedName

    Invoke-NonQuery -Sql "UPDATE security_groups SET member_count = @cnt WHERE id = @id" `
        -Params @{ cnt = $members.Count; id = $group.id }

    foreach ($member in $members) {
        $emailInfo = Resolve-UserEmail -AdUser $member

        # Upsert ad_members
        Invoke-NonQuery -Sql @"
INSERT INTO ad_members (sam_account_name, display_name, email, user_principal_name, account_enabled, ps_resolved_at)
VALUES (@sam, @display, @email, @upn, @enabled, @ts)
ON CONFLICT(sam_account_name) DO UPDATE SET
    display_name        = excluded.display_name,
    email               = excluded.email,
    user_principal_name = excluded.user_principal_name,
    account_enabled     = excluded.account_enabled,
    ps_resolved_at      = excluded.ps_resolved_at
"@ -Params @{
            sam     = $member.SamAccountName
            display = $member.Name
            email   = $emailInfo.Email
            upn     = $emailInfo.UPN
            enabled = if ($member.Enabled) { 1 } else { 0 }
            ts      = $timestamp
        }

        # Get the member id (just inserted or updated)
        $memberId = (Invoke-Query -Sql "SELECT id FROM ad_members WHERE sam_account_name = @sam" `
            -Params @{ sam = $member.SamAccountName }).id

        # Upsert group_members link
        Invoke-NonQuery -Sql @"
INSERT OR IGNORE INTO group_members (group_id, member_id) VALUES (@gid, @mid)
"@ -Params @{ gid = $group.id; mid = $memberId }

        $stats.MembersResolved++
    }

    $stats.GroupsResolved++
    Write-Host "    -> $($members.Count) members resolved" -ForegroundColor Green
}

# Update shares to record ps_enriched_at
if (-not $DryRun) {
    Invoke-NonQuery -Sql @"
UPDATE shares
SET ps_enriched_at = @ts
WHERE id IN (
    SELECT DISTINCT sg.share_id
    FROM share_groups sg
    JOIN security_groups g ON g.id = sg.group_id
    WHERE g.ps_resolved_at = @ts
)
"@ -Params @{ ts = $timestamp }
}

# Finalise run log
if (-not $DryRun -and $runId) {
    Invoke-NonQuery -Sql @"
UPDATE run_log
SET finished_at     = @fin,
    shares_enriched = @enriched,
    errors          = @errors,
    notes           = @notes
WHERE id = @id
"@ -Params @{
        fin      = (Get-Date -Format "o")
        enriched = $stats.GroupsResolved
        errors   = $stats.Errors
        notes    = "Groups: $($stats.GroupsResolved) | Members: $($stats.MembersResolved)"
        id       = $runId
    }
}

Write-Host "`nDone."
Write-Host "  Groups resolved : $($stats.GroupsResolved)"
Write-Host "  Members resolved: $($stats.MembersResolved)"
Write-Host "  Errors          : $($stats.Errors)"


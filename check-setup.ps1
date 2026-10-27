<#
.SYNOPSIS
    Checks that this PC is ready for the course (module 0, lesson 0.9).

.DESCRIPTION
    Prints one PASS, WARN or FAIL line per check. Every FAIL names the lesson that fixes it.
    Changes nothing on the PC. Run it from PowerShell:

        powershell -ExecutionPolicy Bypass -File C:\binexus_lab\check-setup.ps1

    The exit code is the number of failed checks, so 0 means ready.
#>

# The versions the recordings were made with. Newer is fine; older may not match the lessons.
$MinDesktopVersion = [version]'2.159.0.0'
$MarketplaceName = 'power-bi-agentic-dev'
$MarketplaceVersion = '26.40.3'
$Plugins = @('pbip', 'semantic-models', 'reports', 'tabular-editor')
$CourseFolder = 'C:\binexus_lab'
$DataHashes = @{
    'order_lines.csv'   = 'B058911E9F50494FF12D529BDAACB9E56F1DC60F8606A090C24C1246F1E32213'
    'sales_targets.csv' = '12D418A38A8577446FD38A4D713A859D646459CA550D57ABA0E2406C33C9B68F'
}

$script:Failures = 0

function Report([string]$Status, [string]$Message, [string]$Lesson) {
    $colour = @{ PASS = 'Green'; WARN = 'Yellow'; FAIL = 'Red' }[$Status]
    $line = "[$Status] $Message"
    if ($Status -ne 'PASS' -and $Lesson) { $line += " See lesson $Lesson." }
    Write-Host $line -ForegroundColor $colour
    if ($Status -eq 'FAIL') { $script:Failures++ }
}

function Get-CommandVersion([string]$Name, [string[]]$Arguments) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) { return $null }
    try { return ((& $Name @Arguments 2>$null) | Select-Object -First 1) } catch { return $null }
}

Write-Host ''
Write-Host 'Course setup check' -ForegroundColor Cyan
Write-Host ''

# Windows: Power BI Desktop has no macOS build, and the course is written for Windows 10 or 11.
$os = Get-CimInstance Win32_OperatingSystem
if ([Environment]::OSVersion.Version.Major -ge 10 -and [Environment]::Is64BitOperatingSystem) {
    Report 'PASS' "$($os.Caption) (build $($os.BuildNumber))"
} else {
    Report 'FAIL' "$($os.Caption) is not 64-bit Windows 10 or 11." '0.2'
}

# Power BI Desktop: the Microsoft Store version or the downloaded installer.
$desktopVersion = $null
$store = Get-AppxPackage -Name 'Microsoft.MicrosoftPowerBIDesktop' -ErrorAction SilentlyContinue
if ($store) { $desktopVersion = [version]$store.Version }
$exe = Join-Path $env:ProgramFiles 'Microsoft Power BI Desktop\bin\PBIDesktop.exe'
if (-not $desktopVersion -and (Test-Path $exe)) {
    $desktopVersion = [version](Get-Item $exe).VersionInfo.FileVersion
}
if (-not $desktopVersion) {
    Report 'FAIL' 'Power BI Desktop is not installed.' '0.4'
} elseif ($desktopVersion -lt $MinDesktopVersion) {
    Report 'WARN' "Power BI Desktop $desktopVersion is older than the $MinDesktopVersion the recordings use; update it." '0.4'
} else {
    Report 'PASS' "Power BI Desktop $desktopVersion"
}

# Git, with a name and email for your commits.
$git = Get-CommandVersion 'git' @('--version')
if (-not $git) {
    Report 'FAIL' 'Git for Windows is not installed, or not on PATH.' '0.5'
} else {
    $name = (& git config --global user.name 2>$null)
    $email = (& git config --global user.email 2>$null)
    if ($name -and $email) { Report 'PASS' "$git, committing as $name" }
    else { Report 'FAIL' "$git is installed, but user.name or user.email is not set." '0.5' }
}

# VS Code.
$code = Get-CommandVersion 'code' @('--version')
if ($code) { Report 'PASS' "VS Code $code" }
else { Report 'FAIL' 'VS Code is not installed, or the code command is not on PATH.' '0.5' }

# Claude Code.
$claude = Get-CommandVersion 'claude' @('--version')
if ($claude) { Report 'PASS' "Claude Code $($claude -replace '\s*\(Claude Code\)$', '')" }
else { Report 'FAIL' 'Claude Code is not installed, or not on PATH.' '0.6' }

# The PBI Agentic Dev marketplace at the version the recordings use, and its plugins.
$pluginRoot = Join-Path $env:USERPROFILE '.claude\plugins'
$known = Join-Path $pluginRoot 'known_marketplaces.json'
$marketplace = $null
if (Test-Path $known) {
    $marketplace = (Get-Content $known -Raw | ConvertFrom-Json).$MarketplaceName
}
if (-not $marketplace) {
    Report 'FAIL' "The $MarketplaceName marketplace is not added to Claude Code." '0.7'
} else {
    $manifest = Join-Path $marketplace.installLocation '.claude-plugin\marketplace.json'
    $version = $null
    if (Test-Path $manifest) { $version = (Get-Content $manifest -Raw | ConvertFrom-Json).metadata.version }
    if ($version -eq $MarketplaceVersion) { Report 'PASS' "$MarketplaceName marketplace $version" }
    else { Report 'WARN' "$MarketplaceName marketplace is at $version; the recordings use $MarketplaceVersion." '0.7' }

    $installedFile = Join-Path $pluginRoot 'installed_plugins.json'
    $installed = @()
    if (Test-Path $installedFile) {
        $installed = @((Get-Content $installedFile -Raw | ConvertFrom-Json).plugins.PSObject.Properties.Name)
    }
    $missing = @($Plugins | Where-Object { $installed -notcontains "$_@$MarketplaceName" })
    if ($missing.Count -eq 0) { Report 'PASS' "Plugins installed: $($Plugins -join ', ')" }
    else { Report 'FAIL' "Plugins not installed: $($missing -join ', ')." '0.7' }
}

# Tabular Editor 2 or 3, registered as an external tool in Desktop.
$te = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Tabular Editor\TabularEditor.exe'),
    (Join-Path $env:ProgramFiles 'Tabular Editor 3\TabularEditor3.exe')
) | Where-Object { Test-Path $_ }
$toolsFolder = Join-Path ${env:ProgramFiles(x86)} 'Common Files\Microsoft Shared\Power BI Desktop\External Tools'
$registered = @(Get-ChildItem $toolsFolder -Filter 'tabulareditor*.pbitool.json' -ErrorAction SilentlyContinue)
if (-not $te) {
    Report 'FAIL' 'Tabular Editor 2 or 3 is not installed.' '0.8'
} elseif ($registered.Count -eq 0) {
    Report 'WARN' 'Tabular Editor is installed but does not show in Desktop''s External Tools ribbon.' '0.8'
} else {
    $versions = $te | ForEach-Object { if ($_ -like '*TabularEditor3.exe') { '3' } else { '2' } }
    Report 'PASS' "Tabular Editor $($versions -join ' and ')"
}

# Desktop Excel: the reconcile steps use its pivot tables and the Data Model.
$excel = @(
    'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe',
    'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\excel.exe'
) | Where-Object { Test-Path $_ }
if ($excel) { Report 'PASS' 'Excel (desktop)' }
else { Report 'FAIL' 'Desktop Excel is not installed; the reconcile steps need it.' '0.2' }

# The course files: cloned to C:\binexus_lab, with the CSVs exactly as published.
if (-not (Test-Path (Join-Path $CourseFolder '.git'))) {
    Report 'FAIL' "The course files are not cloned to $CourseFolder." '0.5'
} else {
    $bad = @($DataHashes.Keys | Where-Object {
        $file = Join-Path $CourseFolder "data\$_"
        -not (Test-Path $file) -or (Get-FileHash $file -Algorithm SHA256).Hash -ne $DataHashes[$_]
    })
    $tag = (& git -C $CourseFolder describe --tags --exact-match 2>$null)
    if (-not $tag) { $tag = 'no checkpoint tag' }
    if ($bad.Count -eq 0) { Report 'PASS' "Course files in $CourseFolder, at $tag" }
    else { Report 'FAIL' "These data files are missing or changed: $($bad -join ', '). Clone again, or run git checkout -- data." '0.5' }
}

Write-Host ''
if ($script:Failures -eq 0) { Write-Host 'Ready. Carry on with lesson 0.10.' -ForegroundColor Cyan }
else { Write-Host "$script:Failures check(s) failed. Fix them, then run this again." -ForegroundColor Cyan }
exit $script:Failures

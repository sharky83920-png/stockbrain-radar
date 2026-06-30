# Create a Desktop shortcut for the Dashboard launcher, with the brain icon.
# ASCII-only content on purpose (PS 5.1 mis-decodes Chinese in non-BOM files).
# Run:  powershell -ExecutionPolicy Bypass -File scripts\建立Dashboard捷徑.ps1
param(
    [string]$RepoPath = (Split-Path $PSScriptRoot -Parent),
    [string]$LinkName = "StockBrain Radar"
)

$RepoPath = (Resolve-Path $RepoPath).Path

# Find the dashboard launcher by pattern (avoids embedding the Chinese filename)
$bat = Get-ChildItem -Path $RepoPath -Filter *.bat |
       Where-Object { $_.Name -like "*Dashboard*" } |
       Select-Object -First 1
if (-not $bat) {
    Write-Host "ERROR: Dashboard .bat not found in $RepoPath" -ForegroundColor Red
    exit 1
}

$icon    = Join-Path $RepoPath "assets\brain.ico"
$desktop = [Environment]::GetFolderPath("Desktop")
$link    = Join-Path $desktop "$LinkName.lnk"

$w = New-Object -ComObject WScript.Shell
$s = $w.CreateShortcut($link)
$s.TargetPath       = $bat.FullName
$s.WorkingDirectory = $RepoPath
$s.WindowStyle      = 1
$s.Description      = "StockBrain Radar Dashboard"
if (Test-Path $icon) { $s.IconLocation = $icon }
$s.Save()

if (Test-Path $link) {
    Write-Host "OK shortcut created: $link" -ForegroundColor Green
} else {
    Write-Host "FAILED to create shortcut" -ForegroundColor Red
}

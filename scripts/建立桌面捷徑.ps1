param(
    [string]$RepoPath = (Split-Path $PSScriptRoot -Parent)
)

$RepoPath = (Resolve-Path $RepoPath).Path
$BatFile  = Join-Path $RepoPath "scripts\投資家日報_整理.bat"
$Desktop  = [Environment]::GetFolderPath("Desktop")
$LinkPath = Join-Path $Desktop "投資家日報整理.lnk"

if (-not (Test-Path $BatFile)) {
    Write-Host "ERROR: bat not found: $BatFile" -ForegroundColor Red
    Read-Host "Press Enter"
    exit 1
}

$WScript  = New-Object -ComObject WScript.Shell
$Shortcut = $WScript.CreateShortcut($LinkPath)
$Shortcut.TargetPath       = $BatFile
$Shortcut.WorkingDirectory = $RepoPath
$Shortcut.WindowStyle      = 1
$Shortcut.Description      = "StockBrain Investor Daily"
$Shortcut.IconLocation     = "shell32.dll,13"
$Shortcut.Save()

Write-Host ""
Write-Host "  Shortcut created: $LinkPath" -ForegroundColor Green
Write-Host ""
Read-Host "Press Enter"

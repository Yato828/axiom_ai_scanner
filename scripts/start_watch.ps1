param(
    [int]$Limit = 10,
    [int]$Interval = 60,
    [string]$Config = ""
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $ProjectRoot "logs"
$LogPath = Join-Path $LogDir "scanner.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

if ($Config -ne "") {
    $Arguments = "axiom_dashboard.py --config `"$Config`" watch --limit $Limit --interval $Interval"
} else {
    $Arguments = "axiom_dashboard.py watch --limit $Limit --interval $Interval"
}

Start-Process -FilePath "python" `
    -ArgumentList $Arguments `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $LogPath `
    -RedirectStandardError $LogPath `
    -WindowStyle Hidden

Write-Host "Scanner started. Log: $LogPath"

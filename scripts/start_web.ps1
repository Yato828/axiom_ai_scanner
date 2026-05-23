param(
    [int]$Port = 8080,
    [int]$Limit = 100
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

python axiom_dashboard.py web --port $Port --limit $Limit

param(
    [int]$Limit = 15,
    [string]$Config = ""
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if ($Config -ne "") {
    python memorphia_dashboard.py --config $Config scan --limit $Limit
} else {
    python memorphia_dashboard.py scan --limit $Limit
}

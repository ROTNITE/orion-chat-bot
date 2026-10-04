param(
    [ValidateSet("Run", "Menu", "InstallHosts", "RemoveHosts", "ConfigureToken", "Diagnostics", "Install")]
    [string]$Action = "Run"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Launcher = Join-Path $PSScriptRoot "launcher.py"

$map = @{
    "Run" = "run"
    "Menu" = "menu"
    "InstallHosts" = "hosts-add"
    "RemoveHosts" = "hosts-remove"
    "ConfigureToken" = "configure-token"
    "Diagnostics" = "diagnostics"
    "Install" = "install"
}

if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 $Launcher $map[$Action]
    exit $LASTEXITCODE
}
if (Get-Command python -ErrorAction SilentlyContinue) {
    & python $Launcher $map[$Action]
    exit $LASTEXITCODE
}
Write-Host "Python 3.10+ not found." -ForegroundColor Red
exit 10

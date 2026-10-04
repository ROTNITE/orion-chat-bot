param(
    [ValidateSet("Run", "Menu", "InstallHosts", "RemoveHosts", "ConfigureToken", "Diagnostics", "Install")]
    [string]$Action = "Run"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$EnvPath = Join-Path $Root ".env"
$EnvExamplePath = Join-Path $Root ".env.example"
$VenvPath = Join-Path $Root ".venv"
$VenvPython = Join-Path $VenvPath "Scripts\python.exe"
$RequirementsPath = Join-Path $Root "requirements.txt"
$RequirementsStamp = Join-Path $VenvPath ".orion_requirements.sha256"
$HostsPath = Join-Path $env:SystemRoot "System32\drivers\etc\hosts"
$BackupDir = Join-Path $Root "backups"
$HostsBegin = "# >>> ORION TELEGRAM HOSTS >>>"
$HostsEnd = "# <<< ORION TELEGRAM HOSTS <<<"
$TelegramHosts = @(
    "149.154.167.220 my.telegram.org",
    "149.154.167.220 api.telegram.org"
)

function Write-Title {
    param([string]$Text)
    Write-Host ""
    Write-Host "=== $Text ===" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Text)
    Write-Host "[OK] $Text" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Text)
    Write-Host "[!] $Text" -ForegroundColor Yellow
}

function Write-Fail {
    param([string]$Text)
    Write-Host "[X] $Text" -ForegroundColor Red
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Invoke-ElevatedAction {
    param([Parameter(Mandatory=$true)][string]$ElevatedAction)
    $argLine = "-NoLogo -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Action $ElevatedAction"
    try {
        $process = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $argLine -Wait -PassThru
        return $process.ExitCode
    }
    catch {
        Write-Fail "Administrator permission was not granted."
        return 1223
    }
}

function Get-PythonLauncher {
    try {
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 9)" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return "py" }
        }
    }
    catch { }
    try {
        if (Get-Command python -ErrorAction SilentlyContinue) {
            & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 9)" 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) { return "python" }
        }
    }
    catch { }
    return $null
}

function Ensure-Venv {
    if (Test-Path -LiteralPath $VenvPython) {
        Write-Ok "Python virtual environment found."
        return
    }

    Write-Title "First-time Python setup"
    $launcher = Get-PythonLauncher
    if ($null -eq $launcher) {
        throw "Python 3.10+ was not found. Install Python from https://www.python.org/downloads/ and enable 'Add Python to PATH'."
    }

    Write-Host "Creating .venv..."
    if ($launcher -eq "py") {
        & py -3 -m venv $VenvPath
    }
    else {
        & python -m venv $VenvPath
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $VenvPython)) {
        throw "Failed to create .venv."
    }
    Write-Ok ".venv created."
}

function Get-RequirementsHash {
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $RequirementsPath).Hash.ToLowerInvariant()
}

function Install-Dependencies {
    param([switch]$Force)
    Ensure-Venv
    $wanted = Get-RequirementsHash
    $current = ""
    if (Test-Path -LiteralPath $RequirementsStamp) {
        $current = (Get-Content -LiteralPath $RequirementsStamp -Raw).Trim()
    }
    if (-not $Force -and $current -eq $wanted) {
        Write-Ok "Python dependencies are already installed."
        return
    }

    Write-Title "Installing Python dependencies"
    & $VenvPython -m pip install -r $RequirementsPath
    if ($LASTEXITCODE -ne 0) {
        throw "pip could not install requirements.txt. Check internet access to PyPI and run ORION_MENU.cmd -> reinstall dependencies."
    }
    [IO.File]::WriteAllText($RequirementsStamp, $wanted, (New-Object Text.UTF8Encoding($false)))
    Write-Ok "Dependencies installed."
}

function Get-EnvValue {
    param([Parameter(Mandatory=$true)][string]$Key)
    if (-not (Test-Path -LiteralPath $EnvPath)) { return "" }
    foreach ($line in Get-Content -LiteralPath $EnvPath) {
        if ($line -match ('^\s*' + [regex]::Escape($Key) + '\s*=\s*(.*)$')) {
            return $Matches[1].Trim()
        }
    }
    return ""
}

function Set-EnvValue {
    param(
        [Parameter(Mandatory=$true)][string]$Key,
        [AllowEmptyString()][string]$Value
    )
    if (-not (Test-Path -LiteralPath $EnvPath)) {
        if (Test-Path -LiteralPath $EnvExamplePath) {
            Copy-Item -LiteralPath $EnvExamplePath -Destination $EnvPath
        }
        else {
            [IO.File]::WriteAllText($EnvPath, "", (New-Object Text.UTF8Encoding($false)))
        }
    }

    $lines = @(Get-Content -LiteralPath $EnvPath)
    $pattern = '^\s*' + [regex]::Escape($Key) + '\s*='
    $found = $false
    $output = New-Object System.Collections.Generic.List[string]
    foreach ($line in $lines) {
        if ($line -match $pattern) {
            if (-not $found) { $output.Add("$Key=$Value") }
            $found = $true
        }
        else {
            $output.Add($line)
        }
    }
    if (-not $found) { $output.Add("$Key=$Value") }
    [IO.File]::WriteAllLines($EnvPath, $output, (New-Object Text.UTF8Encoding($false)))
}

function Ensure-EnvSkeleton {
    if (-not (Test-Path -LiteralPath $EnvPath)) {
        if (-not (Test-Path -LiteralPath $EnvExamplePath)) { throw ".env.example is missing." }
        Copy-Item -LiteralPath $EnvExamplePath -Destination $EnvPath
        Write-Ok ".env created from template."
    }
}

function Convert-SecureToPlainText {
    param([Security.SecureString]$Secure)
    $ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($Secure)
    try { return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
    finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
}

function Read-BotToken {
    while ($true) {
        Write-Host ""
        Write-Host "Paste the bot token from @BotFather. Input is hidden." -ForegroundColor Cyan
        $secure = Read-Host "BOT_TOKEN" -AsSecureString
        $token = Convert-SecureToPlainText $secure
        if ($token -match '^\d{5,20}:[A-Za-z0-9_-]{20,}$') { return $token }
        Write-Fail "The value does not look like a BotFather bot token."
    }
}

function Configure-Token {
    Ensure-EnvSkeleton
    $token = Read-BotToken
    Set-EnvValue -Key "BOT_TOKEN" -Value $token
    Write-Ok "Token saved to .env."
}

function Ensure-Token {
    Ensure-EnvSkeleton
    $token = Get-EnvValue "BOT_TOKEN"
    if ($token -notmatch '^\d{5,20}:[A-Za-z0-9_-]{20,}$' -or $token -eq "replace-with-botfather-token") {
        Write-Title "Bot token"
        Configure-Token
    }
    else {
        Write-Ok "Bot token is configured."
    }
}

function Test-OrionTelegram {
    if (-not (Test-Path -LiteralPath $VenvPython)) { return 10 }
    Push-Location $Root
    try {
        $diagnosticOutput = @(& $VenvPython -m orion.diagnostics 2>&1)
        $diagnosticCode = $LASTEXITCODE
        foreach ($line in $diagnosticOutput) { Write-Host $line }
        return [int]$diagnosticCode
    }
    finally { Pop-Location }
}

function Read-YesNo {
    param([string]$Prompt, [bool]$Default = $false)
    $suffix = if ($Default) { "[Y/n]" } else { "[y/N]" }
    $answer = (Read-Host "$Prompt $suffix").Trim().ToLowerInvariant()
    if ($answer -eq "") { return $Default }
    return $answer -in @("y", "yes", "д", "да")
}

function Remove-ManagedHostsBlockFromText {
    param([string]$Text)
    $pattern = '(?ms)^\s*# >>> ORION TELEGRAM HOSTS >>>\s*\r?\n.*?^\s*# <<< ORION TELEGRAM HOSTS <<<\s*\r?\n?'
    return [regex]::Replace($Text, $pattern, "")
}

function Install-HostsOverrideInternal {
    if (-not (Test-IsAdministrator)) { throw "Administrator rights are required to edit hosts." }
    New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $backup = Join-Path $BackupDir "hosts-$timestamp.bak"
    Copy-Item -LiteralPath $HostsPath -Destination $backup -Force

    $content = [IO.File]::ReadAllText($HostsPath)
    $content = Remove-ManagedHostsBlockFromText $content
    $linesToAdd = New-Object System.Collections.Generic.List[string]

    foreach ($entry in $TelegramHosts) {
        $parts = $entry -split '\s+', 2
        $ip = $parts[0]
        $hostName = $parts[1]
        $hostPattern = '(?im)^\s*([^#\s]+)\s+' + [regex]::Escape($hostName) + '(?:\s|$)'
        $match = [regex]::Match($content, $hostPattern)
        if ($match.Success) {
            if ($match.Groups[1].Value -eq $ip) {
                Write-Ok "$hostName already has the requested hosts mapping; leaving the user's line untouched."
            }
            else {
                Write-Warn "$hostName already has a different hosts mapping ($($match.Groups[1].Value)). Orion will not overwrite it."
            }
        }
        else {
            $linesToAdd.Add($entry)
        }
    }

    if ($linesToAdd.Count -gt 0) {
        $block = "`r`n$HostsBegin`r`n" + (($linesToAdd | ForEach-Object { $_ }) -join "`r`n") + "`r`n$HostsEnd`r`n"
        $newContent = $content.TrimEnd([char[]]"`r`n") + $block
        [IO.File]::WriteAllText($HostsPath, $newContent, (New-Object Text.UTF8Encoding($false)))
    }
    ipconfig /flushdns | Out-Null
    Write-Ok "Managed hosts override installed. Backup: $backup"
}

function Remove-HostsOverrideInternal {
    if (-not (Test-IsAdministrator)) { throw "Administrator rights are required to edit hosts." }
    $content = [IO.File]::ReadAllText($HostsPath)
    $newContent = Remove-ManagedHostsBlockFromText $content
    if ($newContent -ne $content) {
        [IO.File]::WriteAllText($HostsPath, $newContent.TrimEnd([char[]]"`r`n") + "`r`n", (New-Object Text.UTF8Encoding($false)))
        ipconfig /flushdns | Out-Null
        Write-Ok "Orion-managed hosts block removed. Other hosts entries were not touched."
    }
    else {
        Write-Ok "No Orion-managed hosts block was present."
    }
}

function Ensure-HostsOverride {
    if (Test-IsAdministrator) {
        Install-HostsOverrideInternal
        return $true
    }
    Write-Host "Windows will ask for administrator permission to edit hosts." -ForegroundColor Cyan
    $code = Invoke-ElevatedAction -ElevatedAction "InstallHosts"
    return ($code -eq 0)
}

function Remove-HostsOverride {
    if (Test-IsAdministrator) {
        Remove-HostsOverrideInternal
        return $true
    }
    Write-Host "Windows will ask for administrator permission to edit hosts." -ForegroundColor Cyan
    $code = Invoke-ElevatedAction -ElevatedAction "RemoveHosts"
    return ($code -eq 0)
}

function Configure-Proxy {
    Ensure-EnvSkeleton
    Write-Host ""
    Write-Host "Supported examples:" -ForegroundColor Cyan
    Write-Host "  socks5://127.0.0.1:1080"
    Write-Host "  http://127.0.0.1:7890"
    Write-Host "Leave empty to disable the proxy."
    $proxy = (Read-Host "TELEGRAM_PROXY").Trim()
    if ($proxy -ne "" -and $proxy -notmatch '^(?i)(http|socks4|socks4a|socks5)://[^\s]+$') {
        Write-Fail "Unsupported proxy URL."
        return $false
    }
    Set-EnvValue -Key "TELEGRAM_PROXY" -Value $proxy
    Write-Ok $(if ($proxy) { "Proxy saved." } else { "Proxy disabled." })
    return $true
}

function Repair-NetworkIfNeeded {
    Write-Title "Telegram connection check"
    $code = Test-OrionTelegram
    if ($code -eq 0) {
        Write-Ok "Telegram Bot API connection works."
        return $true
    }

    if ($code -eq 3) {
        Write-Warn "Telegram rejected the current token."
        Configure-Token
        $code = Test-OrionTelegram
        if ($code -eq 0) { return $true }
    }

    if ($code -eq 2) {
        $proxy = Get-EnvValue "TELEGRAM_PROXY"
        if ([string]::IsNullOrWhiteSpace($proxy)) {
            Write-Warn "Direct connection failed. Trying IPv4-only mode."
            $oldIpv4 = Get-EnvValue "FORCE_IPV4"
            Set-EnvValue -Key "FORCE_IPV4" -Value "1"
            $ipv4Code = Test-OrionTelegram
            if ($ipv4Code -eq 0) {
                Write-Ok "IPv4-only mode works and was saved."
                return $true
            }
            Set-EnvValue -Key "FORCE_IPV4" -Value $(if ($oldIpv4) { $oldIpv4 } else { "0" })

            Write-Warn "IPv4-only mode did not fix the connection."
            if (Read-YesNo "Add Orion's managed Telegram hosts block?" $false) {
                if (Ensure-HostsOverride) {
                    Start-Sleep -Seconds 1
                    $hostsCode = Test-OrionTelegram
                    if ($hostsCode -eq 0) {
                        Write-Ok "Telegram works with the hosts override."
                        return $true
                    }
                    Write-Warn "The fixed hosts mapping did not restore Bot API access. You can remove it from ORION_MENU.cmd."
                }
            }
        }

        if (Read-YesNo "Configure an HTTP/SOCKS proxy for Orion?" $false) {
            if (Configure-Proxy) {
                $proxyCode = Test-OrionTelegram
                if ($proxyCode -eq 0) {
                    Write-Ok "Telegram works through the configured proxy."
                    return $true
                }
                Write-Warn "The configured proxy did not pass the Telegram check."
            }
        }
    }

    Write-Fail "Telegram connectivity check still fails. Open ORION_MENU.cmd -> Diagnostics / Proxy / Hosts."
    return $false
}

function Ensure-Ready {
    Set-Location $Root
    Ensure-Venv
    Install-Dependencies
    Ensure-Token
    if ([string]::IsNullOrWhiteSpace((Get-EnvValue "FORCE_IPV4"))) { Set-EnvValue -Key "FORCE_IPV4" -Value "0" }
    if ([string]::IsNullOrWhiteSpace((Get-EnvValue "TELEGRAM_TIMEOUT"))) { Set-EnvValue -Key "TELEGRAM_TIMEOUT" -Value "60" }
}

function Start-Orion {
    Write-Title "Starting Orion"
    Write-Host "Stop the bot with Ctrl+C. Do not close this window while you want the bot online." -ForegroundColor Cyan
    Push-Location $Root
    try {
        & $VenvPython -m orion 2>&1 | Out-Host
        $botExitCode = $LASTEXITCODE
        if ($null -eq $botExitCode) { $botExitCode = 0 }
        return [int]$botExitCode
    }
    finally { Pop-Location }
}

function Run-ProjectTests {
    Ensure-Venv
    Write-Title "Installing dev/test dependencies"
    & $VenvPython -m pip install -r (Join-Path $Root "requirements-dev.txt")
    if ($LASTEXITCODE -ne 0) { throw "Could not install test dependencies." }
    Write-Title "Running tests"
    Push-Location $Root
    try {
        & $VenvPython -m pytest -q
        return $LASTEXITCODE
    }
    finally { Pop-Location }
}

function Show-Diagnostics {
    Ensure-Ready
    Write-Title "Current network configuration"
    $proxy = Get-EnvValue "TELEGRAM_PROXY"
    $ipv4 = Get-EnvValue "FORCE_IPV4"
    Write-Host ("Proxy: " + $(if ($proxy) { "configured" } else { "off" }))
    Write-Host "IPv4-only: $ipv4"
    Write-Host "api.telegram.org DNS:"
    try { Resolve-DnsName api.telegram.org -ErrorAction Stop | Select-Object -First 4 Name,Type,IPAddress | Format-Table -AutoSize | Out-Host }
    catch { Write-Warn "DNS lookup failed: $($_.Exception.Message)" }
    Write-Host "TCP 443:"
    try {
        $tcp = Test-NetConnection api.telegram.org -Port 443 -WarningAction SilentlyContinue
        Write-Host "TcpTestSucceeded: $($tcp.TcpTestSucceeded)"
    }
    catch { Write-Warn "TCP test failed." }
    Write-Host "Bot API getMe check:"
    $code = Test-OrionTelegram
    if ($code -eq 0) { Write-Ok "Bot API is reachable and token is valid." }
    else { Write-Fail "Diagnostic exit code: $code" }
    return $code
}

function Show-Menu {
    while ($true) {
        Write-Host ""
        Write-Host "=====================================" -ForegroundColor DarkCyan
        Write-Host "              ORION CHAT" -ForegroundColor Cyan
        Write-Host "=====================================" -ForegroundColor DarkCyan
        Write-Host "[1] Start bot"
        Write-Host "[2] Change BotFather token"
        Write-Host "[3] Telegram diagnostics"
        Write-Host "[4] Configure HTTP/SOCKS proxy"
        Write-Host "[5] Install Telegram hosts override"
        Write-Host "[6] Remove Orion hosts override"
        Write-Host "[7] Reinstall Python dependencies"
        Write-Host "[8] Run project tests"
        Write-Host "[0] Exit"
        $choice = (Read-Host "Choose").Trim()
        try {
            switch ($choice) {
                "1" {
                    Ensure-Ready
                    if (Repair-NetworkIfNeeded) { $null = Start-Orion }
                }
                "2" { Ensure-EnvSkeleton; Configure-Token; $null = Test-OrionTelegram }
                "3" { $null = Show-Diagnostics }
                "4" { Ensure-EnvSkeleton; $null = Configure-Proxy; $null = Test-OrionTelegram }
                "5" { $null = Ensure-HostsOverride }
                "6" { $null = Remove-HostsOverride }
                "7" { Ensure-Venv; Install-Dependencies -Force }
                "8" { $null = Run-ProjectTests }
                "0" { return }
                default { Write-Warn "Unknown menu item." }
            }
        }
        catch { Write-Fail $_.Exception.Message }
    }
}

try {
    switch ($Action) {
        "InstallHosts" {
            Install-HostsOverrideInternal
            exit 0
        }
        "RemoveHosts" {
            Remove-HostsOverrideInternal
            exit 0
        }
        "ConfigureToken" {
            Ensure-EnvSkeleton
            Configure-Token
            exit 0
        }
        "Diagnostics" {
            $code = Show-Diagnostics
            exit $code
        }
        "Install" {
            Ensure-Ready
            exit 0
        }
        "Menu" {
            Set-Location $Root
            Show-Menu
            exit 0
        }
        "Run" {
            Set-Location $Root
            Ensure-Ready
            if (-not (Repair-NetworkIfNeeded)) { exit 2 }
            $code = Start-Orion
            exit $code
        }
    }
}
catch {
    Write-Fail $_.Exception.Message
    exit 1
}

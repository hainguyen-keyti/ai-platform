# Starts Docker Desktop if it is not running, and wakes the WSL distro so its systemd brings up the worker
# and the aip-stack timer. Does nothing when both are already up. Run by the 'AI Platform autostart' task.
param([string]$Distro = 'Ubuntu')

$log = Join-Path $env:LOCALAPPDATA 'ai-platform\ensure-windows.log'
New-Item -ItemType Directory -Force (Split-Path -Parent $log) | Out-Null
function Say([string]$text) { Add-Content -Path $log -Value ("{0:u} {1}" -f (Get-Date).ToUniversalTime(), $text) }

$docker = Join-Path $env:ProgramFiles 'Docker\Docker\Docker Desktop.exe'
if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) {
    if (Test-Path $docker) {
        Say 'Docker Desktop not running; starting it'
        Start-Process -FilePath $docker
    } else {
        Say "Docker Desktop not found at $docker"
    }
}

# A distro left stopped does not run its services; any command in it starts it, and systemd keeps it up.
$running = (wsl.exe --list --running --quiet 2>$null) -replace "`0", '' | Where-Object { $_.Trim() -eq $Distro }
if (-not $running) {
    Say "WSL distro $Distro not running; starting it"
    wsl.exe -d $Distro --exec /bin/true
}

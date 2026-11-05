# Windows half of the autostart: a scheduled task that, at sign-in and every 5 minutes, starts Docker
# Desktop if it is not running and wakes the WSL distro, whose systemd then starts the worker and the
# aip-stack timer (scripts/install-autostart.sh). Run once, from PowerShell, as your own user:
#   pwsh -File scripts\windows\install-autostart.ps1 [-Distro Ubuntu]
# Remove with: Unregister-ScheduledTask -TaskName 'AI Platform autostart' -Confirm:$false
param([string]$Distro = 'Ubuntu')

$ErrorActionPreference = 'Stop'
$taskName = 'AI Platform autostart'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$check = Join-Path $here 'ensure-windows.ps1'
$launcher = Join-Path $here 'run-hidden.vbs'

if (-not (Test-Path $check)) { throw "missing $check" }
if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { throw 'wsl.exe not found' }

# wscript runs the check with no console window flashing every 5 minutes.
$action = New-ScheduledTaskAction -Execute 'wscript.exe' -Argument ('"{0}" "{1}" "{2}"' -f $launcher, $check, $Distro)
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$repeat = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger @($atLogon, $repeat) -Settings $settings `
    -Principal $principal -Description 'Starts Docker Desktop and WSL for the AI Platform when they are not running' -Force | Out-Null
Write-Output "installed task '$taskName' (at sign-in and every 5 minutes, distro $Distro)"

' Runs ensure-windows.ps1 with no console window: run-hidden.vbs <script.ps1> <distro>
Set shell = CreateObject("WScript.Shell")
exe = "pwsh.exe"
If CreateObject("Scripting.FileSystemObject").FileExists(shell.ExpandEnvironmentStrings("%ProgramFiles%\PowerShell\7\pwsh.exe")) = False Then exe = "powershell.exe"
shell.Run exe & " -NoProfile -ExecutionPolicy Bypass -File """ & WScript.Arguments(0) & """ -Distro " & WScript.Arguments(1), 0, False

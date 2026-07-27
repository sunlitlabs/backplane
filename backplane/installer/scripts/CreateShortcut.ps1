# Small standalone helper (run via `-File`, not dot-sourced) so Python code
# can create a .lnk without needing pywin32 -- .lnk is a COM object, not a
# format Python's stdlib can write directly, so this shells out to the same
# WScript.Shell technique used across this tool ecosystem. Ported verbatim
# from py-sensor/lib/CreateShortcut.ps1. Static local script, never
# downloaded/eval'd content.

param(
    [Parameter(Mandatory)][string]$ShortcutPath,
    [Parameter(Mandatory)][string]$TargetPath,
    [string]$Arguments = '',
    [string]$WorkingDirectory = '',
    [string]$IconLocation = ''
)

$ErrorActionPreference = 'Stop'

$wshell = New-Object -ComObject WScript.Shell
$shortcut = $wshell.CreateShortcut($ShortcutPath)
$shortcut.TargetPath = $TargetPath
if ($Arguments) { $shortcut.Arguments = $Arguments }
if ($WorkingDirectory) { $shortcut.WorkingDirectory = $WorkingDirectory }
if ($IconLocation) { $shortcut.IconLocation = $IconLocation }
$shortcut.Save()

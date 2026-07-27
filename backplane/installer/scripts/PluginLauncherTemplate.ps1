# Backplane smart-launcher stub TEMPLATE.
#
# Each plugin repo generates its own copy of this file with $PluginName/
# $PluginRepo filled in. This is the ONE file a plugin distributes -- it is
# simultaneously the first-run installer and the permanent "Start <Plugin>"
# icon. Every run performs the same idempotent chain (see
# backplane.installer.bootstrap.launch_plugin): is Backplane's host already
# running? (ask it to show this plugin.) Is Backplane installed but not
# running? (launch it, then ask.) Is Backplane missing entirely? (bootstrap
# it.) Is this plugin not registered yet? (register it.) There is no
# separate one-time Setup.bat distinct from this ongoing run action.
#
# A plugin that supports multiple concurrent named instances (e.g. one
# whose data lives in a user-chosen folder) passes an extra instance-key
# argument through to bootstrap_standalone.py -- see that plugin's own
# migration notes; this generic template covers the single-instance case.

$PluginName = '__PLUGIN_NAME__'
$PluginRepo = '__PLUGIN_REPO__'

$ErrorActionPreference = 'Stop'
$ScriptDir = $PSScriptRoot

# -- Step 1: ensure Python is present -----------------------------------------
$LocalPythonCheck = Join-Path $ScriptDir 'PythonCheck.ps1'
if (Test-Path $LocalPythonCheck) {
    . $LocalPythonCheck
} else {
    # Not present locally (this stub running standalone, e.g. dropped into
    # a shared folder on its own) -- fetch it fresh. Real file, never
    # inline eval, same rule as everywhere else in this project.
    $tempScript = Join-Path $env:TEMP 'BackplanePythonCheck.ps1'
    Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/sunlitlabs/backplane/main/backplane/installer/scripts/PythonCheck.ps1' -OutFile $tempScript -UseBasicParsing
    . $tempScript
}

$showMessage = { param($msg) Write-Host $msg }
$python = Resolve-Python -ShowMessage $showMessage
if (-not $python) {
    Write-Host "Couldn't set up Python -- can't continue."
    exit 1
}
Resolve-Pip -PythonExe $python.PythonExe -ShowMessage $showMessage | Out-Null

# -- Step 2: hand off to the real bootstrap/launch logic ----------------------
$LocalBootstrap = Join-Path $ScriptDir 'bootstrap_standalone.py'
if (-not (Test-Path $LocalBootstrap)) {
    $LocalBootstrap = Join-Path $env:TEMP 'BackplaneBootstrap.py'
    Invoke-WebRequest -Uri 'https://raw.githubusercontent.com/sunlitlabs/backplane/main/backplane/installer/scripts/bootstrap_standalone.py' -OutFile $LocalBootstrap -UseBasicParsing
}

& $python.PythonExe -B $LocalBootstrap $PluginName $PluginRepo
exit $LASTEXITCODE

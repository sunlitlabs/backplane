# Shared Python/pip detection + bootstrap. Ported from py-sensor/l10-manager's
# lib/PythonCheck.ps1 (Find-Python/Test-RealPython/Test-Pip unchanged -- proven
# across two other repos) with Install-Python/Install-Pip added: Backplane
# auto-installs missing prerequisites rather than only guiding the user to do
# it manually, a deliberate choice for this repo specifically (see
# ARCHITECTURE.md). Dot-sourced by install.ps1 and the smart-launcher stub
# template -- keep this file UI-agnostic; callers supply their own
# presentation via scriptblocks passed to Resolve-Python.

function Test-RealPython {
    param(
        [Parameter(Mandatory)][string]$Command,
        [Parameter(Mandatory)][string[]]$Arguments
    )
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $Command
        $psi.Arguments = ($Arguments -join ' ')
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $proc = [System.Diagnostics.Process]::Start($psi)
        $out = $proc.StandardOutput.ReadToEnd()
        $err = $proc.StandardError.ReadToEnd()
        $proc.WaitForExit(5000) | Out-Null
        return "$out$err" -match 'Python 3\.\d+'
    } catch {
        return $false
    }
}

function Find-Python {
    <#
      Detects a real, working Python 3 install - deliberately avoiding the
      Microsoft Store "python.exe" stub, which exists on PATH by default on
      many Windows installs but just opens the Store when run.

      Returns @{ Launcher; PythonExe; PythonwExe } or $null if none found.
    #>

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py -and (Test-RealPython -Command $py.Source -Arguments @('-3', '--version'))) {
        $pythonExe = (& py -3 -c "import sys; print(sys.executable)" 2>$null)
        $pythonExe = if ($pythonExe) { $pythonExe.Trim() } else { $null }
        $pythonwExe = $null
        if ($pythonExe) {
            $candidate = Join-Path (Split-Path $pythonExe) 'pythonw.exe'
            if (Test-Path $candidate) { $pythonwExe = $candidate }
        }
        return @{ Launcher = 'py'; PythonExe = $pythonExe; PythonwExe = $pythonwExe }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python -and $python.Source -notmatch 'WindowsApps' -and (Test-RealPython -Command $python.Source -Arguments @('--version'))) {
        $pythonwExe = $null
        $candidate = Join-Path (Split-Path $python.Source) 'pythonw.exe'
        if (Test-Path $candidate) { $pythonwExe = $candidate }
        return @{ Launcher = 'python'; PythonExe = $python.Source; PythonwExe = $pythonwExe }
    }

    return $null
}

function Install-Python {
    <#
      Downloads the official python.org installer over HTTPS and runs it
      unattended, per-user (no admin/elevation required, matching this
      project's no-admin-rights rule): InstallAllUsers=0 PrependPath=1.
      Always a real downloaded .exe run via Start-Process -Wait, never
      iex/ScriptBlock::Create on any downloaded content.

      -ShowMessage: scriptblock(string) - tells the user what's about to
      happen before it happens; this is a real system change (installing
      Python), so it's always announced, never silent, even though it
      doesn't require interactive confirmation the way py-sensor's guided
      flow does.

      Returns $true if a working Python was found after the install.
    #>
    param(
        [Parameter(Mandatory)][scriptblock]$ShowMessage,
        [string]$Version = '3.12.7'
    )

    & $ShowMessage "Python wasn't found on this computer. Downloading and installing Python $Version (per-user, no admin rights needed)..."

    $arch = if ([Environment]::Is64BitOperatingSystem) { 'amd64' } else { 'win32' }
    $installerUrl = "https://www.python.org/ftp/python/$Version/python-$Version-$arch.exe"
    $installerPath = Join-Path $env:TEMP "python-$Version-$arch.exe"

    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing

    $installArgs = @('/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_launcher=1', 'Include_test=0')
    Start-Process -FilePath $installerPath -ArgumentList $installArgs -Wait
    Remove-Item $installerPath -ErrorAction SilentlyContinue

    # Installer updates PATH for future sessions, but not this already-running
    # process -- refresh it from the registry so Find-Python can see it now.
    $env:Path = [System.Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
                [System.Environment]::GetEnvironmentVariable('Path', 'User')

    return (Find-Python) -ne $null
}

function Resolve-Python {
    <#
      Ensures a real Python 3 install exists, installing it automatically
      (see Install-Python) rather than only guiding the user to do so
      manually.

      -ShowMessage: scriptblock(string) - display an informational message

      Returns the Find-Python hashtable, or $null if installation failed.
    #>
    param(
        [Parameter(Mandatory)][scriptblock]$ShowMessage
    )

    $found = Find-Python
    if ($found) { return $found }

    if (-not (Install-Python -ShowMessage $ShowMessage)) {
        & $ShowMessage "Automatic Python installation didn't succeed. Please install Python 3 from https://www.python.org/downloads/ and try again."
        return $null
    }

    return Find-Python
}

function Test-Pip {
    <#
      True if `<PythonExe> -m pip --version` runs successfully.
    #>
    param(
        [Parameter(Mandatory)][string]$PythonExe
    )
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $PythonExe
        $psi.Arguments = '-m pip --version'
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $proc = [System.Diagnostics.Process]::Start($psi)
        $out = $proc.StandardOutput.ReadToEnd()
        $err = $proc.StandardError.ReadToEnd()
        $proc.WaitForExit(5000) | Out-Null
        return "$out$err" -match 'pip \d+\.\d+'
    } catch {
        return $false
    }
}

function Resolve-Pip {
    <#
      Ensures pip is usable for the given Python, bootstrapping it via the
      stdlib `ensurepip` module (ships with every standard CPython install,
      no separate download needed) if Test-Pip fails.

      Returns $true if pip is usable after this call.
    #>
    param(
        [Parameter(Mandatory)][string]$PythonExe,
        [Parameter(Mandatory)][scriptblock]$ShowMessage
    )

    if (Test-Pip -PythonExe $PythonExe) { return $true }

    & $ShowMessage "pip wasn't found -- bootstrapping it now..."
    & $PythonExe -m ensurepip --upgrade | Out-Null

    return Test-Pip -PythonExe $PythonExe
}

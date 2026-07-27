# Shared "stop the running Backplane host" helper. Used by install.ps1
# (before replacing files out from under a live process) and uninstall.ps1
# (before deleting everything). Adapted from py-sensor/lib/
# StopRunningInstance.ps1 -- same poll-for-exit reasoning: Stop-Process
# returns once termination is *requested*, but Windows can take a moment
# longer to actually release file/DLL handles, which showed up for real as a
# flaky reinstall in that repo with only a fixed sleep.

function Stop-BackplaneHost {
    <#
      Finds any python.exe/pythonw.exe running backplane.host.process and
      force-stops it, then waits for the OS to actually finish tearing the
      process down. Returns $true if it found (and stopped) a running host,
      $false if there was nothing to stop.
    #>
    param()

    $runningInstance = Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
        Where-Object { $_.CommandLine -like '*backplane.host.process*' }
    if (-not $runningInstance) { return $false }

    $stoppedIds = $runningInstance | ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        $_.ProcessId
    }
    $deadline = (Get-Date).AddSeconds(5)
    while ((Get-Date) -lt $deadline) {
        $stillRunning = $stoppedIds | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }
        if (-not $stillRunning) { break }
        Start-Sleep -Milliseconds 200
    }
    Start-Sleep -Milliseconds 500
    return $true
}

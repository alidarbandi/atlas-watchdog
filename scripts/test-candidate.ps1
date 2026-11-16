# PowerShell 5.1. Run only against the candidate bundle and disposable demo state.
param(
    [Parameter(Mandatory=$true)][string]$Executable,
    [string]$OutputDirectory = (Join-Path $env:TEMP ('Watchdog acceptance ' + [guid]::NewGuid().ToString('N')))
)
$ErrorActionPreference = 'Stop'
$candidate = (Resolve-Path -LiteralPath $Executable).Path
$output = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path -LiteralPath $output) { throw 'Choose a new output directory; existing state will not be reused.' }
New-Item -ItemType Directory -Path $output | Out-Null
$state = Join-Path $output 'demo state'
$stdout = Join-Path $output 'console.txt'
$stderr = Join-Path $output 'errors.txt'
$started = Get-Date
$previousLocal = $env:LOCALAPPDATA
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
try {
    $env:LOCALAPPDATA = Join-Path $output 'LocalAppData'
    $env:TEMP = Join-Path $output 'temporary extraction'
    $env:TMP = $env:TEMP
    New-Item -ItemType Directory -Path $env:TEMP | Out-Null
    $process = Start-Process -FilePath $candidate -ArgumentList @('--demo','--smoke-test','--state-dir',('"' + $state + '"')) -WindowStyle Hidden -PassThru -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    if (-not $process.WaitForExit(60000)) { $process.Kill(); throw 'Smoke test exceeded 60 seconds.' }
    $process.Refresh()
}
finally {
    $env:LOCALAPPDATA = $previousLocal
    $env:TEMP = $previousTemp
    $env:TMP = $previousTmp
}
$record = [PSCustomObject]@{
    Started = $started.ToUniversalTime().ToString('o')
    Finished = (Get-Date).ToUniversalTime().ToString('o')
    ExecutableSHA256 = (Get-FileHash -LiteralPath $candidate -Algorithm SHA256).Hash
    ExitCode = $process.ExitCode
    DatabaseCreated = (Test-Path -LiteralPath (Join-Path $state 'history.sqlite3'))
    DiagnosticCreated = (Test-Path -LiteralPath (Join-Path $state 'diagnostics.log'))
    OutputDirectory = $output
    Note = 'Exit 0 includes worker/demo event/live-source checks; inspect GUI and follow legacy-acceptance.md as well.'
}
$record | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $output 'result.json') -Encoding UTF8
$record | Format-List
if ($process.ExitCode -ne 0 -or -not $record.DatabaseCreated -or -not $record.DiagnosticCreated) { exit 1 }

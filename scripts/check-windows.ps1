# PowerShell 5.1 read-only diagnostics. No secrets, machine name or source logs.
param(
    [ValidateSet('modern', 'legacy')][string]$Profile = 'modern',
    [string]$Executable
)
$ErrorActionPreference = 'Stop'
$atlasOs = Get-CimInstance -ClassName Win32_OperatingSystem
$atlasProcessor = Get-CimInstance -ClassName Win32_Processor | Select-Object -First 1
$atlasBuild = [int]$atlasOs.BuildNumber
$atlasRevision = (Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion' -Name UBR -ErrorAction SilentlyContinue).UBR
$atlasMinimum = if ($Profile -eq 'legacy') { 14393 } else { 17763 }
$atlasSupported = $atlasBuild -ge $atlasMinimum -and $atlasProcessor.Architecture -eq 9 -and [Environment]::Is64BitOperatingSystem
$atlasHash = if ($Executable) { (Get-FileHash -LiteralPath $Executable -Algorithm SHA256).Hash } else { 'No executable supplied' }
[PSCustomObject]@{
    OperatingSystem = $atlasOs.Caption
    Version = $atlasOs.Version
    BuildRevision = "$atlasBuild.$atlasRevision"
    OSArchitecture = $atlasOs.OSArchitecture
    ProcessorArchitectureCode = $atlasProcessor.Architecture
    PowerShellProcessBits = [IntPtr]::Size * 8
    SelectedProfile = $Profile
    RequiredBuild = $atlasMinimum
    MeetsSelectedOSBaseline = $atlasSupported
    ExactReportedTargetBuild = ($atlasBuild -eq 14393 -and $atlasRevision -eq 3884)
    TargetOSValidation = 'PENDING; meeting the baseline is not an application test'
    ExecutableSHA256 = $atlasHash
    StartupDiagnostic = (Join-Path $env:LOCALAPPDATA 'ATLASWatchdog\startup.json')
} | Format-List
if (-not $atlasSupported) { exit 1 }

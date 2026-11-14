# Read-only OS preflight; no administrator access or system changes.
$ErrorActionPreference = 'Stop'
$atlasOs = Get-CimInstance -ClassName Win32_OperatingSystem
$atlasBuild = [int]$atlasOs.BuildNumber
$atlasArchitecture = $atlasOs.OSArchitecture
$atlasSupported = $atlasBuild -ge 17763 -and $atlasArchitecture -match '64' -and $env:PROCESSOR_ARCHITECTURE -notmatch 'ARM'
[PSCustomObject]@{
    OperatingSystem = $atlasOs.Caption
    Version = $atlasOs.Version
    Build = $atlasBuild
    Architecture = $atlasArchitecture
    MeetsSelectedOSBaseline = $atlasSupported
    RequiredBaseline = 'Windows 10 version 1809 / build 17763 or newer, x64'
} | Format-List
if (-not $atlasSupported) {
    Write-Output 'This build is not supported on the detected OS/architecture. See docs\compatibility.md.'
    exit 1
}
Write-Output 'OS baseline met. Complete docs\acceptance.md before unattended use.'

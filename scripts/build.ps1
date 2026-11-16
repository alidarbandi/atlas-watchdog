param(
    [ValidateSet('modern', 'legacy')]
    [string]$Profile = 'modern',
    [ValidateSet('Both', 'OneFolder', 'OneFile')]
    [string]$Format = 'Both',
    [switch]$SkipTests
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$environmentFolder = if ($Profile -eq 'legacy') { '.venv-legacy' } else { '.venv' }
$pythonExe = Join-Path $projectRoot "$environmentFolder\Scripts\python.exe"
$releaseDir = Join-Path $projectRoot "dist\v0.1.7\$Profile"
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Create the profile environment and install its lock first; see docs\legacy-build.md.'
}
$previousProfile = $env:ATLAS_WATCHDOG_PROFILE
$env:ATLAS_WATCHDOG_PROFILE = $Profile
Push-Location -LiteralPath $projectRoot
try {
    & $pythonExe scripts\validate_build.py
    if ($LASTEXITCODE -ne 0) { throw 'Build platform validation failed.' }
    if (-not $SkipTests) {
        & $pythonExe -m pytest -q
        if ($LASTEXITCODE -ne 0) { throw 'Tests failed; no build was produced.' }
    }
    if ($Format -in @('Both', 'OneFolder')) {
        & $pythonExe -m PyInstaller packaging\onedir.spec --noconfirm --clean --distpath $releaseDir --workpath "build\$Profile\onedir"
        if ($LASTEXITCODE -ne 0) { throw 'One-folder build failed.' }
    }
    if ($Format -in @('Both', 'OneFile')) {
        & $pythonExe -m PyInstaller packaging\onefile.spec --noconfirm --clean --distpath $releaseDir --workpath "build\$Profile\onefile"
        if ($LASTEXITCODE -ne 0) { throw 'One-file build failed.' }
    }
    & $pythonExe scripts\prepare_release.py --output $releaseDir --profile $Profile
    if ($LASTEXITCODE -ne 0) { throw 'Release preparation failed.' }
    Write-Output "Build complete: $releaseDir. Legacy target-OS validation remains PENDING until separately performed."
}
finally {
    Pop-Location
    $env:ATLAS_WATCHDOG_PROFILE = $previousProfile
}

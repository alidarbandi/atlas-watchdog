param(
    [ValidateSet('Both', 'OneFolder', 'OneFile')]
    [string]$Format = 'Both',
    [switch]$SkipTests
)
$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw 'Create .venv and install requirements-lock.txt first; see README.md.'
}
Push-Location -LiteralPath $projectRoot
try {
    & $pythonExe -c "import platform,sys; assert sys.platform == 'win32', 'Build Windows binaries on Windows'; assert sys.version_info[:2] == (3,12), 'Use CPython 3.12'; assert platform.architecture()[0] == '64bit', 'Use x64 Python'"
    if ($LASTEXITCODE -ne 0) { throw 'Build platform validation failed.' }
    if (-not $SkipTests) {
        & $pythonExe -m pytest -q
        if ($LASTEXITCODE -ne 0) { throw 'Tests failed; no build was produced.' }
    }
    if ($Format -in @('Both', 'OneFolder')) {
        & $pythonExe -m PyInstaller packaging\onedir.spec --noconfirm --clean
        if ($LASTEXITCODE -ne 0) { throw 'One-folder build failed.' }
    }
    if ($Format -in @('Both', 'OneFile')) {
        & $pythonExe -m PyInstaller packaging\onefile.spec --noconfirm --clean
        if ($LASTEXITCODE -ne 0) { throw 'One-file build failed.' }
    }
    & $pythonExe scripts\prepare_release.py
    if ($LASTEXITCODE -ne 0) { throw 'Release preparation failed.' }
    Write-Output 'Build complete. Artifacts are under dist\. Follow docs\acceptance.md before unattended use.'
}
finally {
    Pop-Location
}

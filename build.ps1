# Build a portable Windows folder with PyInstaller.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    throw "Run run.bat once first, or create .venv and install requirements.txt."
}

& ".venv\Scripts\python.exe" -m pip install "pyinstaller>=6.0"
& ".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean "PitchLens.spec"

Write-Host ""
Write-Host "Build finished: $PSScriptRoot\dist\PitchLens\PitchLens.exe"

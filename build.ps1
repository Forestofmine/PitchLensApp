# Build a portable Windows folder with PyInstaller.
$ErrorActionPreference = "Stop"
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$output = Join-Path $PSScriptRoot 'dist\PitchLens\PitchLens.exe'

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Run run.bat once first, or create .venv and install requirements.txt."
}

Push-Location -LiteralPath $PSScriptRoot
try {
    & $python -m pip install 'pyinstaller>=6.0'
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller installation failed with exit code $LASTEXITCODE."
    }

    $startedAt = [DateTime]::UtcNow
    & $python -m PyInstaller --noconfirm --clean 'PitchLens.spec'
    if ($LASTEXITCODE -ne 0) {
        throw "PitchLens build failed with exit code $LASTEXITCODE."
    }

    $artifact = Get-Item -LiteralPath $output -ErrorAction SilentlyContinue
    if ($null -eq $artifact -or $artifact.PSIsContainer -or $artifact.LastWriteTimeUtc -lt $startedAt) {
        throw "The build did not produce a fresh executable at $output."
    }
    Write-Host "Build finished: $output"
}
finally {
    Pop-Location
}

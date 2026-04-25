param(
    [string]$OutputDir = "dist\leam_openclaw_handoff"
)

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host "Cleaning previous build artifacts..."
Remove-Item -Recurse -Force "build", "dist\*.whl", $OutputDir -ErrorAction SilentlyContinue

Write-Host "Building LEAM wheel..."
python -m pip install --upgrade build
python -m build --wheel

$Wheel = Get-ChildItem -Path "dist" -Filter "leam-*.whl" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $Wheel) {
    throw "Wheel build failed: no leam-*.whl found in dist."
}

Write-Host "Creating OpenClaw handoff package..."
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutputDir "docs") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $OutputDir "examples") | Out-Null

Copy-Item $Wheel.FullName -Destination $OutputDir
Copy-Item "README.md", "config.example.json", "requirements.txt", "pyproject.toml" -Destination $OutputDir
Copy-Item "docs\OPENCLAW_INTEGRATION.md" -Destination (Join-Path $OutputDir "docs")

if (Test-Path "docs\PARAMETER_UPDATE_API.md") {
    Copy-Item "docs\PARAMETER_UPDATE_API.md" -Destination (Join-Path $OutputDir "docs")
}

if (Test-Path "examples\quickstart.py") {
    Copy-Item "examples\quickstart.py" -Destination (Join-Path $OutputDir "examples")
}

$ArchivePath = "$OutputDir.zip"
Remove-Item -Force $ArchivePath -ErrorAction SilentlyContinue
Compress-Archive -Path (Join-Path $OutputDir "*") -DestinationPath $ArchivePath

Write-Host ""
Write-Host "Done."
Write-Host "Handoff directory: $OutputDir"
Write-Host "Handoff archive:   $ArchivePath"
Write-Host ""
Write-Host "Do not include local config.json or virtual environments in the handoff package."

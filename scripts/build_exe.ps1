param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if ($Clean) {
    Remove-Item -Path "build", "dist" -Recurse -Force -ErrorAction SilentlyContinue
}

python -m PyInstaller --clean --noconfirm cfi_edi_processor.spec

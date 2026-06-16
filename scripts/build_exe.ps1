param(
    [switch]$Clean
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if ($Clean) {
    Remove-Item -Path "build", "dist" -Recurse -Force -ErrorAction SilentlyContinue
}

$dependencyCheck = python -c "import importlib.util; missing=[name for name in ('jinja2','pyodbc') if importlib.util.find_spec(name) is None]; print(','.join(missing)); raise SystemExit(1 if missing else 0)"
if ($LASTEXITCODE -ne 0) {
    throw "Build dependencies are missing from this Python environment: $dependencyCheck. Install them with: python -m pip install .[build]"
}

python -m PyInstaller --clean --noconfirm cfi_edi_processor.spec

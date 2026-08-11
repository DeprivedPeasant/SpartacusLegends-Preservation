$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BuildRoot = Join-Path $ProjectRoot '.build'
$VenvRoot = Join-Path $BuildRoot 'venv'
$VenvPython = Join-Path $VenvRoot 'Scripts\python.exe'
$DistRoot = Join-Path $ProjectRoot 'dist'
$PackageRoot = Join-Path $DistRoot 'SpartacusLegends-Preservation-v0.3.2'

New-Item -ItemType Directory -Force -Path $BuildRoot,$DistRoot,$PackageRoot | Out-Null

if (-not (Test-Path -LiteralPath $VenvPython)) {
    python -m venv $VenvRoot
}

& $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements-build.txt')
& $VenvPython -m PyInstaller `
    --clean `
    --noconfirm `
    --onefile `
    --console `
    --name SpartacusLegendsServer `
    --paths (Join-Path $ProjectRoot 'tools') `
    --hidden-import prudp_server `
    --hidden-import roster_bridge `
    --hidden-import UbiOnlineConfigService.spartacus_onlineconfig `
    --distpath $DistRoot `
    --workpath (Join-Path $BuildRoot 'pyinstaller-work') `
    --specpath $BuildRoot `
    (Join-Path $ProjectRoot 'tools\spartacus_server.py')

Copy-Item -Force -LiteralPath (Join-Path $DistRoot 'SpartacusLegendsServer.exe') -Destination $PackageRoot
Copy-Item -Force -LiteralPath (Join-Path $PSScriptRoot 'SpartacusLegends_ServerPatch.yml') -Destination $PackageRoot
Copy-Item -Force -LiteralPath (Join-Path $ProjectRoot 'README.md') -Destination $PackageRoot

$ZipPath = Join-Path $DistRoot 'SpartacusLegends-Preservation-v0.3.2.zip'
Compress-Archive -Force -Path (Join-Path $PackageRoot '*') -DestinationPath $ZipPath
Write-Host "Release created: $ZipPath"

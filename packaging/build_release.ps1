$ErrorActionPreference = 'Stop'

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BuildRoot = Join-Path $ProjectRoot '.build'
$VenvRoot = Join-Path $BuildRoot 'venv'
$VenvPython = Join-Path $VenvRoot 'Scripts\python.exe'
$DistRoot = Join-Path $ProjectRoot 'dist'

# Single source of truth: the version lives only in tools/_version.py.
$VersionFile = Join-Path $ProjectRoot 'tools\_version.py'
$VersionMatch = Select-String -Path $VersionFile -Pattern '__version__\s*=\s*"([^"]+)"'
if (-not $VersionMatch) {
    throw "Could not read __version__ from $VersionFile"
}
$Version = $VersionMatch.Matches[0].Groups[1].Value

$PackageRoot = Join-Path $BuildRoot "SpartacusLegends-Preservation-v$Version"

New-Item -ItemType Directory -Force -Path $BuildRoot,$DistRoot,$PackageRoot | Out-Null

if (-not (Test-Path -LiteralPath $VenvPython)) {
    python -m venv $VenvRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create the build virtual environment (exit $LASTEXITCODE)."
    }
}

& $VenvPython -m pip install --disable-pip-version-check -r (Join-Path $PSScriptRoot 'requirements-build.txt')
if ($LASTEXITCODE -ne 0) {
    throw "Failed to install build requirements (exit $LASTEXITCODE)."
}

& $VenvPython -m PyInstaller `
    --clean `
    --noconfirm `
    --onefile `
    --console `
    --name SpartacusLegendsServer `
    --paths (Join-Path $ProjectRoot 'tools') `
    --hidden-import _version `
    --hidden-import prudp_server `
    --hidden-import roster_bridge `
    --hidden-import legend_recovery `
    --hidden-import migration_coordinator `
    --hidden-import title_save_migration `
    --hidden-import UbiOnlineConfigService.spartacus_onlineconfig `
    --distpath $DistRoot `
    --workpath (Join-Path $BuildRoot 'pyinstaller-work') `
    --specpath $BuildRoot `
    (Join-Path $ProjectRoot 'tools\spartacus_server.py')
if ($LASTEXITCODE -ne 0) {
    throw "Failed to build SpartacusLegendsServer.exe (exit $LASTEXITCODE)."
}

& $VenvPython -m PyInstaller `
    --clean `
    --noconfirm `
    --onefile `
    --console `
    --name SpartacusLegendsPatchInstaller `
    --add-data "$(Join-Path $PSScriptRoot 'SpartacusLegends_ServerPatch.yml');." `
    --add-data "$(Join-Path $ProjectRoot 'tools\patch_signatures.json');." `
    --paths (Join-Path $ProjectRoot 'tools') `
    --hidden-import game_detect `
    --distpath $DistRoot `
    --workpath (Join-Path $BuildRoot 'pyinstaller-work') `
    --specpath $BuildRoot `
    (Join-Path $ProjectRoot 'tools\patch_installer.py')
if ($LASTEXITCODE -ne 0) {
    throw "Failed to build SpartacusLegendsPatchInstaller.exe (exit $LASTEXITCODE)."
}

& $VenvPython -m PyInstaller `
    --clean `
    --noconfirm `
    --onedir `
    --contents-directory SpartacusLegendsServerGUI_runtime `
    --windowed `
    --name SpartacusLegendsServerGUI `
    --paths (Join-Path $ProjectRoot 'tools') `
    --add-data "$(Join-Path $PSScriptRoot 'SpartacusLegends_ServerPatch.yml');." `
    --add-data "$(Join-Path $ProjectRoot 'tools\patch_signatures.json');." `
    --hidden-import _version `
    --hidden-import prudp_server `
    --hidden-import roster_bridge `
    --hidden-import legend_recovery `
    --hidden-import migration_coordinator `
    --hidden-import title_save_migration `
    --hidden-import server_config `
    --hidden-import server_control `
    --hidden-import user_events `
    --hidden-import port_diagnostics `
    --hidden-import save_editor `
    --hidden-import patch_installer `
    --hidden-import game_detect `
    --hidden-import UbiOnlineConfigService.spartacus_onlineconfig `
    --distpath $DistRoot `
    --workpath (Join-Path $BuildRoot 'pyinstaller-work') `
    --specpath $BuildRoot `
    (Join-Path $ProjectRoot 'tools\spartacus_gui.py')
if ($LASTEXITCODE -ne 0) {
    throw "Failed to build SpartacusLegendsServerGUI.exe (exit $LASTEXITCODE)."
}

Copy-Item -Force -LiteralPath (Join-Path $DistRoot 'SpartacusLegendsServer.exe') -Destination $PackageRoot
Copy-Item -Force -LiteralPath (Join-Path $DistRoot 'SpartacusLegendsPatchInstaller.exe') -Destination $PackageRoot
# The GUI is a one-folder build: nothing is unpacked to %TEMP% at launch
# (a one-file Qt app failed there with "Could not create temporary
# directory"), and it starts faster. Its runtime folder must stay beside it.
$GuiBuild = Join-Path $DistRoot 'SpartacusLegendsServerGUI'
$GuiRuntime = Join-Path $PackageRoot 'SpartacusLegendsServerGUI_runtime'
if (Test-Path -LiteralPath $GuiRuntime) {
    Remove-Item -Recurse -Force -LiteralPath $GuiRuntime
}
Copy-Item -Force -LiteralPath (Join-Path $GuiBuild 'SpartacusLegendsServerGUI.exe') -Destination $PackageRoot
Copy-Item -Recurse -Force -LiteralPath (Join-Path $GuiBuild 'SpartacusLegendsServerGUI_runtime') -Destination $PackageRoot
Copy-Item -Force -LiteralPath (Join-Path $PSScriptRoot 'SpartacusLegends_ServerPatch.yml') -Destination $PackageRoot
Copy-Item -Force -LiteralPath (Join-Path $ProjectRoot 'README.md') -Destination $PackageRoot
Copy-Item -Force -LiteralPath (Join-Path $ProjectRoot 'MIGRATION_GUIDE.md') -Destination $PackageRoot

$ZipPath = Join-Path $DistRoot "SpartacusLegends-Preservation-v$Version.zip"
# Zip an explicit list. The package folder is also a convenient place to run
# a test build, which leaves player saves (data\), logs\ and GUI settings in
# it; a wildcard would ship those inside the release.
$ReleaseItems = @(
    'SpartacusLegendsServer.exe',
    'SpartacusLegendsPatchInstaller.exe',
    'SpartacusLegendsServerGUI.exe',
    'SpartacusLegendsServerGUI_runtime',
    'SpartacusLegends_ServerPatch.yml',
    'README.md',
    'MIGRATION_GUIDE.md'
) | ForEach-Object { Join-Path $PackageRoot $_ }
foreach ($Item in $ReleaseItems) {
    if (-not (Test-Path -LiteralPath $Item)) {
        throw "Release item is missing: $Item"
    }
}
Compress-Archive -Force -Path $ReleaseItems -DestinationPath $ZipPath

Add-Type -AssemblyName System.IO.Compression.FileSystem
$Archive = [System.IO.Compression.ZipFile]::OpenRead($ZipPath)
try {
    $Leaked = $Archive.Entries | Where-Object {
        $_.FullName -match '^(data|logs|backups)[\\/]' -or
        $_.FullName -match '(^|[\\/])gui-settings\.ini$' -or
        $_.FullName -match '(^|[\\/])server-config\.json'
    } | ForEach-Object { $_.FullName }
} finally {
    $Archive.Dispose()
}
if ($Leaked) {
    Remove-Item -Force -LiteralPath $ZipPath
    throw "Refusing to ship player or local files in the release: $($Leaked -join ', ')"
}
Write-Host "Release created: $ZipPath"

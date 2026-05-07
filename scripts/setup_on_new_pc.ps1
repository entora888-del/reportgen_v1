param(
    [switch]$RestoreAppDataTemplate = $true,
    [switch]$RunTests,
    [switch]$CompareSamples,
    [switch]$SmokeGui,
    [switch]$RunGui
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
Set-Location $repoRoot

$buildScript = Join-Path $repoRoot "scripts\build_win.ps1"
$bundledTemplate = Join-Path $repoRoot "migration_assets\appdata\ReportGen\templates\報告書_ひな形_v2.docx"

function Restore-BundledAppDataTemplate {
    if (-not $env:APPDATA) {
        Write-Warning "APPDATA is not available. Skipping AppData template restore."
        return
    }
    if (-not (Test-Path $bundledTemplate)) {
        Write-Host "Bundled AppData template was not found. Skipping restore."
        return
    }

    $targetDir = Join-Path $env:APPDATA "ReportGen\templates"
    $targetPath = Join-Path $targetDir "報告書_ひな形_v2.docx"
    New-Item -ItemType Directory -Force -Path $targetDir | Out-Null
    Copy-Item -Force -LiteralPath $bundledTemplate -Destination $targetPath
    Write-Host "Restored AppData template to: $targetPath"
}

if ($RestoreAppDataTemplate) {
    Restore-BundledAppDataTemplate
}

& powershell -ExecutionPolicy Bypass -File $buildScript -RecreateVenv -InstallDeps

if ($RunTests) {
    & powershell -ExecutionPolicy Bypass -File $buildScript -RunTests
}

if ($CompareSamples) {
    & powershell -ExecutionPolicy Bypass -File $buildScript -CompareSamples
}

if ($SmokeGui) {
    & powershell -ExecutionPolicy Bypass -File $buildScript -SmokeGui
}

if ($RunGui) {
    & powershell -ExecutionPolicy Bypass -File $buildScript -RunGui
}

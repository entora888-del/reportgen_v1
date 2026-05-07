param(
    [switch]$RecreateVenv,
    [switch]$InstallDeps,
    [switch]$RunGui,
    [switch]$SmokeGui,
    [switch]$RunTests,
    [switch]$CompareSamples,
    [string]$SampleXml,
    [string]$SampleOut = "output\sample_report.docx",
    [string]$SampleLiqPdf
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
Set-Location $repoRoot

$venvDir = Join-Path $repoRoot ".venv"
$pythonExe = Join-Path $venvDir "Scripts\python.exe"

function Require-WindowsPython {
    $pyCmd = Get-Command py -ErrorAction SilentlyContinue
    if (-not $pyCmd) {
        throw "Windows Python launcher 'py' was not found. Install Python 3.10+ first."
    }
}

function New-ProjectVenv {
    Require-WindowsPython

    if (Test-Path $venvDir) {
        $hasWindowsVenv = Test-Path $pythonExe
        $hasWslVenv = Test-Path (Join-Path $venvDir "bin\python")

        if ($hasWindowsVenv -and -not $RecreateVenv) {
            return
        }

        if ($hasWslVenv -and -not $RecreateVenv) {
            throw ".venv looks like a WSL/Linux virtualenv. Re-run with '-RecreateVenv' to rebuild it for Windows."
        }

        Remove-Item -Recurse -Force $venvDir
    }

    & py -3 -m venv .venv
}

function Install-ProjectDeps {
    & $pythonExe -m pip install -U pip
    & $pythonExe -m pip install -e .
}

function Ensure-ProjectDeps {
    try {
        & $pythonExe -c "import reportgen" *> $null
    } catch {
    }
    if ($LASTEXITCODE -ne 0) {
        Install-ProjectDeps
    }
}

function Ensure-Pytest {
    try {
        & $pythonExe -c "import pytest" *> $null
    } catch {
    }
    if ($LASTEXITCODE -ne 0) {
        & $pythonExe -m pip install pytest
    }
}

New-ProjectVenv

if ($InstallDeps -or $RecreateVenv) {
    Install-ProjectDeps
}

if ($RunTests) {
    Ensure-ProjectDeps
    Ensure-Pytest
    & $pythonExe -m pytest
}

if ($RunGui) {
    Ensure-ProjectDeps
    & $pythonExe -m reportgen.gui.app
}

if ($SmokeGui) {
    Ensure-ProjectDeps
    & $pythonExe .\scripts\smoke_gui.py
}

if ($CompareSamples) {
    Ensure-ProjectDeps
    & $pythonExe .\scripts\verify_samples.py --samples-root .\data\samples --out-dir .\tmp\compare_results
}

if ($SampleXml) {
    Ensure-ProjectDeps
    $args = @(
        ".\scripts\generate_report.py",
        "--xml", $SampleXml,
        "--out", $SampleOut
    )
    if ($SampleLiqPdf) {
        $args += @("--liq-pdf", $SampleLiqPdf)
    }
    & $pythonExe @args
}

param(
    [string]$OutDir = "output\transfer",
    [switch]$IncludeOutput,
    [switch]$SkipGit,
    [switch]$SkipAppDataTemplate
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = Split-Path -Parent $scriptDir
$repoRootFull = [System.IO.Path]::GetFullPath($repoRoot).TrimEnd("\")
$repoName = Split-Path -Leaf $repoRootFull

function Resolve-FullPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$PathValue
    )

    if ([System.IO.Path]::IsPathRooted($PathValue)) {
        return [System.IO.Path]::GetFullPath($PathValue).TrimEnd("\")
    }
    return [System.IO.Path]::GetFullPath((Join-Path $repoRootFull $PathValue)).TrimEnd("\")
}

function Test-IsUnderPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Candidate,
        [Parameter(Mandatory = $true)]
        [string]$Root
    )

    $candidateFull = [System.IO.Path]::GetFullPath($Candidate).TrimEnd("\")
    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd("\")
    if ($candidateFull.Length -lt $rootFull.Length) {
        return $false
    }
    if ($candidateFull.Equals($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    return $candidateFull.StartsWith($rootFull + "\", [System.StringComparison]::OrdinalIgnoreCase)
}

function Get-RelativeEntryName {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FullPath
    )

    $relative = $FullPath.Substring($repoRootFull.Length).TrimStart("\")
    return ($repoName + "/" + $relative.Replace("\", "/"))
}

$outDirFull = Resolve-FullPath -PathValue $OutDir
New-Item -ItemType Directory -Force -Path $outDirFull | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$zipPath = Join-Path $outDirFull "${repoName}_pc_move_${timestamp}.zip"
if (Test-Path $zipPath) {
    Remove-Item -Force $zipPath
}

$excludedDirNames = @(
    ".venv",
    ".codex",
    ".pytest_cache",
    "__pycache__",
    "build",
    "dist",
    "tmp",
    ".mypy_cache",
    ".ruff_cache"
)
if (-not $IncludeOutput) {
    $excludedDirNames += "output"
}
if ($SkipGit) {
    $excludedDirNames += ".git"
}

$excludedFileNames = @(
    "Thumbs.db"
)

$appDataTemplate = $null
if (-not $SkipAppDataTemplate -and $env:APPDATA) {
    $candidate = Join-Path $env:APPDATA "ReportGen\templates\報告書_ひな形_v2.docx"
    if (Test-Path $candidate) {
        $appDataTemplate = [System.IO.Path]::GetFullPath($candidate)
    }
}

$repoFiles = Get-ChildItem -LiteralPath $repoRootFull -Recurse -Force -File | Where-Object {
    $full = [System.IO.Path]::GetFullPath($_.FullName)
    if ($full.Equals($zipPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $false
    }
    if (Test-IsUnderPath -Candidate $full -Root $outDirFull) {
        return $false
    }
    if ($excludedFileNames -contains $_.Name) {
        return $false
    }

    $relative = $full.Substring($repoRootFull.Length).TrimStart("\")
    foreach ($segment in ($relative -split "[\\/]")) {
        if ($excludedDirNames -contains $segment) {
            return $false
        }
    }
    return $true
}

$zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($file in $repoFiles) {
        $entryName = Get-RelativeEntryName -FullPath ([System.IO.Path]::GetFullPath($file.FullName))
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zip,
            $file.FullName,
            $entryName,
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }

    if ($appDataTemplate) {
        $templateEntry = "migration_assets/appdata/ReportGen/templates/報告書_ひな形_v2.docx"
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $zip,
            $appDataTemplate,
            $templateEntry,
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }

    $note = @"
reportgen_v1: move to another PC
Created: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz")

This archive contains:
- the current working tree$(if ($SkipGit) { "" } else { " and .git metadata" })
- data/ and booklets/ if they exist in the repo
- the AppData template if present$(if ($appDataTemplate) { "" } else { " (not found on this PC)" })

This archive excludes:
- .venv
- caches and temp folders
- build/ dist/
$(if ($IncludeOutput) { "" } else { "- output/" })

Recommended steps on the destination PC:
1. Extract the archive to a normal Windows folder.
2. If migration_assets/appdata/ReportGen/templates/ exists, copy it to:
   %APPDATA%\ReportGen\templates\
3. Open PowerShell in the extracted repo root and run:
   powershell -ExecutionPolicy Bypass -Command "& '.\scripts\build_win.ps1' -RecreateVenv -InstallDeps"
4. Verify the setup:
   powershell -ExecutionPolicy Bypass -Command "& '.\scripts\build_win.ps1' -RunTests"
   powershell -ExecutionPolicy Bypass -Command "& '.\scripts\build_win.ps1' -CompareSamples"
   powershell -ExecutionPolicy Bypass -Command "& '.\scripts\build_win.ps1' -SmokeGui"
   powershell -ExecutionPolicy Bypass -Command "& '.\scripts\build_win.ps1' -RunGui"
5. Re-set any needed environment variables such as:
   OPENAI_API_KEY
   REPORTGEN_TEMPLATE_PATH
   REPORTGEN_OUT_DIR
   REPORTGEN_BOOKLET_INDEX
   REPORTGEN_BOOKLET_OUTDIR
   REPORTGEN_BOOKLET_CANDIDATES
   REPORTGEN_BOOKLET_BUFFER
   REPORTGEN_BOOKLET_CODE_FIELD
   REPORTGEN_BOOKLET_NAME_FIELD
   REPORTGEN_AI_MODEL
"@

    $noteEntry = $zip.CreateEntry("migration_assets/MIGRATE_TO_NEW_PC.txt")
    $writer = [System.IO.StreamWriter]::new($noteEntry.Open(), [System.Text.UTF8Encoding]::new($false))
    try {
        $writer.Write($note)
    } finally {
        $writer.Dispose()
    }

    $manifest = [ordered]@{
        created_at = (Get-Date).ToString("o")
        repo_name = $repoName
        repo_root = $repoRootFull
        archive_path = $zipPath
        include_git = (-not $SkipGit)
        include_output = [bool]$IncludeOutput
        include_appdata_template = [bool]$appDataTemplate
        excluded_dir_names = $excludedDirNames
        file_count = @($repoFiles).Count
    } | ConvertTo-Json -Depth 4

    $manifestEntry = $zip.CreateEntry("migration_assets/manifest.json")
    $manifestWriter = [System.IO.StreamWriter]::new($manifestEntry.Open(), [System.Text.UTF8Encoding]::new($false))
    try {
        $manifestWriter.Write($manifest)
    } finally {
        $manifestWriter.Dispose()
    }
} finally {
    $zip.Dispose()
}

$archiveSizeMb = [Math]::Round(((Get-Item $zipPath).Length / 1MB), 2)
Write-Host "Archive created: $zipPath"
Write-Host "Included repo files: $(@($repoFiles).Count)"
Write-Host "Archive size (MB): $archiveSizeMb"
if ($appDataTemplate) {
    Write-Host "Included AppData template: $appDataTemplate"
} else {
    Write-Host "AppData template was not included."
}

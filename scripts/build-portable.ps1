param(
    [string]$Source = (Join-Path (Split-Path -Parent $PSScriptRoot) 'upstream'),
    [switch]$SkipBuild
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$version = '0.2.0'
$Source = (Resolve-Path -LiteralPath $Source).Path

if (-not $SkipBuild) {
    & pnpm --dir (Join-Path $Source 'apps/desktop-tauri') exec tauri build --no-bundle
    if ($LASTEXITCODE -ne 0) { throw "Tauri build failed: $LASTEXITCODE" }
}

$outputRoot = Join-Path $projectRoot 'artifacts'
$packageName = "codex-barbar-plus_${version}_x64-portable"
$stage = Join-Path $outputRoot $packageName
# Refuse to mix a previous package or user data into a new portable archive.
if (Test-Path -LiteralPath $stage) { throw "Package directory already exists: $stage" }
New-Item -ItemType Directory -Path $stage | Out-Null
foreach ($name in @('codex-barbar.exe', 'WebView2Loader.dll')) {
    Copy-Item -LiteralPath (Join-Path $Source "target/release/$name") -Destination $stage
}
foreach ($name in @('LICENSE', 'UPSTREAMS.md', 'README.md', 'README.zh-CN.md', 'PORTABLE.md')) {
    Copy-Item -LiteralPath (Join-Path $Source $name) -Destination $stage
}
Copy-Item -LiteralPath (Join-Path $projectRoot 'README-PLUS.md') -Destination $stage
$docs = Join-Path $stage 'docs'
New-Item -ItemType Directory -Path $docs | Out-Null
foreach ($name in @('audit-fixes-20260912.md', 'memory-fixes-20260917.md', 'fix-maximized-taskbar-v0.2.0.md')) {
    Copy-Item -LiteralPath (Join-Path $projectRoot "docs/$name") -Destination $docs
}
$zip = Join-Path $outputRoot "$packageName.zip"
Compress-Archive -LiteralPath $stage -DestinationPath $zip -CompressionLevel Optimal
$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
"$hash  $packageName.zip" | Set-Content -LiteralPath (Join-Path $outputRoot 'SHA256SUMS.txt') -Encoding ascii
Write-Output $zip
Write-Output $hash

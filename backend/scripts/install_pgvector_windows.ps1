param(
    [string]$SourceRoot,
    [string]$PostgresRoot = "D:\postgresql\18"
)

$ErrorActionPreference = "Stop"

$source = Resolve-Path $SourceRoot
$target = Resolve-Path $PostgresRoot

if ($target.Path -ne "D:\postgresql\18") {
    throw "Unexpected PostgreSQL path: $($target.Path)"
}

Copy-Item -LiteralPath (Join-Path $source "lib\vector.dll") -Destination (Join-Path $target "lib\vector.dll") -Force
Copy-Item -Path (Join-Path $source "share\extension\*") -Destination (Join-Path $target "share\extension") -Force

$targetInclude = Join-Path $target "include\server\extension"
New-Item -ItemType Directory -Force -Path $targetInclude | Out-Null
Copy-Item -LiteralPath (Join-Path $source "include\server\extension\vector") -Destination $targetInclude -Recurse -Force

Write-Host "pgvector files installed to $($target.Path)"

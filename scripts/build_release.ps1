# Build the Go Jayu entrypoint for local distribution.

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$BinDir = Join-Path $Root "bin"
$Output = Join-Path $BinDir "jayu.exe"

New-Item -ItemType Directory -Force -Path $BinDir | Out-Null

Push-Location $Root
try {
    go test ./...
    go build -trimpath -ldflags="-s -w" -o $Output .\cmd\jayu
}
finally {
    Pop-Location
}

Write-Host "Built: $Output"
Write-Host "Runtime state remains external: state/, signals/, runs/, data/cache/"

$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$dataDir = Join-Path $workspace 'storage\postgres'
$postgresRoot = Get-ChildItem 'C:\Program Files\PostgreSQL' -Directory -ErrorAction SilentlyContinue |
  Sort-Object { [int]($_.Name -replace '\D', '') } -Descending |
  Select-Object -First 1

if (-not (Test-Path (Join-Path $dataDir 'PG_VERSION'))) {
  Write-Output 'The NINTH local PostgreSQL cluster is not initialized.'
  exit 0
}
if (-not $postgresRoot) { Write-Error 'PostgreSQL is not installed.' }

$pgctl = Join-Path $postgresRoot.FullName 'bin\pg_ctl.exe'
& $pgctl -D $dataDir status *> $null
if ($LASTEXITCODE -eq 0) {
  & $pgctl -D $dataDir stop -m fast
  Write-Output 'NINTH PostgreSQL stopped.'
} else {
  Write-Output 'NINTH PostgreSQL is already stopped.'
}

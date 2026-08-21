$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
$dataDir = Join-Path $workspace 'storage\postgres'
$postgresRoot = Get-ChildItem 'C:\Program Files\PostgreSQL' -Directory -ErrorAction SilentlyContinue |
  Sort-Object { [int]($_.Name -replace '\D', '') } -Descending |
  Select-Object -First 1

if (-not $postgresRoot) {
  Write-Error 'PostgreSQL is not installed. Install PostgreSQL 17+ or use docker-compose.auth.yml.'
}

$bin = Join-Path $postgresRoot.FullName 'bin'
$initdb = Join-Path $bin 'initdb.exe'
$pgctl = Join-Path $bin 'pg_ctl.exe'
$ready = Join-Path $bin 'pg_isready.exe'
$createdb = Join-Path $bin 'createdb.exe'
$psql = Join-Path $bin 'psql.exe'

if (-not (Test-Path (Join-Path $dataDir 'PG_VERSION'))) {
  New-Item -ItemType Directory -Path $dataDir -Force | Out-Null
  & $initdb -D $dataDir -U ninth -A trust --encoding=UTF8 --locale=C
}

& $ready -h 127.0.0.1 -p 54329 *> $null
if ($LASTEXITCODE -ne 0) {
  & $pgctl -D $dataDir -l (Join-Path $dataDir 'server.log') -o '-p 54329' start
}

for ($attempt = 0; $attempt -lt 20; $attempt++) {
  & $ready -h 127.0.0.1 -p 54329 *> $null
  if ($LASTEXITCODE -eq 0) { break }
  Start-Sleep -Milliseconds 500
}

$databaseExists = & $psql -h 127.0.0.1 -p 54329 -U ninth -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='ninth'"
if (-not $databaseExists -or [string]::Join('', $databaseExists).Trim() -ne '1') {
  & $createdb -h 127.0.0.1 -p 54329 -U ninth ninth
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
Write-Output 'NINTH PostgreSQL is ready on 127.0.0.1:54329.'

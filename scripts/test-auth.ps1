$ErrorActionPreference = 'Stop'
$workspace = Split-Path -Parent $PSScriptRoot
Set-Location $workspace

$envFile = Join-Path $workspace '.env'
if (Test-Path $envFile) {
  foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*([^#][^=]*)=(.*)$') {
      [Environment]::SetEnvironmentVariable($matches[1].Trim(), $matches[2], 'Process')
    }
  }
}

if (-not $env:TEST_DATABASE_URL) {
  $env:TEST_DATABASE_URL = 'postgresql://ninth@127.0.0.1:54329/ninth_test?schema=public'
}
$env:DATABASE_URL = $env:TEST_DATABASE_URL

& powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $workspace 'scripts\start-local-postgres.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$postgresRoot = Get-ChildItem 'C:\Program Files\PostgreSQL' -Directory -ErrorAction Stop |
  Sort-Object { [int]($_.Name -replace '\D', '') } -Descending |
  Select-Object -First 1
$createdb = Join-Path $postgresRoot.FullName 'bin\createdb.exe'
$psql = Join-Path $postgresRoot.FullName 'bin\psql.exe'
$databaseExists = & $psql -h 127.0.0.1 -p 54329 -U ninth -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='ninth_test'"
if (-not $databaseExists -or [string]::Join('', $databaseExists).Trim() -ne '1') {
  & $createdb -h 127.0.0.1 -p 54329 -U ninth ninth_test
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& npx.cmd prisma migrate deploy --schema server/prisma/schema.prisma
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& node --test --test-concurrency=1 server/src/modules/auth/auth.integration.test.js
exit $LASTEXITCODE

param()

$ErrorActionPreference = 'Stop'
(Get-Process -Id $PID).PriorityClass = 'BelowNormal'
$repositoryRoot = Split-Path -Parent $PSScriptRoot
$logDirectory = Join-Path $repositoryRoot 'logs'
$environmentFile = Join-Path $repositoryRoot '.env'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null

if (Test-Path -LiteralPath $environmentFile) {
  foreach ($rawLine in Get-Content -LiteralPath $environmentFile) {
    $line = $rawLine.Trim()
    if (-not $line -or $line.StartsWith('#') -or -not $line.Contains('=')) { continue }
    $parts = $line.Split('=', 2)
    $name = $parts[0].Trim()
    if ($name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { continue }
    $value = $parts[1].Trim()
    if (($value.StartsWith('"') -and $value.EndsWith('"')) -or ($value.StartsWith("'") -and $value.EndsWith("'"))) {
      $value = $value.Substring(1, $value.Length - 2)
    }
    [Environment]::SetEnvironmentVariable($name, $value, 'Process')
  }
}

$env:NINTH_MAINTENANCE_CATCHUP_ENABLED = '1'
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$logFile = Join-Path $logDirectory "nightly-maintenance-$timestamp.log"
$python = (Get-Command python -ErrorAction Stop).Source

Push-Location $repositoryRoot
try {
  & $python -m ml.maintenance --once *>> $logFile
  exit $LASTEXITCODE
} catch {
  $_ | Out-String | Add-Content -LiteralPath $logFile
  exit 1
} finally {
  Pop-Location
}

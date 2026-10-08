$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$toolsDir = Join-Path $repoRoot ".spectral-tools"
$spectralBin = Join-Path $toolsDir "node_modules\.bin\spectral.cmd"
$spectralVersion = "6.17.0"
$rulesetPath = Join-Path $toolsDir "openapi-ruleset.yaml"
$targetFile = Join-Path $repoRoot "docs\openapi.yaml"

if (-not (Test-Path -LiteralPath $spectralBin)) {
    New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
    npm install --prefix $toolsDir --no-save --no-package-lock --no-audit --no-fund "@stoplight/spectral-cli@$spectralVersion"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Falha a instalar @stoplight/spectral-cli@$spectralVersion (npm exit $LASTEXITCODE)."
        exit $LASTEXITCODE
    }
}

$ruleset = @'
extends: spectral:oas
rules:
  path-keys-no-trailing-slash: off
'@
Set-Content -LiteralPath $rulesetPath -Value $ruleset -Encoding utf8

Push-Location $repoRoot
try {
    & $spectralBin lint $targetFile --ruleset $rulesetPath --format pretty
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
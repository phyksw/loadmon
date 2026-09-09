$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskExisting = & git -C $taskRoot config --local --get core.hooksPath
if ($taskExisting -and $taskExisting -ne '.githooks') {
    throw "An existing local hooksPath is configured: $taskExisting"
}
& git -C $taskRoot config --local core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) { throw 'Git hook installation failed.' }
Write-Host 'Local Git pre-commit hook installed (.githooks).'
Write-Host 'Codex definitions are in .codex/hooks.json; use the Codex hook review UI to trust them.'

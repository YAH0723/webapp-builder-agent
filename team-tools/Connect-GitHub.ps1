param(
    [Parameter(Mandatory = $true)]
    [string]$RepositoryUrl
)
$ErrorActionPreference = 'Stop'
if ($RepositoryUrl -notmatch '^https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+(?:\.git)?/?$') {
    throw 'Use an HTTPS GitHub repository URL without credentials or query parameters.'
}
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location -LiteralPath $projectRoot
try {
    $branch = git branch --show-current
    if ($LASTEXITCODE -ne 0 -or $branch -ne 'main') { throw 'Switch to main before connecting.' }
    $changes = git status --porcelain
    if ($LASTEXITCODE -ne 0 -or $changes) { throw 'Commit or save pending changes before pushing.' }
    $existing = git remote get-url origin 2>$null
    if ($LASTEXITCODE -eq 0) {
        if ($existing.TrimEnd('/') -ne $RepositoryUrl.TrimEnd('/')) {
            throw 'origin already points elsewhere. Review it manually before changing it.'
        }
    } else {
        git remote add origin $RepositoryUrl
        if ($LASTEXITCODE -ne 0) { throw 'Could not set origin.' }
    }
    git push -u origin main
    if ($LASTEXITCODE -ne 0) {
        throw 'Push failed. Check that the empty repository exists and GitHub authentication is available. No force push was used.'
    }
    Write-Host 'main pushed. Invite teammates in the repository Collaborators settings.'
} finally {
    Pop-Location
}

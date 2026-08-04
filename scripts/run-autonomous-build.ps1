param(
    [ValidateRange(1, 50)]
    [int]$MaxRuns = 10
)

$ErrorActionPreference = "Stop"

# Quando lo script è salvato in scripts\, il parent è la root del repository.
# Il fallback permette anche di eseguirne il contenuto dalla root in emergenza.
if ([string]::IsNullOrWhiteSpace($PSScriptRoot)) {
    $RepoRoot = (Get-Location).Path
}
else {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}

Set-Location $RepoRoot

$PromptFile = Join-Path $RepoRoot "docs\AUTONOMOUS_BUILD_PROMPT.md"
$LogDirectory = Join-Path $RepoRoot "artifacts\autonomous-build"
$ProfileFile = Join-Path $HOME ".codex\carreros-autonomous.config.toml"

if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    throw "Codex CLI non trovato nel PATH."
}

if (-not (Test-Path $PromptFile)) {
    throw "Prompt file non trovato: $PromptFile"
}

if (-not (Test-Path $ProfileFile)) {
    throw "Profilo Codex non trovato: $ProfileFile"
}

if (-not (Test-Path (Join-Path $RepoRoot ".git"))) {
    throw "La directory non è un repository Git: $RepoRoot"
}

New-Item -ItemType Directory -Force $LogDirectory | Out-Null

$ActivateVenv = Join-Path $RepoRoot ".venv\Scripts\Activate.ps1"

if (Test-Path $ActivateVenv) {
    . $ActivateVenv
    Write-Host "Virtual environment attivato."
}

$currentBranch = git branch --show-current

if ($LASTEXITCODE -ne 0) {
    throw "Impossibile determinare il branch Git corrente."
}

Write-Host ""
Write-Host "Repository: $RepoRoot"
Write-Host "Branch: $currentBranch"
Write-Host "Numero massimo di run: $MaxRuns"

for ($run = 1; $run -le $MaxRuns; $run++) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $eventLog = Join-Path $LogDirectory "run-$run-$timestamp.jsonl"
    $lastMessage = Join-Path $LogDirectory "run-$run-$timestamp-final.txt"

    Write-Host ""
    Write-Host "=== Avvio run Codex $run di $MaxRuns ==="

    Get-Content $PromptFile -Raw |
        & codex exec `
            --profile carreros-autonomous `
            --sandbox workspace-write `
            --ask-for-approval never `
            --json `
            --output-last-message $lastMessage `
            - |
        Tee-Object -FilePath $eventLog |
        Out-Host

    $exitCode = $LASTEXITCODE

    if ($exitCode -ne 0) {
        Write-Warning "Codex è terminato con codice $exitCode."

        if ($run -eq $MaxRuns) {
            exit $exitCode
        }

        Start-Sleep -Seconds 10
        continue
    }

    if (-not (Test-Path $lastMessage)) {
        Write-Warning "Codex non ha generato il messaggio finale."

        if ($run -eq $MaxRuns) {
            exit 4
        }

        Start-Sleep -Seconds 10
        continue
    }

    $result = Get-Content $lastMessage -Raw

    Write-Host ""
    Write-Host "=== Risultato run $run ==="
    Write-Host $result

    if ($result -match "(?m)^\s*BUILD_COMPLETE\s*$") {
        Write-Host ""
        Write-Host "Build autonoma completata."
        exit 0
    }

    if ($result -match "(?m)^\s*BUILD_BLOCKED\s*$") {
        Write-Host ""
        Write-Host "Build bloccata da una dipendenza esterna."
        exit 2
    }

    if ($run -lt $MaxRuns) {
        Write-Host ""
        Write-Host "Build non ancora completata. Avvio di una nuova sessione."
        Start-Sleep -Seconds 10
    }
}

Write-Host ""
Write-Host "Raggiunto il numero massimo di run senza BUILD_COMPLETE."
exit 3

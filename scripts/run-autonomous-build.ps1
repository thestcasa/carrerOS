param(
    [ValidateRange(1, 50)]
    [int]$MaxRuns = 10
)

$ErrorActionPreference = "Stop"

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

if ((Get-Item $PromptFile).Length -eq 0) {
    throw "Il prompt file è vuoto: $PromptFile"
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
Write-Host "Prompt: $PromptFile"

for ($run = 1; $run -le $MaxRuns; $run++) {
    $timestamp = Get-Date -Format "yyyyMMdd-HHmmss"

    $eventLog = Join-Path `
        $LogDirectory `
        "run-$run-$timestamp.jsonl"

    $errorLog = Join-Path `
        $LogDirectory `
        "run-$run-$timestamp-stderr.txt"

    $lastMessage = Join-Path `
        $LogDirectory `
        "run-$run-$timestamp-final.txt"

    Write-Host ""
    Write-Host "=== Avvio run Codex $run di $MaxRuns ==="

    # cmd.exe gestisce in modo affidabile il passaggio del file
    # allo stdin di codex exec su Windows.
    $codexCommand = (
        "type `"$PromptFile`" | " +
        "codex exec " +
        "--profile carreros-autonomous " +
        "--sandbox workspace-write " +
        "--json " +
        "--output-last-message `"$lastMessage`" " +
        "- " +
        "2> `"$errorLog`""
    )

    & $env:ComSpec /d /c $codexCommand |
        Tee-Object -FilePath $eventLog |
        Out-Host

    $exitCode = $LASTEXITCODE

    if (Test-Path $errorLog) {
        $stderrText = Get-Content $errorLog -Raw

        if (-not [string]::IsNullOrWhiteSpace($stderrText)) {
            Write-Host ""
            Write-Host "=== Output diagnostico Codex ==="
            Write-Host $stderrText
        }
    }

    if ($exitCode -ne 0) {
        Write-Warning "Codex è terminato con codice $exitCode."

        if ($run -eq $MaxRuns) {
            exit $exitCode
        }

        Write-Host "Nuovo tentativo tra 10 secondi."
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
        Write-Host "Build non ancora completata."
        Write-Host "Avvio di una nuova sessione tra 10 secondi."
        Start-Sleep -Seconds 10
    }
}

Write-Host ""
Write-Host "Raggiunto il numero massimo di run senza BUILD_COMPLETE."
exit 3

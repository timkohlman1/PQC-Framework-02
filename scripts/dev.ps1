[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CommandArgs
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$imageName = if ($env:PQC_DOCKER_IMAGE) { $env:PQC_DOCKER_IMAGE } else { "pqc-framework-stm32-build" }
$sshSource = if ($env:PQC_DOCKER_SSH_DIR) { $env:PQC_DOCKER_SSH_DIR } else { Join-Path $env:USERPROFILE ".ssh" }

function Invoke-DockerRun {
    param(
        [string[]]$InnerArgs,
        [switch]$Gateway
    )

    $dockerArgs = @(
        "run", "--rm",
        "-v", "${repoRoot}:/workspace",
        "-w", "/workspace"
    )

    if ($Gateway) {
        if (-not (Test-Path -LiteralPath $sshSource)) {
            throw "Gateway mode requires an SSH directory. Set PQC_DOCKER_SSH_DIR or create $sshSource."
        }
        $dockerArgs += @(
            "-e", "PQC_CONTAINER_ENABLE_GATEWAY=1",
            "-v", "${sshSource}:/host-ssh:ro"
        )
        $setup = "mkdir -p /root/.ssh && cp -r /host-ssh/. /root/.ssh/ && chmod 700 /root/.ssh && find /root/.ssh -type f -exec chmod 600 {} \; && find /root/.ssh -type d -exec chmod 700 {} \;"
        $quotedInner = ($InnerArgs | ForEach-Object { "'" + ($_ -replace "'", "'\\''") + "'" }) -join " "
        $dockerArgs += @($imageName, "sh", "-lc", "$setup && $quotedInner")
    }
    else {
        $dockerArgs += @($imageName)
        $dockerArgs += $InnerArgs
    }

    & docker @dockerArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

if (-not $CommandArgs -or $CommandArgs.Count -eq 0) {
    Write-Host "Usage: scripts\dev.ps1 <build-image|pytest|pytest-gateway|pytest-hardware|experiment|experiment-gateway|python|python-gateway|cmake|shell|run> [args...]"
    exit 2
}

$command = $CommandArgs[0]
$rest = @()
if ($CommandArgs.Count -gt 1) {
    $rest = $CommandArgs[1..($CommandArgs.Count - 1)]
}

switch ($command) {
    "build-image" {
        & docker build -f docker/python/Dockerfile -t $imageName .
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    "pytest" {
        Invoke-DockerRun -InnerArgs (@("python", "-m", "pytest") + $rest)
    }
    "pytest-gateway" {
        Invoke-DockerRun -Gateway -InnerArgs (@("python", "-m", "pytest") + $rest)
    }
    "pytest-hardware" {
        $pytestArgs = if ($rest.Count -eq 0) { @("tests/hardware", "-m", "hardware", "--pqc-require-hardware") } else { $rest }
        Invoke-DockerRun -Gateway -InnerArgs (@("python", "-m", "pytest") + $pytestArgs)
    }
    "experiment" {
        Invoke-DockerRun -InnerArgs (@("python", "scripts/experiment.py") + $rest)
    }
    "experiment-gateway" {
        Invoke-DockerRun -Gateway -InnerArgs (@("python", "scripts/experiment.py") + $rest)
    }
    "python" {
        Invoke-DockerRun -InnerArgs (@("python") + $rest)
    }
    "python-gateway" {
        Invoke-DockerRun -Gateway -InnerArgs (@("python") + $rest)
    }
    "cmake" {
        Invoke-DockerRun -InnerArgs (@("cmake") + $rest)
    }
    "shell" {
        Invoke-DockerRun -InnerArgs (@("sh") + $rest)
    }
    "run" {
        Invoke-DockerRun -InnerArgs $rest
    }
    default {
        throw "Unknown dev command '$command'."
    }
}

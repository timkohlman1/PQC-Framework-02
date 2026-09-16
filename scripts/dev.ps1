[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CommandArgs
)

$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$imageName = if ($env:PQC_DOCKER_IMAGE) { $env:PQC_DOCKER_IMAGE } else { "pqc-framework-stm32-build" }
$sshSource = if ($env:PQC_DOCKER_SSH_DIR) { $env:PQC_DOCKER_SSH_DIR } else { Join-Path $env:USERPROFILE ".ssh" }


function Import-LocalDotEnv {
    $envPath = Join-Path $repoRoot ".env"
    $loadedNames = @()

    if (-not (Test-Path -LiteralPath $envPath)) {
        return $loadedNames
    }

    $allowedNames = @("PQC_WIFI_SSID", "PQC_WIFI_PSK")
    $parsed = @{}

    foreach ($rawLine in Get-Content -LiteralPath $envPath) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }

        $parts = $line -split "=", 2
        if ($parts.Count -ne 2) {
            throw "Invalid .env entry. Expected NAME=value."
        }

        $name = $parts[0].Trim()
        if ($name -notin $allowedNames) {
            continue
        }

        $value = $parts[1].Trim()
        if ($value.Length -ge 2) {
            $first = $value.Substring(0, 1)
            $last = $value.Substring($value.Length - 1, 1)
            if (($first -eq '"' -and $last -eq '"') -or ($first -eq "'" -and $last -eq "'")) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }
        $parsed[$name] = $value
    }

    foreach ($name in $allowedNames) {
        # Explicit shell/session environment variables take precedence over .env.
        if ($parsed.ContainsKey($name) -and $null -eq [Environment]::GetEnvironmentVariable($name, "Process")) {
            [Environment]::SetEnvironmentVariable($name, [string]$parsed[$name], "Process")
            $loadedNames += $name
        }
    }

    return $loadedNames
}

function Remove-LocalDotEnvVariables {
    param([string[]]$Names)

    foreach ($name in $Names) {
        if ([string]::IsNullOrWhiteSpace($name)) {
            continue
        }
        [Environment]::SetEnvironmentVariable($name, $null, "Process")
    }
}

function Invoke-DockerRun {
    param(
        [string[]]$InnerArgs,
        [switch]$Gateway
    )

    $dotenvNames = @()
    $dockerExitCode = 0

    try {
        $dotenvNames = @(Import-LocalDotEnv)

        $dockerArgs = @(
            "run", "--rm",
            "-v", "${repoRoot}:/workspace",
            "-w", "/workspace"
        )

        if ($env:PQC_WIFI_SSID) {
            $dockerArgs += @("-e", "PQC_WIFI_SSID")
        }

        if ($env:PQC_WIFI_PSK) {
            $dockerArgs += @("-e", "PQC_WIFI_PSK")
        }

        if ($env:PQC_CAMPAIGN_HW) {
            $dockerArgs += @("-e", "PQC_CAMPAIGN_HW")
        }

        if ($env:PQC_CAMPAIGN_HW_CONFIG) {
            $dockerArgs += @("-e", "PQC_CAMPAIGN_HW_CONFIG")
        }

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
        $dockerExitCode = $LASTEXITCODE
    }
    finally {
        # Variables sourced from .env exist only for this invocation. Values that
        # already existed in the caller's environment were never overwritten.
        Remove-LocalDotEnvVariables -Names $dotenvNames
    }

    if ($dockerExitCode -ne 0) {
        exit $dockerExitCode
    }
}

if (-not $CommandArgs -or $CommandArgs.Count -eq 0) {
    Write-Host "Usage: scripts\dev.ps1 <build-image|pytest|pytest-gateway|pytest-hardware|experiment|experiment-gateway|campaign|campaign-gateway|python|python-gateway|cmake|shell|run> [args...]"
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
    "campaign" {
        Invoke-DockerRun -InnerArgs (@("python", "scripts/run_campaign.py") + $rest)
    }
    "campaign-gateway" {
        Invoke-DockerRun -Gateway -InnerArgs (@("python", "scripts/run_campaign.py") + $rest)
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

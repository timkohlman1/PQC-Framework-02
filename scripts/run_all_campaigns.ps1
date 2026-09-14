[CmdletBinding()]
param(
    [string]$ResultsRoot = "results",
    [switch]$StopOnFailure
)

$ErrorActionPreference = "Stop"

# Always operate from the repository root containing this script's parent scripts directory.
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

$DevScript = Join-Path $RepoRoot "scripts\dev.ps1"
$CampaignDir = Join-Path $RepoRoot "configs\campaigns"
$GeneratedCampaignRoot = Join-Path $RepoRoot ".pqc-generated-state\campaigns"

if (-not (Test-Path $DevScript)) {
    throw "Repository wrapper not found: $DevScript"
}
if (-not (Test-Path $CampaignDir)) {
    throw "Campaign directory not found: $CampaignDir"
}

# Discover the canonical campaign inventory dynamically so the runner follows the
# source-controlled campaign set rather than a hard-coded historical list.
$CampaignFiles = @(Get-ChildItem -Path $CampaignDir -Filter "*.yaml" -File | Sort-Object Name)

if ($CampaignFiles.Count -eq 0) {
    throw "No campaign YAML files found under $CampaignDir"
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$BatchRoot = Join-Path $RepoRoot "$ResultsRoot\campaign-batch\$Timestamp"
$LogRoot = Join-Path $BatchRoot "logs"
$SummaryCsv = Join-Path $BatchRoot "summary.csv"
$SummaryJson = Join-Path $BatchRoot "summary.json"
$TranscriptPath = Join-Path $BatchRoot "console-transcript.txt"

New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null

$Summary = [System.Collections.Generic.List[object]]::new()
$ResolvedCampaigns = [System.Collections.Generic.List[object]]::new()

function Get-RelativeRepoPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    $full = (Resolve-Path $Path).Path

    # Windows PowerShell 5.1 runs on .NET Framework, which does not provide
    # [System.IO.Path]::GetRelativePath(). Use System.Uri instead so this script
    # works in both Windows PowerShell 5.1 and newer PowerShell versions.
    $repoWithSlash = $RepoRoot.TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    $repoUri = [System.Uri]::new($repoWithSlash)
    $pathUri = [System.Uri]::new($full)
    $relative = [System.Uri]::UnescapeDataString($repoUri.MakeRelativeUri($pathUri).ToString())

    return ($relative -replace '\\', '/')
}

function Add-SummaryRow {
    param(
        [string]$Phase,
        [string]$Campaign,
        [string]$Case,
        [string]$Path,
        [int]$ExitCode,
        [datetime]$Started,
        [datetime]$Finished,
        [string]$Log
    )

    $Summary.Add([pscustomobject]@{
        phase            = $Phase
        campaign         = $Campaign
        case             = $Case
        path             = $Path
        exit_code        = $ExitCode
        status           = if ($ExitCode -eq 0) { "PASS" } else { "FAIL" }
        started_at       = $Started.ToString("o")
        finished_at      = $Finished.ToString("o")
        duration_seconds = [math]::Round(($Finished - $Started).TotalSeconds, 3)
        log              = $Log
    })
}

function Write-SummaryFiles {
    $Summary | Export-Csv -Path $SummaryCsv -NoTypeInformation -Encoding UTF8
    $Summary | ConvertTo-Json -Depth 5 | Set-Content -Path $SummaryJson -Encoding UTF8
}

function Invoke-LoggedCommand {
    param(
        [Parameter(Mandatory = $true)][string]$LogPath,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )

    # The batch runner itself uses ErrorActionPreference=Stop, but child commands
    # must be allowed to fail without terminating the overnight batch. Windows
    # PowerShell 5.1 can surface native stderr as ErrorRecord objects when streams
    # are merged, so temporarily use Continue while the command is captured.
    $savedErrorActionPreference = $ErrorActionPreference
    $commandExitCode = 1

    try {
        $ErrorActionPreference = "Continue"
        & $Command *>&1 | Tee-Object -FilePath $LogPath | Out-Host

        if ($null -ne $LASTEXITCODE) {
            $commandExitCode = [int]$LASTEXITCODE
        }
        else {
            $commandExitCode = 0
        }
    }
    catch {
        $_ | Out-String | Tee-Object -FilePath $LogPath -Append | Out-Host
        if ($null -ne $LASTEXITCODE -and [int]$LASTEXITCODE -ne 0) {
            $commandExitCode = [int]$LASTEXITCODE
        }
        else {
            $commandExitCode = 1
        }
    }
    finally {
        $ErrorActionPreference = $savedErrorActionPreference
    }

    return [int]$commandExitCode
}

Start-Transcript -Path $TranscriptPath -Force | Out-Null

try {
    Write-Host ""
    Write-Host "PQC campaign batch runner"
    Write-Host "========================="
    Write-Host "Repository: $RepoRoot"
    Write-Host "Campaigns discovered: $($CampaignFiles.Count)"
    Write-Host "Batch evidence: $BatchRoot"
    Write-Host ""

    # Wi-Fi values are intentionally not stored in generated cases. Warn before a
    # long unattended run if they are absent, but leave final validation to the framework.
    if (-not $env:PQC_WIFI_SSID -or -not $env:PQC_WIFI_PSK) {
        Write-Warning "PQC_WIFI_SSID and/or PQC_WIFI_PSK are not set in this PowerShell environment."
        Write-Warning "Generated cases do not contain these secrets; hardware runs that require Wi-Fi may fail."
    }

    # -------------------------------------------------------------------------
    # Phase 1: Resolve/materialise every source-controlled campaign first.
    # -------------------------------------------------------------------------
    Write-Host ""
    Write-Host "PHASE 1 - Resolve all campaigns"
    Write-Host "==============================="

    foreach ($CampaignFile in $CampaignFiles) {
        $CampaignName = $CampaignFile.BaseName
        $ResolveLog = Join-Path $LogRoot ("resolve_{0}.log" -f $CampaignName)

        Write-Host ""
        Write-Host "Resolving campaign: $CampaignName"
        Write-Host "Source: $($CampaignFile.FullName)"

        $Started = Get-Date
        $ExitCode = Invoke-LoggedCommand -LogPath $ResolveLog -Command {
            & $DevScript python scripts/resolve_campaign.py $CampaignFile.Name
        }
        $Finished = Get-Date

        Add-SummaryRow `
            -Phase "resolve" `
            -Campaign $CampaignName `
            -Case "" `
            -Path (Get-RelativeRepoPath $CampaignFile.FullName) `
            -ExitCode $ExitCode `
            -Started $Started `
            -Finished $Finished `
            -Log (Get-RelativeRepoPath $ResolveLog)

        if ($ExitCode -ne 0) {
            Write-Error "Campaign resolution failed: $CampaignName (exit $ExitCode)" -ErrorAction Continue
            Write-SummaryFiles
            if ($StopOnFailure) {
                throw "Stopping because -StopOnFailure was specified."
            }
            continue
        }

        $CaseDir = Join-Path $GeneratedCampaignRoot "$CampaignName\cases"
        if (-not (Test-Path $CaseDir)) {
            Write-Error "Resolver succeeded but case directory was not created: $CaseDir" -ErrorAction Continue
            Add-SummaryRow `
                -Phase "discover" `
                -Campaign $CampaignName `
                -Case "" `
                -Path "" `
                -ExitCode 90 `
                -Started $Finished `
                -Finished (Get-Date) `
                -Log ""
            Write-SummaryFiles
            if ($StopOnFailure) {
                throw "Stopping because -StopOnFailure was specified."
            }
            continue
        }

        $Cases = @(Get-ChildItem -Path $CaseDir -Filter "*.yaml" -File | Sort-Object Name)
        if ($Cases.Count -eq 0) {
            Write-Error "Resolver succeeded but generated no case YAML files for: $CampaignName" -ErrorAction Continue
            Add-SummaryRow `
                -Phase "discover" `
                -Campaign $CampaignName `
                -Case "" `
                -Path (Get-RelativeRepoPath $CaseDir) `
                -ExitCode 91 `
                -Started $Finished `
                -Finished (Get-Date) `
                -Log ""
            Write-SummaryFiles
            if ($StopOnFailure) {
                throw "Stopping because -StopOnFailure was specified."
            }
            continue
        }

        $ResolvedCampaigns.Add([pscustomobject]@{
            Name  = $CampaignName
            Cases = $Cases
        })

        Write-Host "Generated cases: $($Cases.Count)"
    }

    $TotalCases = ($ResolvedCampaigns | ForEach-Object { $_.Cases.Count } | Measure-Object -Sum).Sum
    if ($null -eq $TotalCases) {
        $TotalCases = 0
    }

    Write-Host ""
    Write-Host "Resolution complete."
    Write-Host "Campaigns ready to execute: $($ResolvedCampaigns.Count)"
    Write-Host "Generated cases ready to execute: $TotalCases"

    if ($TotalCases -eq 0) {
        throw "No generated campaign cases are available to execute."
    }

    # -------------------------------------------------------------------------
    # Phase 2: Execute every generated case sequentially.
    # A failing case is recorded and the batch continues unless -StopOnFailure
    # was explicitly requested.
    # -------------------------------------------------------------------------
    Write-Host ""
    Write-Host "PHASE 2 - Run all generated cases"
    Write-Host "================================="

    $CaseOrdinal = 0

    foreach ($Campaign in $ResolvedCampaigns) {
        Write-Host ""
        Write-Host "Campaign: $($Campaign.Name)"
        Write-Host ("-" * (10 + $Campaign.Name.Length))

        foreach ($CaseFile in $Campaign.Cases) {
            $CaseOrdinal++
            $RelativeCasePath = Get-RelativeRepoPath $CaseFile.FullName
            $CaseName = $CaseFile.BaseName

            $SafeCaseName = ($CaseName -replace '[^A-Za-z0-9_.-]', '_')
            $RunLog = Join-Path $LogRoot (
                "run_{0:D3}_{1}_{2}.log" -f $CaseOrdinal, $Campaign.Name, $SafeCaseName
            )

            Write-Host ""
            Write-Host ("[{0}/{1}] {2} :: {3}" -f $CaseOrdinal, $TotalCases, $Campaign.Name, $CaseName)
            Write-Host "Experiment: $RelativeCasePath"

            $Started = Get-Date
            $ExitCode = Invoke-LoggedCommand -LogPath $RunLog -Command {
                & $DevScript experiment-gateway run --experiment $RelativeCasePath
            }
            $Finished = Get-Date

            Add-SummaryRow `
                -Phase "run" `
                -Campaign $Campaign.Name `
                -Case $CaseName `
                -Path $RelativeCasePath `
                -ExitCode $ExitCode `
                -Started $Started `
                -Finished $Finished `
                -Log (Get-RelativeRepoPath $RunLog)

            Write-SummaryFiles

            if ($ExitCode -eq 0) {
                Write-Host "PASS: $($Campaign.Name) / $CaseName"
            }
            else {
                Write-Warning "FAIL: $($Campaign.Name) / $CaseName (exit $ExitCode)"
                if ($StopOnFailure) {
                    throw "Stopping because -StopOnFailure was specified."
                }
            }
        }
    }

    # -------------------------------------------------------------------------
    # Final batch summary.
    # -------------------------------------------------------------------------
    Write-SummaryFiles

    $ResolveRows = @($Summary | Where-Object { $_.phase -eq "resolve" })
    $RunRows = @($Summary | Where-Object { $_.phase -eq "run" })
    $PassedRuns = @($RunRows | Where-Object { $_.exit_code -eq 0 }).Count
    $FailedRuns = @($RunRows | Where-Object { $_.exit_code -ne 0 }).Count
    $FailedResolves = @($ResolveRows | Where-Object { $_.exit_code -ne 0 }).Count

    Write-Host ""
    Write-Host "BATCH COMPLETE"
    Write-Host "=============="
    Write-Host "Campaigns discovered : $($CampaignFiles.Count)"
    Write-Host "Campaign resolve fails: $FailedResolves"
    Write-Host "Cases attempted       : $($RunRows.Count)"
    Write-Host "Cases passed          : $PassedRuns"
    Write-Host "Cases failed          : $FailedRuns"
    Write-Host "Summary CSV           : $SummaryCsv"
    Write-Host "Summary JSON          : $SummaryJson"
    Write-Host "Transcript            : $TranscriptPath"
    Write-Host ""

    if ($FailedResolves -gt 0 -or $FailedRuns -gt 0) {
        exit 1
    }

    exit 0
}
finally {
    try {
        Stop-Transcript | Out-Null
    }
    catch {
        # Ignore transcript shutdown errors so they do not hide experiment results.
    }
}

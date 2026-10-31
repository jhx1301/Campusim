param(
    [Parameter(Mandatory = $true)][string]$Experiment,
    [Parameter(Mandatory = $true)][int]$Seed,
    [ValidateSet(32, 64)][int]$Until = 32
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location -LiteralPath $repoRoot
$plan = Get-Content -LiteralPath $Experiment -Raw -Encoding UTF8 | ConvertFrom-Json
$entry = $plan.seeds | Where-Object { $_.seed -eq $Seed }
if (-not $entry) { throw "Seed $Seed is absent from the prepared experiment." }
$settings = Get-Content -LiteralPath $entry.settings_path -Raw -Encoding UTF8 | ConvertFrom-Json
$keyName = $settings.api_key_env
if (-not [Environment]::GetEnvironmentVariable($keyName, 'Process')) {
    foreach ($scope in @('User', 'Machine')) {
        $credential = [Environment]::GetEnvironmentVariable($keyName, $scope)
        if ($credential) {
            [Environment]::SetEnvironmentVariable($keyName, $credential, 'Process')
            break
        }
    }
}
if (-not [Environment]::GetEnvironmentVariable($keyName, 'Process')) {
    throw "Required credential environment variable $keyName is absent."
}
$env:OMP_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:OPENBLAS_NUM_THREADS = '1'
$env:NUMEXPR_NUM_THREADS = '1'
$env:PYTHONUTF8 = '1'

foreach ($checkpoint in $entry.checkpoints | Where-Object { $_.episodes -le $Until }) {
    $frozen = $checkpoint.frozen_library
    $manifest = [IO.Path]::ChangeExtension($frozen, 'manifest.json')
    if (Test-Path -LiteralPath $frozen) {
        if (-not (Test-Path -LiteralPath $manifest)) {
            throw "Incomplete frozen checkpoint; inspect $frozen before continuing."
        }
        Write-Output "Seed $Seed checkpoint $($checkpoint.episodes) already frozen."
        continue
    }
    $arguments = @('-B', '-X', 'utf8', '-m', 'examples.control_v1.learn_memory',
        '--protocol', $entry.protocol_path, 'train', '--episodes', $checkpoint.episodes_path,
        '--settings', $entry.settings_path, '--library', $entry.library,
        '--output', $entry.runs_directory, '--artifact', $plan.calibration_artifact)
    if ($plan.calibration_data_path) { $arguments += @('--data', $plan.calibration_data_path) }
    Write-Output "Starting seed $Seed through episode $($checkpoint.episodes)."
    & $plan.python @arguments
    if ($LASTEXITCODE -ne 0) { throw "Seed $Seed training failed; the current episode was rolled back. Inspect its run audit." }
    & $plan.python -B -X utf8 -m examples.control_v1.learn_memory freeze --library $entry.library --output $frozen
    if ($LASTEXITCODE -ne 0) { throw "Seed $Seed completed training but freezing failed; inspect $frozen." }
    Write-Output "Seed $Seed checkpoint $($checkpoint.episodes) frozen at $frozen."
}

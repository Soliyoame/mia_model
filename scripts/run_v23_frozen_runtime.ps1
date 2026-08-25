[CmdletBinding()]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]]$RunnerArguments
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$frozenCommit = "f00205f1933863357458f5741ab8bf9115e56126"
$frozenWorktree = "${projectRoot}_v23_runtime_r2"
$gitDir = Join-Path $projectRoot ".git\worktrees\mia_model_v23_runtime_r2"
$pythonExecutable = "D:\python\anaconda\envs\mia_model\python.exe"
$runner = Join-Path $projectRoot "scripts\42_run_v23_restoration_first.py"

if ($RunnerArguments.Count -eq 0) {
    throw "v23 runner arguments are required"
}
if (-not (Test-Path -LiteralPath $pythonExecutable -PathType Leaf)) {
    throw "mia_model Python executable is missing: $pythonExecutable"
}
if (-not (Test-Path -LiteralPath $runner -PathType Leaf)) {
    throw "v23 runner is missing: $runner"
}
if (-not (Test-Path -LiteralPath $frozenWorktree -PathType Container)) {
    throw "frozen v23 runtime worktree is missing: $frozenWorktree"
}
if (-not (Test-Path -LiteralPath $gitDir -PathType Container)) {
    throw "frozen v23 runtime git directory is missing: $gitDir"
}
$actualCommitOutput = & git --git-dir=$gitDir rev-parse HEAD
if ($LASTEXITCODE -ne 0 -or $null -eq $actualCommitOutput) {
    throw "cannot read frozen v23 runtime commit"
}
$actualCommit = ([string]$actualCommitOutput).Trim()
if ($actualCommit -ne $frozenCommit) {
    throw "frozen v23 runtime commit drift: $actualCommit"
}

$previousGitDir = [Environment]::GetEnvironmentVariable("GIT_DIR", "Process")
$previousGitWorkTree = [Environment]::GetEnvironmentVariable("GIT_WORK_TREE", "Process")
$runnerExitCode = 1
try {
    [Environment]::SetEnvironmentVariable("GIT_DIR", $gitDir, "Process")
    [Environment]::SetEnvironmentVariable("GIT_WORK_TREE", $projectRoot, "Process")
    & $pythonExecutable -X utf8 -B $runner @RunnerArguments
    $runnerExitCode = $LASTEXITCODE
}
finally {
    [Environment]::SetEnvironmentVariable("GIT_DIR", $previousGitDir, "Process")
    [Environment]::SetEnvironmentVariable("GIT_WORK_TREE", $previousGitWorkTree, "Process")
}

exit $runnerExitCode

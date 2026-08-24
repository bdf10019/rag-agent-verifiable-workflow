[CmdletBinding()]
param(
    [string]$PythonExecutable = "python"
)

$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Push-Location $projectRoot
try {
    & $PythonExecutable -m pip check
    if ($LASTEXITCODE -ne 0) { throw "Dependency check failed." }
    & $PythonExecutable -m compileall -q src
    if ($LASTEXITCODE -ne 0) { throw "Python compilation failed." }
    & $PythonExecutable -m ruff check src tests
    if ($LASTEXITCODE -ne 0) { throw "Ruff failed." }
    & $PythonExecutable -m mypy src
    if ($LASTEXITCODE -ne 0) { throw "Mypy failed." }
    & $PythonExecutable -m pytest --cov=opsflow_agent --cov-report=term-missing
    if ($LASTEXITCODE -ne 0) { throw "Tests failed." }
    & $PythonExecutable -m opsflow_agent --database outputs/verify.db doctor
    if ($LASTEXITCODE -ne 0) { throw "Runtime diagnostics failed." }
    & $PythonExecutable -m opsflow_agent --database outputs/verify.db evaluate --output outputs/evaluation-report.json
    if ($LASTEXITCODE -ne 0) { throw "Offline evaluation failed." }
    & (Join-Path $PSScriptRoot "privacy-check.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Privacy check failed." }
    Write-Host "All verification stages passed."
}
finally {
    Pop-Location
}

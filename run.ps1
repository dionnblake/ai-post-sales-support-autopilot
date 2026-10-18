$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) {
    throw 'Create .venv and install requirements-dev.txt as described in README.md first.'
}
$taskTemp = Join-Path $projectRoot 'work\tmp'
[void][System.IO.Directory]::CreateDirectory($taskTemp)
$env:TEMP = $taskTemp
$env:TMP = $taskTemp
$env:PYTHONDONTWRITEBYTECODE = '1'
Set-Location -LiteralPath $projectRoot
& $pythonPath -m streamlit run (Join-Path $projectRoot 'app.py') --server.address 127.0.0.1 --server.port 8517
exit $LASTEXITCODE

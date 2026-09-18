param([switch]$Scripted,[switch]$KeepDeny)
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$demoArgs = @('run_demo.py')
if ($Scripted) { $demoArgs += '--scripted' }
if ($KeepDeny) { $demoArgs += '--keep-deny' }
& .\.venv\Scripts\python.exe @demoArgs
exit $LASTEXITCODE

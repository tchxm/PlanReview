# One command: site + API + real pipeline (Terraform + Cedar) + local emulator. Open http://127.0.0.1:8000/
Set-Location $PSScriptRoot
& (Join-Path $PSScriptRoot '.venv\Scripts\python.exe') run_site.py

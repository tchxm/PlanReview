# Starts the Vite dev server on 127.0.0.1:5173. /api is proxied to FastAPI (127.0.0.1:8000).
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot 'web')
if (-not (Test-Path 'node_modules')) { npm ci }
npm run dev

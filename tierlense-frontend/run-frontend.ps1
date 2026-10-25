$ErrorActionPreference = "Stop"

if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "Node.js/npm was not found. Install a current Node.js LTS release, reopen PowerShell, and retry."
}

if (-not (Test-Path ".\package.json")) {
    throw "Run this script from the tierlense-frontend directory."
}

if (-not (Test-Path ".\node_modules")) {
    Write-Host "Installing frontend dependencies..."
    npm install
    if ($LASTEXITCODE -ne 0) { throw "npm install failed." }
}

Write-Host "Starting TierLense frontend at http://localhost:5173"
npm run dev

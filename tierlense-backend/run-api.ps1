$ErrorActionPreference = "Stop"

if (-not (Test-Path ".venv\Scripts\Activate.ps1")) {
    throw "Virtual environment not found. Follow README.md setup steps first."
}
. ".venv\Scripts\Activate.ps1"
alembic upgrade head
uvicorn tierlense.main:app --app-dir src --reload

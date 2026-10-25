# TierLense Frontend

A complete light-mode React/Vite workspace for the TierLense supply-chain intelligence backend. The refreshed design follows the uploaded admin reference's Inter system-font stack, 256px navigation rail, 80px top bar, neutral white/grey palette, thin borders, measured 32px desktop page gutters, and restrained active states. Core text, inputs and tables use readable enterprise sizing; labels remain compact only where they serve as metadata. No dark mode, neon styling or remote font dependency is used.

## Features

- Data-driven overview with supply-network graph, disruption-severity chart, investigation status bars, entity-composition chart and evidence-pipeline summary.
- Organization registry, onboarding, organization detail editing and dependency watch-profile management.
- Investigation history, queue status, progress, result summaries and execution/provider metrics. Queueing a job includes an explicit warning that an active worker may call configured external providers.
- Supply-chain dependency explorer with interactive graph nodes, tier/direction/depth controls, entity registration, evidence-backed relationship registration, experimental likelihood index and downstream impact analysis.
- Disruption register, source-passage-based event creation and downstream impact results.
- Evidence library assembled from documents referenced by graph relationships, disruption events, investigation snapshots and detected evidence changes, including source excerpts and linked passages.
- Deterministic alternative-supplier assessments with country constraints, rationale, missing information, supporting passages and persisted history.
- Recurring scan schedule configuration, point-in-time snapshots and source-content change tracking.
- API connectivity / health checks and configurable API base URL.
- Responsive layout for desktop, tablet and mobile navigation.

## Requirements

- Node.js 20+ recommended
- TierLense FastAPI backend running locally (default `http://127.0.0.1:8000`)
- Backend migrations applied and the documented API routes available

## Run on Windows PowerShell

```powershell
cd .\tierlense-frontend
npm install
npm run dev
```

Open `http://localhost:5173` (use `localhost` to match the backend CORS default).

In another PowerShell window, start the API from the backend directory using its existing setup, for example:

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn tierlense.main:app --app-dir src --reload
```

The frontend defaults to `http://127.0.0.1:8000/api/v1`. You can change this in **API & preferences** or set an environment variable before starting Vite:

```powershell
$env:VITE_API_BASE_URL = "http://127.0.0.1:8000/api/v1"
npm run dev
```

If the browser reports a CORS error, configure the backend's CORS middleware to allow the frontend origin `http://localhost:5173` (or run the frontend and API behind a same-origin development proxy). This frontend does not bypass browser security.

## PDS-4 presentation demo defaults

The **Add organization** form is pre-filled with `PDS-4 Demo - Army Logistics Spares (SIMULATED)` and the fixture's demonstration values. These values intentionally match the backend demo trigger. To populate the synthetic four-tier graph, disruption scenarios, evidence and alternate-supplier recommendations during registration, start the backend API with `ENABLE_PDS4_DEMO_SCENARIO=true`. The flag is opt-in and registration must use the exact organization name.

All fixture entities, ownership links, evidence passages, disruption scenarios and alternatives are fictional. This is a presentation dataset inspired by the PDS No. 4 problem domain; it is not an actual Indian Army procurement network or official assessment. The form resets to these demo defaults each time you open it and after a successful registration.

## Model-free acceptance work

The frontend does not call model providers directly and contains no provider API keys. However, creating an organization, queueing an investigation, or enabling automatic scheduling can cause provider work to run through the separate backend worker. Keep the worker stopped when conducting model-free validation. Read-only dashboard, history, evidence and graph requests are ordinary API reads, although the backend likelihood endpoint persists a deterministic experimental assessment when invoked.

## Notes and boundaries

- No mock dashboard data is inserted. Charts are computed from API records; empty states are shown when a graph or signal set is empty.
- The supplied API surface does not define a user-authentication/session contract, so this frontend does not invent an authentication system. Restrict access to the local backend; implement API-side authentication/authorization before exposing it to a wider network.
- Alternative-supplier scores indicate deterministic function matching, not verified supplier readiness or qualification.
- Disruption likelihood is explicitly labeled experimental and uncalibrated.
- The Evidence Library indexes documents returned from related records because the reviewed API contract exposes document inspection by ID rather than a global evidence-document list endpoint.

## Production build

```powershell
npm run build
npm run preview
```
### Human-readable investigation details

Investigation detail views render result summaries and execution metrics as readable sections and metric cards, not raw JSON. Results are grouped into source discovery, findings and validation, supply-chain graph and risk, and scenario/safeguards. Provider usage is broken down by provider and stage, including request outcomes and token counts. The demo scenario explicitly notes when data was loaded locally with no external model-provider activity.

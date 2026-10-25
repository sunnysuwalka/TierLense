# Frontend-to-backend API map

All requests use the configured API base URL (default `http://127.0.0.1:8000/api/v1`). This map describes the routes used by the frontend, derived from the supplied TierLense Sprint 1, 3 and 4 backend source.

| Frontend area | Routes used |
|---|---|
| Connection status | `GET /health/live`, `GET /health/ready` |
| Organization registry | `GET /organizations`, `POST /organizations`, `GET /organizations/{organization_id}`, `PATCH /organizations/{organization_id}`, `PUT /organizations/{organization_id}/watch-profile` |
| Investigation jobs | `GET /organizations/{organization_id}/investigation-jobs`, `POST /organizations/{organization_id}/investigation-jobs` |
| Supply-chain graph | `GET /supply-chain/organizations/{organization_id}/entities`, `POST /supply-chain/organizations/{organization_id}/entities`, `GET /supply-chain/organizations/{organization_id}/relationships`, `POST /supply-chain/organizations/{organization_id}/relationships`, `GET /supply-chain/organizations/{organization_id}/graph` |
| Disruptions and impact | `GET /supply-chain/organizations/{organization_id}/disruptions`, `GET /supply-chain/organizations/{organization_id}/disruptions/{event_id}`, `POST /supply-chain/organizations/{organization_id}/disruptions`, `GET /supply-chain/organizations/{organization_id}/impact`, `GET /supply-chain/organizations/{organization_id}/entities/{entity_id}/likelihood` |
| Evidence library | `GET /supply-chain/organizations/{organization_id}/evidence/{document_id}`; document IDs are discovered through relationships, events, history and evidence changes because the reviewed API does not expose a global document-list route |
| Alternative suppliers | `POST /organizations/{organization_id}/entities/{entity_id}/alternative-suppliers`, `GET /organizations/{organization_id}/alternative-supplier-recommendations` |
| Recurring scans and historical results | `GET /organizations/{organization_id}/scan-schedule`, `PUT /organizations/{organization_id}/scan-schedule`, `GET /organizations/{organization_id}/history`, `GET /organizations/{organization_id}/history/{snapshot_id}`, `GET /organizations/{organization_id}/evidence-changes` |

## Behavior notes

- Creating an organization creates the backend's initial investigation job record. If the worker is active, provider work may follow asynchronously.
- Queueing a manual investigation is explicit and includes a warning in the UI.
- The disruption likelihood index is labeled experimental and uncalibrated.
- Supplier matching is deterministic and does not certify a candidate as interchangeable or qualified.
- The frontend does not call Groq, OpenRouter, or any external model provider directly.

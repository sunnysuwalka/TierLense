"""Acceptance tests for the opt-in, synthetic PDS-4 presentation fixture."""

from types import SimpleNamespace

import pytest

from tierlense.services import organizations as organizations_service


DEMO_NAME = "PDS-4 Demo - Army Logistics Spares (SIMULATED)"


def _payload(name: str = DEMO_NAME) -> dict:
    return {
        "name": name,
        "website": "https://pds4-demo.invalid/",
        "country_code": "IN",
        "description": (
            "SIMULATED presentation fixture for an Army logistics-vehicle "
            "preventive-maintenance spares supply chain."
        ),
        "watch_profile": {
            "dependency_role": "equipment/spares ecosystem",
            "products_services": [
                "vehicle preventive maintenance spare kits",
                "air and oil filter assemblies",
                "filter media rolls",
                "gasket and O-ring sets",
            ],
            "dependency_context": (
                "Fictional demonstration only. Every supplier, relationship, "
                "ownership record, disruption and evidence passage is synthetic."
            ),
            "criticality": "high",
            "identity_clues": ["PDS-4 local demo fixture", "SIMULATED data only"],
        },
    }


def test_exact_opt_in_name_populates_pds4_demo_across_api(client, monkeypatch):
    monkeypatch.setattr(
        organizations_service,
        "get_settings",
        lambda: SimpleNamespace(enable_pds4_demo_scenario=True),
    )

    response = client.post("/api/v1/organizations", json=_payload())
    assert response.status_code == 201, response.text
    body = response.json()
    organization_id = body["organization"]["id"]
    job = body["initial_investigation"]
    assert job["status"] == "completed"
    assert job["result_summary"]["demo_scenario_id"] == "pds4_army_logistics_v1"
    assert job["result_summary"]["external_model_calls"] == 0
    assert "SIMULATED" in body["notice"]

    entities = client.get(
        f"/api/v1/supply-chain/organizations/{organization_id}/entities?limit=200"
    ).json()
    relationships = client.get(
        f"/api/v1/supply-chain/organizations/{organization_id}/relationships?limit=200"
    ).json()
    graph = client.get(
        f"/api/v1/supply-chain/organizations/{organization_id}/graph?direction=both&max_depth=4"
    ).json()
    disruptions = client.get(
        f"/api/v1/supply-chain/organizations/{organization_id}/disruptions?limit=100"
    ).json()
    history = client.get(f"/api/v1/organizations/{organization_id}/history?limit=10").json()
    changes = client.get(f"/api/v1/organizations/{organization_id}/evidence-changes").json()
    alternatives = client.get(
        f"/api/v1/organizations/{organization_id}/alternative-supplier-recommendations?limit=20"
    ).json()
    schedule = client.get(f"/api/v1/organizations/{organization_id}/scan-schedule").json()

    assert entities["total"] == 20
    assert relationships["total"] == 20
    assert len(graph["nodes"]) >= 15
    assert any("Western Polymer Feedstock" in node["entity"]["name"] for node in graph["nodes"])
    assert disruptions["total"] == 3
    assert history["total"] == 1
    assert len(changes) == 1
    assert alternatives["total"] == 2
    assert all(row["candidates"] for row in alternatives["items"])
    assert schedule["last_job_id"] == job["id"]
    assert "external_model_calls" in job["result_summary"]


def test_demo_is_not_triggered_when_feature_flag_is_off(client, monkeypatch):
    monkeypatch.setattr(
        organizations_service,
        "get_settings",
        lambda: SimpleNamespace(enable_pds4_demo_scenario=False),
    )

    response = client.post("/api/v1/organizations", json=_payload())
    assert response.status_code == 201, response.text
    body = response.json()
    organization_id = body["organization"]["id"]
    assert body["initial_investigation"]["status"] == "queued"
    relationships = client.get(
        f"/api/v1/supply-chain/organizations/{organization_id}/relationships?limit=200"
    ).json()
    disruptions = client.get(
        f"/api/v1/supply-chain/organizations/{organization_id}/disruptions?limit=100"
    ).json()
    assert relationships["total"] == 0
    assert disruptions["total"] == 0

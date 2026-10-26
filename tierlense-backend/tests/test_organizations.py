def _organization_payload(name="Arisun Creatives"):
    return {
        "name": name,
        "description": "Illustrative organization for API tests.",
        "watch_profile": {
            "dependency_role": "software_service_provider",
            "products_services": ["software solutions"],
            "dependency_context": "Organization we depend on for software services.",
            "criticality": "high",
            "identity_clues": [],
        },
    }


def test_onboard_creates_organization_profile_and_queued_job(client):
    response = client.post("/api/v1/organizations", json=_organization_payload())
    assert response.status_code == 201, response.text
    body = response.json()
    organization = body["organization"]
    job = body["initial_investigation"]

    assert organization["name"] == "Arisun Creatives"
    assert organization["identity_status"] == "unverified"
    assert organization["watch_profile"]["criticality"] == "high"
    assert organization["watch_profile"]["products_services"] == ["software solutions"]
    assert job["organization_id"] == organization["id"]
    assert job["job_type"] == "initial_scan"
    assert job["status"] == "queued"
    assert "queued" in body["notice"].lower()
    assert "background worker claims it" in body["notice"].lower()

    # Registration creates the recurring schedule in the same onboarding transaction.
    from sqlalchemy import select
    from tierlense.api.deps import get_db
    from tierlense.main import app
    from tierlense.models import InvestigationSchedule
    generator = app.dependency_overrides[get_db]()
    db = next(generator)
    try:
        from uuid import UUID
        schedule = db.scalar(select(InvestigationSchedule).where(
            InvestigationSchedule.organization_id == UUID(organization["id"])
        ))
        assert schedule is not None
        assert schedule.enabled is True
        assert schedule.interval_minutes == 1440
    finally:
        generator.close()

    retrieved = client.get(f"/api/v1/organizations/{organization['id']}")
    assert retrieved.status_code == 200
    assert retrieved.json()["name"] == "Arisun Creatives"

    listed_jobs = client.get("/api/v1/investigation-jobs?status=queued")
    assert listed_jobs.status_code == 200
    assert listed_jobs.json()["total"] == 1


def test_same_name_is_not_silently_merged(client):
    first = client.post("/api/v1/organizations", json=_organization_payload())
    second = client.post("/api/v1/organizations", json=_organization_payload())
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["organization"]["id"] != second.json()["organization"]["id"]
    assert first.json()["organization"]["identity_status"] == "unverified"
    assert second.json()["organization"]["identity_status"] == "unverified"


def test_list_search_and_patch_organization(client):
    created = client.post("/api/v1/organizations", json=_organization_payload()).json()
    org_id = created["organization"]["id"]

    searched = client.get("/api/v1/organizations?q=Arisun")
    assert searched.status_code == 200
    assert searched.json()["total"] == 1

    patched = client.patch(
        f"/api/v1/organizations/{org_id}",
        json={"country_code": "in", "description": "Updated description"},
    )
    assert patched.status_code == 200
    assert patched.json()["country_code"] == "IN"
    assert patched.json()["description"] == "Updated description"


def test_replace_watch_profile(client):
    created = client.post("/api/v1/organizations", json=_organization_payload()).json()
    org_id = created["organization"]["id"]
    response = client.put(
        f"/api/v1/organizations/{org_id}/watch-profile",
        json={
            "dependency_role": "critical_vendor",
            "products_services": ["identity management"],
            "dependency_context": "Updated dependency context",
            "criticality": "critical",
            "identity_clues": ["example.org"],
        },
    )
    assert response.status_code == 200
    assert response.json()["criticality"] == "critical"
    assert response.json()["identity_clues"] == ["example.org"]


def test_invalid_criticality_is_rejected(client):
    payload = _organization_payload()
    payload["watch_profile"]["criticality"] = "unlimited"
    response = client.post("/api/v1/organizations", json=payload)
    assert response.status_code == 422


def test_missing_organization_returns_404(client):
    response = client.get("/api/v1/organizations/00000000-0000-0000-0000-000000000001")
    assert response.status_code == 404

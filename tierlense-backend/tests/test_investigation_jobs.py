def test_queue_manual_investigation(client):
    created = client.post(
        "/api/v1/organizations",
        json={"name": "Example Supplier"},
    ).json()
    organization_id = created["organization"]["id"]

    response = client.post(
        f"/api/v1/organizations/{organization_id}/investigation-jobs",
        json={"job_type": "manual_scan"},
    )
    assert response.status_code == 201
    job = response.json()
    assert job["organization_id"] == organization_id
    assert job["job_type"] == "manual_scan"
    assert job["status"] == "queued"

    fetched = client.get(f"/api/v1/investigation-jobs/{job['id']}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == job["id"]


def test_scheduled_at_requires_timezone(client):
    created = client.post(
        "/api/v1/organizations",
        json={"name": "Example Supplier"},
    ).json()
    organization_id = created["organization"]["id"]
    response = client.post(
        f"/api/v1/organizations/{organization_id}/investigation-jobs",
        json={"job_type": "scheduled_scan", "scheduled_at": "2026-10-24T12:00:00"},
    )
    assert response.status_code == 422

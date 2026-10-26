"""Result APIs expose progress/source/finding lists without leaking content by default."""


def _payload():
    return {
        "name": "Results Test Organization",
        "watch_profile": {
            "dependency_role": "supplier",
            "products_services": ["test service"],
            "criticality": "medium",
            "identity_clues": [],
        },
    }


def test_pipeline_status_and_result_lists_work_for_new_job(client):
    created = client.post("/api/v1/organizations", json=_payload())
    assert created.status_code == 201
    job_id = created.json()["initial_investigation"]["id"]

    status_response = client.get(f"/api/v1/investigation-jobs/{job_id}/pipeline-status")
    sources_response = client.get(f"/api/v1/investigation-jobs/{job_id}/sources")
    findings_response = client.get(f"/api/v1/investigation-jobs/{job_id}/findings")

    assert status_response.status_code == 200
    assert status_response.json()["status"] == "queued"
    assert status_response.json()["progress_percent"] == 0
    assert sources_response.status_code == 200
    assert sources_response.json()["items"] == []
    assert findings_response.status_code == 200
    assert findings_response.json()["items"] == []


def test_result_apis_return_404_for_unknown_job(client):
    missing = "22222222-2222-4222-8222-222222222222"
    assert client.get(f"/api/v1/investigation-jobs/{missing}/sources").status_code == 404
    assert client.get(f"/api/v1/investigation-jobs/{missing}/findings").status_code == 404
    assert client.get(f"/api/v1/investigation-jobs/{missing}/pipeline-status").status_code == 404

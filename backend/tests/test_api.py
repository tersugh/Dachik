from fastapi.testclient import TestClient


def test_data_audit_api_workflow(client: TestClient) -> None:
    device = client.post(
        "/api/v1/devices",
        json={
            "hostname": "synthetic-api-mac.local",
            "display_name": "Synthetic API Mac",
            "operating_system": "macOS",
            "operating_system_version": "test",
        },
    )
    assert device.status_code == 201

    bundle = client.post(
        "/api/v1/bundles",
        json={
            "provider_name": "Synthetic ISP",
            "plan_name": "Synthetic API plan",
            "allowance_bytes": 30_000_000_000,
            "billing_cycle_start": "2026-08-01T00:00:00+01:00",
            "billing_cycle_end": "2026-09-01T00:00:00+01:00",
            "timezone": "Africa/Lagos",
        },
    )
    assert bundle.status_code == 201
    assert bundle.json()["allowance_bytes"] == 30_000_000_000

    experiment = client.post(
        "/api/v1/experiments",
        json={
            "data_bundle_id": bundle.json()["id"],
            "device_id": device.json()["id"],
            "measurement_boundary": "measured.interface",
            "methodology_version": "test-v1",
        },
    )
    assert experiment.status_code == 201
    experiment_id = experiment.json()["id"]

    started = client.post(f"/api/v1/experiments/{experiment_id}/start")
    assert started.status_code == 200
    assert started.json()["status"] == "active"
    assert client.post(f"/api/v1/experiments/{experiment_id}/start").status_code == 409

    snapshot = client.post(
        f"/api/v1/experiments/{experiment_id}/isp-snapshots",
        json={
            "timestamp_utc": "2026-08-02T10:00:00+01:00",
            "reported_value": "14.203",
            "reported_unit": "GB",
            "snapshot_type": "remaining_balance",
            "provenance": "manual",
        },
    )
    assert snapshot.status_code == 201
    assert snapshot.json()["reported_value"] == "14.203"
    assert snapshot.json()["normalized_bytes"] == 14_203_000_000

    audit = client.get(f"/api/v1/audits/{experiment_id}")
    json_export = client.get(f"/api/v1/audits/{experiment_id}/export.json")
    csv_export = client.get(f"/api/v1/audits/{experiment_id}/export.csv")
    pdf_export = client.get(f"/api/v1/audits/{experiment_id}/report.pdf")
    assert audit.status_code == json_export.status_code == 200
    assert audit.json()["total_observed_bytes"] == json_export.json()["total_observed_bytes"]
    assert str(audit.json()["total_observed_bytes"]) in csv_export.text
    assert pdf_export.status_code == 200
    assert pdf_export.content.startswith(b"%PDF")
    assert audit.json()["audit_status"] == "in_progress"

    history = client.get("/api/v1/experiments")
    detail = client.get(f"/api/v1/experiments/{experiment_id}")
    snapshots = client.get(f"/api/v1/experiments/{experiment_id}/isp-snapshots")
    assert history.status_code == detail.status_code == snapshots.status_code == 200
    assert history.json()[0]["id"] == experiment_id
    assert len(snapshots.json()) == 1

    completed = client.post(f"/api/v1/experiments/{experiment_id}/complete")
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"


def test_api_rejects_invalid_bundle_and_missing_relations(client: TestClient) -> None:
    invalid_bundle = client.post(
        "/api/v1/bundles",
        json={
            "provider_name": "Synthetic ISP",
            "plan_name": "Invalid plan",
            "allowance_bytes": -1,
            "billing_cycle_start": "2026-09-01T00:00:00Z",
            "billing_cycle_end": "2026-08-01T00:00:00Z",
            "timezone": "UTC",
        },
    )
    assert invalid_bundle.status_code == 422

    missing = client.post(
        "/api/v1/experiments",
        json={
            "data_bundle_id": "missing",
            "device_id": "missing",
            "methodology_version": "test-v1",
        },
    )
    assert missing.status_code == 404


def test_measurement_api_returns_unknown_instead_of_zero_without_observations(
    client: TestClient,
) -> None:
    device = client.post(
        "/api/v1/devices",
        json={
            "hostname": "measurement-api-mac",
            "display_name": "Measurement API Mac",
            "operating_system": "macOS",
            "operating_system_version": None,
        },
    ).json()
    bundle = client.post(
        "/api/v1/bundles",
        json={
            "provider_name": "Synthetic network",
            "plan_name": "Synthetic plan",
            "allowance_bytes": 30_000_000_000,
            "billing_cycle_start": "2026-08-01T00:00:00Z",
            "billing_cycle_end": "2026-09-01T00:00:00Z",
            "timezone": "UTC",
        },
    ).json()
    experiment = client.post(
        "/api/v1/experiments",
        json={
            "data_bundle_id": bundle["id"],
            "device_id": device["id"],
            "methodology_version": "test-v1",
        },
    ).json()
    client.post(f"/api/v1/experiments/{experiment['id']}/start")

    status = client.get("/api/v1/measurement/status")
    usage = client.get("/api/v1/usage/current-experiment")

    assert status.status_code == 200
    assert status.json()["status"] == "waiting"
    assert status.json()["service_installed"] is False
    assert status.json()["service_expected_to_run"] is False
    assert status.json()["collector_run_status"] is None
    assert usage.status_code == 200
    assert usage.json()["total_observed_bytes"] is None
    assert usage.json()["message"] == "Waiting for the first measurement."

import os

from fastapi.testclient import TestClient

from fasa_api.main import app


def _client(auth_required: bool = True, token: str = "test-token") -> TestClient:
    os.environ["FASA_REQUIRE_AUTH"] = "true" if auth_required else "false"
    os.environ["FASA_API_TOKEN"] = token
    return TestClient(app)


def test_health_is_public():
    client = _client(auth_required=True)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_supported_requires_auth():
    client = _client(auth_required=True)
    r = client.get("/supported")
    assert r.status_code == 401
    assert r.json()["detail"]["code"] == "unauthorized"


def test_supported_accepts_bearer_token():
    client = _client(auth_required=True, token="abc123")
    r = client.get("/supported", headers={"Authorization": "Bearer abc123"})
    assert r.status_code == 200
    body = r.json()
    assert "species" in body
    assert "production_systems" in body
    assert "stages_by_species_and_system" in body


def test_validate_recipe_rejects_invalid_fraction_range():
    client = _client(auth_required=True, token="abc123")
    payload = {"fractions": {"30355": 1.2}, "parameters": ["crude_protein_percent"]}
    r = client.post(
        "/validate-recipe",
        json=payload,
        headers={"Authorization": "Bearer abc123"},
    )
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_fraction"

import os

from fastapi.testclient import TestClient

from fasa_api.main import app
from tests.test_smoke import DEMO_PRICES


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


def test_supported_lists_countries():
    client = _client(auth_required=True, token="abc123")
    r = client.get("/supported", headers={"Authorization": "Bearer abc123"})
    assert r.status_code == 200
    assert r.json()["countries"] == ["KE", "NG", "ZM"]


def test_formulate_rejects_unsupported_country():
    client = _client(auth_required=True, token="abc123")
    payload = {
        "species": "Nile Tilapia",
        "stage": "< 5g (Starter)",
        "prices": {"30355": 0.30},
        "country": "US",
    }
    r = client.post(
        "/formulate",
        json=payload,
        headers={"Authorization": "Bearer abc123"},
    )
    # "US" is a well-formed ISO-2 string but not a supported country -> 422 from the
    # Literal on FormulateRequest (Pydantic validates before the endpoint guard runs).
    assert r.status_code == 422


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


def test_formulate_accepts_inclusion_limits():
    """Both limit layers travel through the HTTP surface and shape the response."""
    client = _client(auth_required=True, token="abc123")
    payload = {
        "species": "Nile Tilapia",
        "stage": "< 5g (Starter)",
        "prices": DEMO_PRICES,
        "nutrient_limits": {"PA05": {"max": 8.0}},
        "ingredient_limits": {"30355": {"max": 0.35}},
    }
    r = client.post("/formulate", json=payload, headers={"Authorization": "Bearer abc123"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in {"optimal", "infeasible"}
    for line in body["recipe"]:
        if line["code"] == "30355":
            assert line["max_inclusion_percent"] == 35.0
            assert line["inclusion_percent"] <= 35.0 + 1e-3
    # ASNS caps starter fibre at 7%, tighter than the 8% practice limit
    fibre = next(c for c in body["composition"] if c["code"] == "PA05")
    assert (fibre["target"], fibre["source"]) == (7.0, "asns")


def test_formulate_rejects_an_out_of_range_ingredient_limit():
    client = _client(auth_required=True, token="abc123")
    payload = {
        "species": "Nile Tilapia",
        "stage": "< 5g (Starter)",
        "prices": {"30355": 0.30},
        "ingredient_limits": {"30355": {"max": 1.5}},  # >100% of feed mass
    }
    r = client.post("/formulate", json=payload, headers={"Authorization": "Bearer abc123"})
    assert r.status_code == 422


def test_validate_recipe_keeps_the_original_payload_shape_working():
    """Backward compatibility: fractions + parameters alone still returns composition."""
    client = _client(auth_required=True, token="abc123")
    payload = {"fractions": {"30355": 0.5, "31237": 0.495},
               "parameters": ["crude_protein_percent"]}
    r = client.post("/validate-recipe", json=payload,
                    headers={"Authorization": "Bearer abc123"})
    assert r.status_code == 200
    body = r.json()
    assert set(body["composition"]) == {"crude_protein_percent"}
    assert body["nutrient_checks"] == []
    assert body["in_limits"] is True


def test_validate_recipe_checks_inclusion_rates():
    """Inclusion limits travel through the HTTP surface and flag a breach."""
    client = _client(auth_required=True, token="abc123")
    payload = {
        "fractions": {"31605": 0.40, "31621": 0.595},
        "parameters": [],
        "species": "Nile Tilapia",
        "stage": "< 5g (Starter)",
        "production_system": "General-LowCost",
        "ingredient_limits": {"31605": {"max": 0.15}},
    }
    r = client.post("/validate-recipe", json=payload,
                    headers={"Authorization": "Bearer abc123"})
    assert r.status_code == 200
    body = r.json()
    assert body["in_limits"] is False
    assert body["total_inclusion_percent"] == 99.5
    bran = next(c for c in body["inclusion_checks"] if c["code"] == "31605")
    assert (bran["max_inclusion_percent"], bran["in_limits"]) == (15.0, False)
    # full scope given, so the nutrient side was scored too
    assert body["nutrient_checks"]


def test_validate_recipe_rejects_an_unknown_stage():
    client = _client(auth_required=True, token="abc123")
    payload = {
        "fractions": {"30355": 0.995},
        "species": "Nile Tilapia",
        "stage": "not-a-stage",
        "production_system": "General",
    }
    r = client.post("/validate-recipe", json=payload,
                    headers={"Authorization": "Bearer abc123"})
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "invalid_request"

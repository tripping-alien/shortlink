import pytest
from fastapi.testclient import TestClient
from app import app, to_bijective_base6, from_bijective_base6

client = TestClient(app)

# --- Unit Tests for Core Logic ---

@pytest.mark.parametrize("decimal_input, expected_bijective", [
    (1, "1"),
    (6, "6"),
    (7, "11"),
    (43, "111"),
    (12, "16"),
    (216, "556"),
])
def test_to_bijective_base6(decimal_input, expected_bijective):
    """Tests the conversion from decimal to bijective base-6."""
    assert to_bijective_base6(decimal_input) == expected_bijective

@pytest.mark.parametrize("bijective_input, expected_decimal", [
    ("1", 1),
    ("6", 6),
    ("11", 7),
    ("111", 43),
    ("16", 12),
    ("556", 216),
])
def test_from_bijective_base6(bijective_input, expected_decimal):
    """Tests the conversion from bijective base-6 to decimal."""
    assert from_bijective_base6(bijective_input) == expected_decimal

def test_from_bijective_base6_invalid_char():
    """Tests that an invalid character raises a ValueError."""
    with pytest.raises(ValueError):
        from_bijective_base6("1A2")

# --- Integration Tests for API Endpoints ---

def test_convert_live_endpoint():
    """Tests the /convert endpoint for live conversions."""
    response = client.post("/convert", json={"decimal_value": 43})
    assert response.status_code == 200
    data = response.json()
    assert data["bijective_base6"] == "111"
    assert data["binary"] == "101011"

def test_calculate_all_endpoint():
    """Tests the /calculate-all endpoint for math operations."""
    response = client.post("/calculate-all", json={"num1": "13", "num2": "5"}) # 9 + 5
    assert response.status_code == 200
    data = response.json()
    assert data["results"]["addition"]["decimal"] == 14
    assert data["results"]["addition"]["bijective"] == "22"
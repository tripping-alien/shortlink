import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta, timezone
import os

# Add the project root to sys.path to resolve relative imports
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# We must monkeypatch the database path *before* importing the app
# This ensures that the app, upon import, uses our test database path.
import database
database.DB_FILE = ":memory:" # Use an in-memory SQLite database for tests

from app import app, to_bijective_base6, from_bijective_base6


@pytest.fixture(scope="function")
def client():
    """
    Pytest fixture to set up and tear down the database for each test function.
    This ensures that tests are isolated and don't interfere with each other.
    """
    # Setup: create a clean database before each test
    database.init_db()
    yield TestClient(app)
    # Teardown: The in-memory database is automatically discarded.


# ===================================
# 1. Core Logic Tests
# ===================================

def test_bijective_functions():
    """Tests the encoding and decoding functions for correctness."""
    test_cases = {
        1: '1',
        6: '6',
        7: '11',
        12: '16',
        37: '61',
        100: '244'
    }
    for num, code in test_cases.items():
        assert to_bijective_base6(num) == code
        assert from_bijective_base6(code) == num

def test_invalid_bijective_inputs():
    """Tests that the bijective functions raise errors for invalid inputs."""
    with pytest.raises(ValueError):
        to_bijective_base6(0)
    with pytest.raises(ValueError):
        from_bijective_base6("0") # '0' is not in the character set
    with pytest.raises(ValueError):
        from_bijective_base6("abc") # Invalid characters


# ===================================
# 2. API Endpoint Tests
# ===================================

def test_health_check(client: TestClient):
    """Tests the /health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200

def test_root_redirect(client: TestClient):
    """Tests that the root path redirects to a language-specific path."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307 # Temporary Redirect
    assert response.headers["location"] == "/en"

def test_ui_rendering(client: TestClient):
    """Tests that the main UI page renders correctly."""
    response = client.get("/en")
    assert response.status_code == 200
    assert "Bijective-Shorty" in response.text

def test_create_link_success(client: TestClient):
    """Tests successful link creation."""
    response = client.post(
        "/api/links",
        json={
            "long_url": "https://example.com/a-very-long-url",
            "ttl": "1d",
            "challenge": {"num1": 5, "num2": 5, "challenge_answer": 10}
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["short_url"].endswith("/1")
    assert data["long_url"] == "https://example.com/a-very-long-url"
    assert "expires_at" in data

def test_create_link_bad_challenge(client: TestClient):
    """Tests that link creation fails with an incorrect bot challenge answer."""
    response = client.post(
        "/api/links",
        json={
            "long_url": "https://example.com",
            "ttl": "1d",
            "challenge": {"num1": 5, "num2": 5, "challenge_answer": 9} # Incorrect
        }
    )
    assert response.status_code == 400
    assert "Bot verification failed" in response.json()["detail"]

def test_create_link_missing_scheme(client: TestClient):
    """Tests that the server correctly prepends https:// to URLs without a scheme."""
    response = client.post(
        "/api/links",
        json={
            "long_url": "google.com", # No scheme
            "ttl": "1d",
            "challenge": {"num1": 2, "num2": 3, "challenge_answer": 5}
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["long_url"] == "https://google.com/"

def test_redirect_to_long_url(client: TestClient):
    """Tests that a valid short code correctly redirects."""
    # First, create a link
    client.post(
        "/api/links",
        json={
            "long_url": "https://redirect-target.com",
            "ttl": "1h",
            "challenge": {"num1": 1, "num2": 1, "challenge_answer": 2}
        }
    )
    # Now, test the redirect
    response = client.get("/1", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "https://redirect-target.com"

def test_redirect_not_found(client: TestClient):
    """Tests that a non-existent short code returns a 404."""
    response = client.get("/999", follow_redirects=False)
    assert response.status_code == 404

def test_get_link_details(client: TestClient):
    """Tests the endpoint for retrieving link details."""
    # Create a link
    create_response = client.post(
        "/api/links",
        json={
            "long_url": "https://details-test.com",
            "ttl": "1w",
            "challenge": {"num1": 3, "num2": 4, "challenge_answer": 7}
        }
    )
    short_code = create_response.json()["short_url"].split("/")[-1]

    # Retrieve its details
    details_response = client.get(f"/api/links/{short_code}")
    assert details_response.status_code == 200
    data = details_response.json()
    assert data["long_url"] == "https://details-test.com/"
    assert data["short_url"].endswith(f"/{short_code}")
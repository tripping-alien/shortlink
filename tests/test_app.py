import os
import sys
import time
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

# Add the project root to sys.path to resolve module imports correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# We import the app and its components here, but the fixture will ensure
# it runs with a temporary database for each test.
from app import app, to_bijective_base6, from_bijective_base6, TTL


@pytest.fixture
def client(tmp_path, monkeypatch):
    """
    Pytest fixture to provide a test client with an isolated, temporary database.
    This is the standard, robust way to test FastAPI applications with file-based persistence.
    """
    # 1. Create a temporary database file path for this specific test run.
    test_db_path = tmp_path / "test_db.json"

    # 2. Use monkeypatch to override the `settings.db_file` for the duration of the test.
    #    This ensures that the app's lifespan manager uses our temporary file.
    monkeypatch.setattr("database.DB_FILE", str(test_db_path))

    # 3. Use the TestClient as a context manager. This correctly handles
    #    the application's lifespan events (startup and shutdown).
    with TestClient(app) as test_client:
        yield test_client

    # 4. Teardown is handled automatically by pytest's tmp_path and the context manager.


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
        from_bijective_base6("0")  # '0' is not in the character set
    with pytest.raises(ValueError):
        from_bijective_base6("abc")  # Invalid characters


# ===================================
# 2. API Endpoint Tests
# ===================================

def test_health_check(client: TestClient):
    """Tests the /health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200


def test_ui_rendering(client: TestClient):
    """Tests that the main UI page renders correctly."""
    response = client.get("/en")
    assert response.status_code == 200
    assert "Bijective-Shorty" in response.text


def test_create_link_success(client: TestClient):
    """Tests successful link creation."""
    response = client.post(
        "/links",
        json={
            "long_url": "https://example.com/a-very-long-url",
            "ttl": "1d",
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["short_url"].endswith("/1")
    assert data["long_url"] == "https://example.com/a-very-long-url/"


def test_create_link_invalid_url(client: TestClient):
    """Tests that link creation fails with an invalid URL."""
    response = client.post(
        "/links",
        json={"long_url": "not-a-valid-url", "ttl": "1d"}
    )
    assert response.status_code == 422  # Unprocessable Entity


def test_redirect_to_long_url(client: TestClient):
    """Tests that a valid short code correctly redirects."""
    # First, create a link
    create_response = client.post(
        "/links",
        json={"long_url": "https://redirect-target.com", "ttl": "1h"}
    )
    assert create_response.status_code == 201

    # Now, test the redirect
    response = client.get("/1", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "https://redirect-target.com/"


def test_link_expiration(client: TestClient, monkeypatch):
    """Tests that a link expires correctly."""
    # Monkeypatch the TTL_MAP for this test to create a very short-lived link
    monkeypatch.setitem("app.TTL_MAP", TTL.ONE_HOUR, timedelta(seconds=1))

    # Create a link with a 1-second TTL
    client.post(
        "/links",
        json={"long_url": "https://expiring-link.com", "ttl": "1h"}
    )

    # Immediately, it should work
    response = client.get("/1", follow_redirects=False)
    assert response.status_code == 307

    # Wait for more than 1 second
    time.sleep(1.5)

    # Now, it should be expired and return a 404
    response_after_expiry = client.get("/1", follow_redirects=False)
    assert response_after_expiry.status_code == 404
    assert "has expired" in response_after_expiry.json()["detail"]
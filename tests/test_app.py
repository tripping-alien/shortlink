import pytest
import respx
from fastapi.testclient import TestClient
from unittest.mock import patch
import os
import sys
import time

# Add the project root to sys.path to resolve module imports correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Use a file-based SQLite DB for tests to allow shared connections.
TEST_DB_FILE = "./test.db"


@pytest.fixture(scope="function")
def client():
    """
    Pytest fixture to provide a test client with an isolated, file-based database.
    This fixture ensures a clean state for every test.
    """
    # 1. Clean up any previous test database file.
    if os.path.exists(TEST_DB_FILE):
        os.remove(TEST_DB_FILE)

    # 2. Use a patch to force the 'database' module to use our test DB path.
    #    This is done *before* importing the app to ensure the app initializes
    #    with the correct database path.
    with patch('database.DB_FILE', TEST_DB_FILE):
        # Import the app object *inside* the fixture to ensure it's fresh
        # for each test and uses the patched DB_FILE.
        from app import app

        # 3. Yield the test client to the test function.
        with TestClient(app) as test_client:
            yield test_client

    # 4. Clean up the test database file after the test has run.
    if os.path.exists(TEST_DB_FILE):
        os.remove(TEST_DB_FILE)


# ===================================
# 1. Core Logic Tests
# ===================================

# These tests don't need the client fixture as they test pure functions.
from mymath import to_bijective_base6, from_bijective_base6


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


def test_root_redirect(client: TestClient):
    """Tests that the root path redirects to a language-specific path."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307  # Temporary Redirect
    assert response.headers["location"] == "/en"


def test_ui_rendering(client: TestClient):
    """Tests that the main UI page renders correctly."""
    response = client.get("/en")
    assert response.status_code == 200
    assert "Bijective-Shorty" in response.text


@respx.mock
def test_create_link_success(client: TestClient):
    """Tests successful link creation with a mocked successful reCAPTCHA response."""
    # Mock the external call to Google's reCAPTCHA service
    respx.post("https://www.google.com/recaptcha/api/siteverify").respond(200, json={"success": True})

    response = client.post(
        "/api/links",
        data={
            "long_url": "https://example.com/a-very-long-url",
            "ttl": "1d",
            "g-recaptcha-response": "mock-token"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert data["short_url"].endswith("/1")
    assert data["long_url"] == "https://example.com/a-very-long-url/"


@respx.mock
def test_create_link_recaptcha_failure(client: TestClient):
    """Tests that link creation fails with a mocked failed reCAPTCHA response."""
    respx.post("https://www.google.com/recaptcha/api/siteverify").respond(200, json={"success": False})

    response = client.post(
        "/api/links",
        data={
            "long_url": "https://example.com",
            "ttl": "1d",
            "g-recaptcha-response": "mock-token-fail"
        }
    )
    assert response.status_code == 400
    assert "Bot verification failed" in response.json()["detail"]


@respx.mock
def test_redirect_to_long_url(client: TestClient):
    """Tests that a valid short code correctly redirects."""
    respx.post("https://www.google.com/recaptcha/api/siteverify").respond(200, json={"success": True})

    # First, create a link
    client.post(
        "/api/links",
        data={"long_url": "https://redirect-target.com", "ttl": "1h", "g-recaptcha-response": "mock-token"}
    )
    # Now, test the redirect
    response = client.get("/1", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "https://redirect-target.com/"


def test_redirect_not_found(client: TestClient):
    """Tests that a non-existent short code returns a 404."""
    response = client.get("/999", follow_redirects=False)
    assert response.status_code == 404


@respx.mock
def test_link_expiration(client: TestClient):
    """Tests that a link expires correctly."""
    respx.post("https://www.google.com/recaptcha/api/siteverify").respond(200, json={"success": True})

    # Monkeypatch the TTL_MAP for this test to create a very short-lived link
    with patch("app.TTL_MAP", {app.TTL.ONE_HOUR: timedelta(seconds=1)}):
        # Create a link with a 1-second TTL
        client.post(
            "/api/links",
            data={"long_url": "https://expiring-link.com", "ttl": "1h", "g-recaptcha-response": "mock-token"}
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
import os
import sys
import json

import pytest
from fastapi.testclient import TestClient

# Add the project root to sys.path to resolve module imports correctly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

# Import the FastAPI app and other necessary components
from app import app
from encoding import encode_id, decode_id


@pytest.fixture
def client(tmp_path, monkeypatch):
    """
    Pytest fixture to provide a test client with an isolated, temporary database.
    This is the standard, robust way to test FastAPI applications with file-based persistence.
    """
    # Create a temporary database file path for this specific test run.
    test_db_path = tmp_path / "test_shortlinks.db"

    # Use monkeypatch to override the database file path used by the app.
    monkeypatch.setattr("database.DB_FILE", str(test_db_path))

    # 3. Use the TestClient as a context manager. This correctly handles
    #    the application's lifespan events (startup and shutdown).
    with TestClient(app) as test_client:
        yield test_client

    # Teardown: The temporary directory and its contents are automatically removed by pytest.
    if os.path.exists(test_db_path):
        os.remove(test_db_path)


# ===================================
# 1. Core Logic Tests
# ===================================

def test_encoding_decoding_roundtrip():
    """Tests that encoding and decoding functions are reversible."""
    test_cases = [1, 6, 7, 12, 37, 100, 12345]
    for num in test_cases:
        encoded = encode_id(num)
        assert isinstance(encoded, str)
        assert len(encoded) > 0
        decoded = decode_id(encoded)
        assert decoded == num


def test_invalid_decoding():
    """Tests that decoding invalid strings returns None."""
    assert decode_id("0") is None
    assert decode_id("not-a-valid-id") is None
    assert decode_id("") is None


# ===================================
# 2. API Endpoint Tests
# ===================================

def test_health_check_ok(client: TestClient):
    """Tests that the /health endpoint returns a 200 OK status when all services are healthy."""
    response = client.get("/health")
    assert response.status_code == 200
    assert 'Overall Status: <span class="ok">OK</span>' in response.text


def test_root_redirect(client: TestClient):
    """Tests that the root path '/' correctly redirects to the default language UI."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307  # Temporary Redirect
    assert response.headers["location"] == "/ui/en"


def test_ui_rendering_for_language(client: TestClient):
    """Tests that a language-specific UI page renders correctly."""
    response = client.get("/ui/de")  # Test with German
    assert response.status_code == 200
    assert "Bijective-Shorty" in response.text
    # Check for a piece of German text to confirm the correct translation was loaded
    assert "Link-Kürzer" in response.text


def test_create_link_success(client: TestClient):
    """Tests successful link creation."""
    response = client.post(
        "/api/v1/links",
        json={
            "long_url": "https://example.com/a-very-long-url",
            "ttl": "1d"
        }
    )
    assert response.status_code == 201
    data = response.json()
    assert "short_url" in data
    assert "deletion_token" in data
    assert data["long_url"] == "https://example.com/a-very-long-url"
    assert data["expires_at"] is not None


def test_create_link_invalid_url(client: TestClient):
    """Tests that link creation fails with an invalid URL."""
    response = client.post(
        "/api/v1/links",
        json={
            "long_url": "not-a-valid-url",
            "ttl": "1d"
        }
    )
    assert response.status_code == 422  # Unprocessable Entity


def test_create_link_invalid_ttl(client: TestClient):
    """Tests that link creation fails with an invalid TTL value."""
    response = client.post(
        "/api/v1/links",
        json={
            "long_url": "https://example.com",
            "ttl": "invalid-ttl"
        }
    )
    assert response.status_code == 422


def test_redirect_to_long_url(client: TestClient):
    """Tests that a valid short code correctly redirects."""
    # First, create a link
    create_response = client.post(
        "/api/v1/links",
        json={
            "long_url": "https://redirect-target.com",
            "ttl": "1h"
        }
    )
    assert create_response.status_code == 201
    data = create_response.json()
    short_code = data['short_url'].split('/')[-1]

    # Now, test the redirect
    response = client.get(f"/{short_code}", follow_redirects=False)
    assert response.status_code == 307  # Temporary Redirect
    assert response.headers["location"] == "https://redirect-target.com/"


def test_redirect_non_existent_link(client: TestClient):
    """Tests that redirecting a non-existent short code returns a 404."""
    response = client.get("/nonexistent", follow_redirects=False)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_get_link_details(client: TestClient):
    """Tests retrieving the details of a specific link."""
    create_response = client.post(
        "/api/v1/links",
        json={
            "long_url": "https://details-test.com",
            "ttl": "1w"
        }
    )
    assert create_response.status_code == 201
    data = create_response.json()
    short_code = data['short_url'].split('/')[-1]

    # Fetch the details
    details_response = client.get(f"/api/v1/links/{short_code}")
    assert details_response.status_code == 200
    details_data = details_response.json()
    assert details_data["long_url"] == "https://details-test.com/"
    assert details_data["short_url"] == data["short_url"]


def test_get_details_for_non_existent_link(client: TestClient):
    """Tests that fetching details for a non-existent link returns a 404."""
    response = client.get("/api/v1/links/nonexistent")
    assert response.status_code == 404


def test_delete_link_success(client: TestClient):
    """Tests that a link can be successfully deleted with the correct token."""
    # 1. Create a link to get a short_code and a deletion_token
    create_response = client.post(
        "/api/v1/links",
        json={"long_url": "https://to-be-deleted.com", "ttl": "1h"}
    )
    assert create_response.status_code == 201
    data = create_response.json()
    short_code = data['short_url'].split('/')[-1]
    deletion_token = data['deletion_token']

    # 2. Delete the link using the correct token
    delete_response = client.request(
        "DELETE",
        f"/api/v1/links/{short_code}",
        json={"deletion_token": deletion_token}
    )
    assert delete_response.status_code == 204  # No Content

    # 3. Verify the link is actually gone
    get_response = client.get(f"/{short_code}", follow_redirects=False)
    assert get_response.status_code == 404


def test_delete_link_wrong_token(client: TestClient):
    """Tests that a link cannot be deleted with an incorrect token."""
    # 1. Create a link
    create_response = client.post(
        "/api/v1/links",
        json={"long_url": "https://protected-link.com", "ttl": "1h"}
    )
    assert create_response.status_code == 201
    data = create_response.json()
    short_code = data['short_url'].split('/')[-1]

    # 2. Attempt to delete with a wrong token
    delete_response = client.request(
        "DELETE",
        f"/api/v1/links/{short_code}",
        json={"deletion_token": "this-is-the-wrong-token"}
    )
    assert delete_response.status_code == 404  # Not Found, as the combo of ID and token doesn't match

    # 3. Verify the link still exists
    get_response = client.get(f"/{short_code}", follow_redirects=False)
    assert get_response.status_code == 307


def test_delete_link_missing_token(client: TestClient):
    """Tests that the delete endpoint requires a token."""
    create_response = client.post(
        "/api/v1/links",
        json={"long_url": "https://another-link.com", "ttl": "1h"}
    )
    short_code = create_response.json()['short_url'].split('/')[-1]

    # Attempt to delete with no token in the body
    delete_response = client.request(
        "DELETE",
        f"/api/v1/links/{short_code}",
        json={}
    )
    assert delete_response.status_code == 400  # Bad Request

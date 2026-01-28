"""Tests for upload endpoint."""
import base64
import json
from io import BytesIO

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def create_identity_header(account_number="12345", org_id="67890"):
    """Helper to create x-rh-identity header."""
    identity_data = {
        "identity": {
            "account_number": account_number,
            "org_id": org_id,
            "type": "User"
        }
    }
    identity_json = json.dumps(identity_data)
    return base64.b64encode(identity_json.encode()).decode()


def test_health_endpoint():
    """Test health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_root_endpoint():
    """Test root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "insights-on-premise"
    assert data["status"] == "running"


def test_upload_missing_identity_header():
    """Test upload without x-rh-identity header."""
    files = {"file": ("test.tar.gz", BytesIO(b"test data"), "application/gzip")}
    response = client.post("/api/ingress/v1/upload", files=files)

    assert response.status_code == 422  # Validation error


def test_upload_invalid_file_format():
    """Test upload with invalid file format."""
    identity = create_identity_header()
    files = {"file": ("test.txt", BytesIO(b"test data"), "text/plain")}

    response = client.post(
        "/api/ingress/v1/upload",
        files=files,
        headers={"x-rh-identity": identity}
    )

    assert response.status_code == 400
    assert "tar.gz" in response.json()["detail"].lower()


def test_upload_no_filename():
    """Test upload without filename."""
    identity = create_identity_header()
    files = {"file": ("", BytesIO(b"test data"), "application/gzip")}

    response = client.post(
        "/api/ingress/v1/upload",
        files=files,
        headers={"x-rh-identity": identity}
    )

    assert response.status_code == 400

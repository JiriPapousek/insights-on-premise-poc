"""Tests for new API endpoints (clusters/reports and content)."""
import base64
import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import get_db
from app.models import Report, RuleHit, RuleContent


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def valid_identity_header():
    """Generate valid x-rh-identity header."""
    identity = {
        "identity": {
            "account_number": "12345",
            "org_id": "67890",
            "type": "User",
        }
    }
    encoded = base64.b64encode(json.dumps(identity).encode()).decode()
    return {"x-rh-identity": encoded}


@pytest.fixture
def db_session():
    """Get database session for tests."""
    db = next(get_db())
    yield db
    db.close()


def test_clusters_reports_endpoint_no_auth(client):
    """Test clusters/reports endpoint without authentication."""
    response = client.post(
        "/api/v1/organizations/67890/clusters/reports",
        json={"clusters": ["test-cluster-1"]},
    )
    assert response.status_code == 422  # Missing x-rh-identity header


def test_clusters_reports_endpoint_org_mismatch(client, valid_identity_header):
    """Test clusters/reports endpoint with org ID mismatch."""
    response = client.post(
        "/api/v1/organizations/99999/clusters/reports",
        headers=valid_identity_header,
        json={"clusters": ["test-cluster-1"]},
    )
    assert response.status_code == 401
    assert "does not match" in response.json()["detail"]


def test_clusters_reports_endpoint_empty_results(client, valid_identity_header):
    """Test clusters/reports endpoint with no data."""
    response = client.post(
        "/api/v1/organizations/67890/clusters/reports",
        headers=valid_identity_header,
        json={"clusters": ["non-existent-cluster"]},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["clusters"] == {}


def test_clusters_reports_endpoint_with_data(client, valid_identity_header, db_session):
    """Test clusters/reports endpoint with actual data."""
    # Create test data
    org_id = 67890
    cluster_id = "test-cluster-123"

    # Insert a report
    report_data = {"analysis": "test", "findings": []}
    Report.upsert(
        db_session,
        org_id=org_id,
        cluster=cluster_id,
        report=json.dumps(report_data),
        gathered_at=datetime.utcnow(),
    )

    # Insert rule content (normalized table)
    RuleContent.upsert(
        db_session,
        rule_fqdn="test.rule.check",
        error_key="TEST_ERROR",
        description="Test rule",
        impact=2,
    )

    # Insert a rule hit (references rule content)
    RuleHit.upsert(
        db_session,
        org_id=org_id,
        cluster_id=cluster_id,
        rule_fqdn="test.rule.check",
        error_key="TEST_ERROR",
    )

    # Query the endpoint
    response = client.post(
        "/api/v1/organizations/67890/clusters/reports",
        headers=valid_identity_header,
        json={"clusters": [cluster_id]},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert cluster_id in data["clusters"]

    cluster_data = data["clusters"][cluster_id]
    assert cluster_data["cluster_id"] == cluster_id
    assert cluster_data["org_id"] == org_id
    assert cluster_data["report"] == report_data
    assert len(cluster_data["rule_hits"]) == 1

    rule_hit = cluster_data["rule_hits"][0]
    assert rule_hit["rule_fqdn"] == "test.rule.check"
    assert rule_hit["error_key"] == "TEST_ERROR"
    assert rule_hit["template_data"]["description"] == "Test rule"
    assert rule_hit["template_data"]["impact"] == 2


def test_content_endpoint(client):
    """Test content endpoint."""
    response = client.get("/api/v1/content")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "content" in data
    assert isinstance(data["content"], list)


def test_content_endpoint_with_data(client, db_session):
    """Test content endpoint with actual rule data."""
    # Create test rule content directly in the normalized table
    RuleContent.upsert(
        db_session,
        rule_fqdn="security.vulnerability.check",
        error_key="CVE_DETECTED",
        description="Critical security issue",
        reason="Vulnerability detected",
        resolution="Update immediately",
        total_risk=4,
        likelihood=3,
        impact=4,
        tags=json.dumps(["security", "critical"]),
    )

    # Query the endpoint
    response = client.get("/api/v1/content")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert len(data["content"]) > 0

    # Find our rule in the content
    rule_found = False
    for rule in data["content"]:
        if rule["rule_fqdn"] == "security.vulnerability.check":
            rule_found = True
            assert rule["error_key"] == "CVE_DETECTED"
            assert rule["description"] == "Critical security issue"
            assert rule["total_risk"] == 4
            assert rule["likelihood"] == 3
            assert rule["impact"] == 4
            assert "security" in rule["tags"]
            break

    assert rule_found, "Test rule not found in content response"

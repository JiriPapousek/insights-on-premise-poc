"""Tests for authentication module."""
import base64
import json
import pytest

from app.auth import decode_identity_header, AuthenticationError


def test_decode_valid_identity_header():
    """Test decoding a valid x-rh-identity header."""
    identity_data = {
        "identity": {
            "account_number": "12345",
            "org_id": "67890",
            "type": "User"
        }
    }

    # Encode identity
    identity_json = json.dumps(identity_data)
    encoded = base64.b64encode(identity_json.encode()).decode()

    # Decode and validate
    result = decode_identity_header(encoded)

    assert result.identity.account_number == "12345"
    assert result.identity.org_id == "67890"
    assert result.identity.type == "User"


def test_decode_missing_header():
    """Test that missing header raises error."""
    with pytest.raises(AuthenticationError, match="Missing x-rh-identity header"):
        decode_identity_header("")


def test_decode_invalid_base64():
    """Test that invalid base64 raises error."""
    with pytest.raises(AuthenticationError, match="Invalid base64 encoding"):
        decode_identity_header("not-valid-base64!!!")


def test_decode_invalid_json():
    """Test that invalid JSON raises error."""
    invalid_json = base64.b64encode(b"not valid json").decode()

    with pytest.raises(AuthenticationError, match="Invalid JSON"):
        decode_identity_header(invalid_json)


def test_decode_invalid_structure():
    """Test that invalid structure raises error."""
    invalid_data = {"wrong": "structure"}
    encoded = base64.b64encode(json.dumps(invalid_data).encode()).decode()

    with pytest.raises(AuthenticationError):
        decode_identity_header(encoded)

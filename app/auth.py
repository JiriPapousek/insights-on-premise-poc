"""Authentication module for x-rh-identity header handling."""
import base64
import json
import logging
from typing import Tuple
from fastapi import HTTPException, Header

from app.schemas import IdentityHeader

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails."""

    pass


def decode_identity_header(x_rh_identity: str) -> IdentityHeader:
    """
    Decode and parse x-rh-identity header.

    Args:
        x_rh_identity: Base64-encoded identity header value

    Returns:
        Parsed IdentityHeader object

    Raises:
        AuthenticationError: If header is invalid or malformed
    """
    if not x_rh_identity:
        raise AuthenticationError("Missing x-rh-identity header")

    try:
        # Decode base64
        decoded_bytes = base64.b64decode(x_rh_identity)
        decoded_str = decoded_bytes.decode("utf-8")

        # Parse JSON
        identity_dict = json.loads(decoded_str)

        # Validate with Pydantic
        identity = IdentityHeader(**identity_dict)

        return identity

    except base64.binascii.Error as e:
        logger.error(f"Failed to decode base64 identity header: {e}")
        raise AuthenticationError("Invalid base64 encoding in x-rh-identity header")

    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse identity JSON: {e}")
        raise AuthenticationError("Invalid JSON in x-rh-identity header")

    except Exception as e:
        logger.error(f"Failed to validate identity header: {e}")
        raise AuthenticationError(f"Invalid identity header format: {str(e)}")


def get_identity(
    x_rh_identity: str = Header(..., alias="x-rh-identity")
) -> Tuple[int, str]:
    """
    FastAPI dependency to extract org_id and account_number from header.

    Args:
        x_rh_identity: The x-rh-identity header value

    Returns:
        Tuple of (org_id as int, account_number as str)

    Raises:
        HTTPException: If authentication fails
    """
    try:
        identity = decode_identity_header(x_rh_identity)
        org_id = int(identity.identity.org_id)
        account_number = identity.identity.account_number

        logger.debug(f"Authenticated request for org_id={org_id}, account={account_number}")

        return org_id, account_number

    except AuthenticationError as e:
        logger.warning(f"Authentication failed: {e}")
        raise HTTPException(status_code=401, detail=str(e))

    except ValueError as e:
        logger.error(f"Invalid org_id format: {e}")
        raise HTTPException(status_code=401, detail="Invalid org_id format")

"""Pydantic schemas for API request/response validation."""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class IdentityPayload(BaseModel):
    """Schema for x-rh-identity header payload."""

    account_number: str
    org_id: str
    type: str = "User"


class IdentityHeader(BaseModel):
    """Schema for decoded x-rh-identity header."""

    identity: IdentityPayload


class UploadResponse(BaseModel):
    """Response schema for successful upload."""

    request_id: str = Field(..., description="Unique request identifier")
    status: str = Field(..., description="Processing status")
    cluster_id: str = Field(..., description="Cluster identifier from archive")
    rules_found: int = Field(..., description="Number of rules violations found")
    uploaded_at: datetime = Field(..., description="Upload timestamp")


class ErrorResponse(BaseModel):
    """Response schema for errors."""

    error: str = Field(..., description="Error message")
    request_id: Optional[str] = Field(None, description="Request ID if available")
    detail: Optional[str] = Field(None, description="Additional error details")


# Schemas for clusters/reports endpoint
class ClustersRequest(BaseModel):
    """Request schema for retrieving reports for multiple clusters."""

    clusters: List[str] = Field(..., description="List of cluster UUIDs")


class RuleHitResponse(BaseModel):
    """Schema for individual rule hit in cluster report."""

    rule_fqdn: str = Field(..., description="Fully qualified rule name")
    error_key: str = Field(..., description="Error key for the rule")
    template_data: Dict[str, Any] = Field(..., description="Template data for the rule")
    updated_at: datetime = Field(..., description="Last update timestamp")


class ClusterReport(BaseModel):
    """Schema for cluster report data."""

    cluster_id: str = Field(..., description="Cluster identifier")
    org_id: int = Field(..., description="Organization ID")
    report: Dict[str, Any] = Field(..., description="Full report JSON data")
    reported_at: Optional[datetime] = Field(None, description="First report timestamp")
    last_checked_at: Optional[datetime] = Field(None, description="Last check timestamp")
    gathered_at: Optional[datetime] = Field(None, description="Data collection timestamp")
    rule_hits: List[RuleHitResponse] = Field(default_factory=list, description="List of rule violations")


class ClustersReportResponse(BaseModel):
    """Response schema for clusters reports endpoint."""

    status: str = Field(default="ok", description="Response status")
    clusters: Dict[str, ClusterReport] = Field(..., description="Map of cluster_id to report data")


# Schemas for content endpoint (matching insights-content-service format)
class ErrorKeyMetadata(BaseModel):
    """Metadata for an error key."""

    description: str = Field(..., description="Error description")
    impact: str = Field(..., description="Impact level or description")
    likelihood: int = Field(..., description="Likelihood of occurrence (1-4)")
    publish_date: str = Field(..., description="Publication date")
    status: str = Field(..., description="Rule status (active, inactive)")
    tags: List[str] = Field(default_factory=list, description="Rule tags")


class ErrorKeyContent(BaseModel):
    """Content for a specific error key."""

    metadata: ErrorKeyMetadata = Field(..., description="Error key metadata")
    total_risk: int = Field(..., description="Total risk level (1-4)")
    generic: str = Field(default="", description="Generic information")
    summary: str = Field(default="", description="Summary")
    resolution: str = Field(default="", description="Resolution steps")
    more_info: str = Field(default="", description="Additional information URL")
    reason: str = Field(default="", description="Reason for the rule")
    HasReason: bool = Field(default=False, description="Whether reason field is present")


class PluginInfo(BaseModel):
    """Plugin information."""

    name: str = Field(default="", description="Plugin name")
    node_id: str = Field(default="", description="Node ID")
    product_code: str = Field(default="", description="Product code")
    python_module: str = Field(..., description="Python module path")


class ContentRule(BaseModel):
    """Schema for rule content (matching insights-content-service format)."""

    plugin: PluginInfo = Field(..., description="Plugin information")
    error_keys: Dict[str, ErrorKeyContent] = Field(..., description="Map of error keys to content")
    generic: str = Field(default="", description="Generic information (top-level)")
    summary: str = Field(default="", description="Summary (top-level)")
    resolution: str = Field(default="", description="Resolution (top-level)")
    more_info: str = Field(default="", description="More info (top-level)")
    reason: str = Field(default="", description="Reason (top-level)")
    HasReason: bool = Field(default=False, description="Whether reason field is present")


class ContentResponse(BaseModel):
    """Response schema for content endpoint."""

    status: str = Field(default="ok", description="Response status")
    content: List[ContentRule] = Field(..., description="List of rule content metadata")

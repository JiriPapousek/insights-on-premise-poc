"""FastAPI application for Insights On Premise."""
import json
import logging
import os
import tempfile
import uuid
from datetime import datetime
from typing import Tuple, Dict

from fastapi import FastAPI, File, UploadFile, Depends, HTTPException, Header
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.auth import get_identity
from app.config import get_settings
from app.database import get_db, init_db
from app.models import Report, RuleHit
from app.processor import ArchiveProcessor, ProcessingError
from app.schemas import (
    UploadResponse,
    ErrorResponse,
    ClustersReportResponse,
    ClusterReport,
    RuleHitResponse,
    ContentResponse,
    ContentRule,
)
from app.content_service import get_content_service

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()

# Create FastAPI app
app = FastAPI(
    title="Insights On-Premise",
    description="Red Hat Insights archive processing for on-premise deployment",
    version="1.0.0",
)


@app.on_event("startup")
async def startup_event():
    """Initialize application on startup."""
    logger.info("Starting Insights On-Premise application")

    # Ensure temp upload directory exists
    os.makedirs(settings.temp_upload_dir, exist_ok=True)
    logger.info(f"Temp upload directory: {settings.temp_upload_dir}")

    # Initialize database
    try:
        init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

    # Initialize content service (loads YAML/markdown files into memory, like content-service)
    try:
        content_service = get_content_service()
        logger.info("Content service initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize content service: {e}", exc_info=True)


@app.get("/")
async def root():
    """Root endpoint for health check."""
    return {
        "service": "insights-on-premise",
        "status": "running",
        "version": "1.0.0",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.post(
    f"{settings.api_prefix}/upload",
    response_model=UploadResponse,
    status_code=202,
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request"},
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)
async def upload_archive(
    upload: UploadFile = File(...),
    identity: Tuple[int, str] = Depends(get_identity),
    db: Session = Depends(get_db),
    x_rh_insights_request_id: str = Header(None, alias="x-rh-insights-request-id"),
):
    """
    Upload and process Red Hat Insights archive.

    Args:
        upload: Uploaded archive file (tar, tar.gz, or tgz format)
        identity: Tuple of (org_id, account_number) from authentication
        db: Database session
        x_rh_insights_request_id: Optional request ID header

    Returns:
        UploadResponse with processing results

    Raises:
        HTTPException: On validation or processing errors
    """
    # Generate or use provided request ID
    request_id = x_rh_insights_request_id or str(uuid.uuid4())
    org_id, account_number = identity

    logger.info(
        f"Upload request {request_id} from org_id={org_id}, account={account_number}"
    )

    # Validate file
    if not upload.filename:
        logger.warning(f"Request {request_id}: No filename provided")
        raise HTTPException(
            status_code=400,
            detail="No filename provided",
        )

    if not upload.filename.endswith((".tar.gz", ".tgz", ".tar")):
        logger.warning(f"Request {request_id}: Invalid file format: {upload.filename}")
        raise HTTPException(
            status_code=400,
            detail="File must be a .tar, .tar.gz, or .tgz archive",
        )

    # Save uploaded file to temporary location
    temp_file_path = None
    try:
        # Determine file suffix
        if upload.filename.endswith('.tar.gz'):
            suffix = '.tar.gz'
        elif upload.filename.endswith('.tgz'):
            suffix = '.tgz'
        else:
            suffix = '.tar'

        # Create temporary file
        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=suffix,
            dir=settings.temp_upload_dir,
        ) as temp_file:
            temp_file_path = temp_file.name

            # Read and validate file size
            chunk_size = 1024 * 1024  # 1MB chunks
            total_size = 0

            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break

                total_size += len(chunk)

                if total_size > settings.max_file_size:
                    logger.warning(
                        f"Request {request_id}: File too large ({total_size} bytes)"
                    )
                    raise HTTPException(
                        status_code=400,
                        detail=f"File size exceeds maximum allowed size of {settings.max_file_size} bytes",
                    )

                temp_file.write(chunk)

        logger.info(
            f"Request {request_id}: Saved uploaded file ({total_size} bytes) to {temp_file_path}"
        )

        # Process archive
        processor = ArchiveProcessor(db, org_id)
        cluster_id, rules_count = processor.process_archive(temp_file_path)

        # Return success response
        response = UploadResponse(
            request_id=request_id,
            status="processed",
            cluster_id=cluster_id,
            rules_found=rules_count,
            uploaded_at=datetime.utcnow(),
        )

        logger.info(
            f"Request {request_id}: Successfully processed cluster {cluster_id} with {rules_count} rules"
        )

        return response

    except ProcessingError as e:
        logger.error(f"Request {request_id}: Processing error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Archive processing failed: {str(e)}",
        )

    except HTTPException:
        # Re-raise HTTP exceptions
        raise

    except Exception as e:
        logger.error(f"Request {request_id}: Unexpected error: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error during upload processing",
        )

    finally:
        # Clean up temporary file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.debug(f"Cleaned up temporary file: {temp_file_path}")
            except Exception as e:
                logger.warning(f"Failed to clean up temporary file: {e}")


@app.get(
    "/api/v1/clusters/reports",
    response_model=ClustersReportResponse,
    status_code=200,
    responses={
        401: {"model": ErrorResponse, "description": "Unauthorized"},
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)
async def get_clusters_reports(
    identity: Tuple[int, str] = Depends(get_identity),
    db: Session = Depends(get_db),
):
    """
    Retrieve reports for all clusters in the organization.

    This endpoint returns all cluster reports for the authenticated organization.

    Args:
        identity: Tuple of (org_id, account_number) from authentication
        db: Database session

    Returns:
        ClustersReportResponse with report data for all clusters in the org

    Raises:
        HTTPException: On authorization or processing errors
    """
    org_id, _ = identity

    logger.info(f"Fetching all cluster reports for org_id={org_id}")

    try:
        clusters_data = {}

        # Query all reports for this organization
        reports = db.query(Report).filter_by(org_id=org_id).all()

        for report in reports:
            cluster_id = report.cluster

            # Query rule hits for this cluster (no join needed - use in-memory content)
            rule_hits = (
                db.query(RuleHit)
                .filter(RuleHit.org_id == org_id, RuleHit.cluster_id == cluster_id)
                .all()
            )

            # Parse report JSON
            try:
                report_data = json.loads(report.report)
            except json.JSONDecodeError:
                logger.warning(
                    f"Failed to parse report JSON for cluster {cluster_id}"
                )
                report_data = {}

            # Build rule hits response with content from content service
            content_service = get_content_service()
            rule_hits_response = []

            for hit in rule_hits:
                # Get content from content service (serves from files, like insights-content-service)
                content_data = content_service.get_content(hit.rule_fqdn, hit.error_key)

                if content_data:
                    template_data = {
                        "description": content_data.get("description", ""),
                        "generic": content_data.get("generic", ""),
                        "reason": content_data.get("reason", ""),
                        "resolution": content_data.get("resolution", ""),
                        "more_info": content_data.get("more_info", ""),
                        "total_risk": content_data.get("total_risk", 1),
                        "likelihood": content_data.get("likelihood", 1),
                        "impact": content_data.get("impact", 1),
                        "publish_date": content_data.get("publish_date"),
                        "tags": content_data.get("tags", []),
                    }
                else:
                    # Content not found - use empty template
                    template_data = {
                        "description": "",
                        "generic": "",
                        "reason": "",
                        "resolution": "",
                        "more_info": "",
                        "total_risk": 1,
                        "likelihood": 1,
                        "impact": 1,
                        "publish_date": None,
                        "tags": [],
                    }

                rule_hits_response.append(
                    RuleHitResponse(
                        rule_fqdn=hit.rule_fqdn,
                        error_key=hit.error_key,
                        template_data=template_data,
                        updated_at=hit.updated_at,
                    )
                )

            # Build cluster report
            clusters_data[cluster_id] = ClusterReport(
                cluster_id=cluster_id,
                org_id=org_id,
                report=report_data,
                reported_at=report.reported_at,
                last_checked_at=report.last_checked_at,
                gathered_at=report.gathered_at,
                rule_hits=rule_hits_response,
            )

        logger.info(f"Successfully fetched {len(clusters_data)} cluster reports")

        return ClustersReportResponse(
            status="ok",
            clusters=clusters_data,
        )

    except Exception as e:
        logger.error(f"Error fetching cluster reports: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error while fetching cluster reports",
        )


@app.get(
    "/api/v1/content",
    response_model=ContentResponse,
    status_code=200,
    responses={
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)
async def get_content():
    """
    Retrieve all available rule content metadata.

    This endpoint mimics the logic of insights-results-smart-proxy's
    v1/content endpoint. It returns metadata about all rules including
    descriptions, impact levels, and remediation information.

    This on-premise deployment serves content directly from markdown/YAML files
    (loaded into memory at startup), just like insights-content-service does.

    Returns:
        ContentResponse with list of rule content metadata

    Raises:
        HTTPException: On processing errors
    """
    logger.info("Fetching all rule content metadata")

    try:
        # Get all content from content service in smart-proxy format
        content_service = get_content_service()
        all_content = content_service.get_all_content_smart_proxy_format()

        logger.info(f"Successfully fetched metadata for {len(all_content)} rules")

        return ContentResponse(
            status="ok",
            content=all_content,
        )

    except Exception as e:
        logger.error(f"Error fetching rule content: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Internal server error while fetching rule content",
        )


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc: HTTPException):
    """Custom handler for HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.detail,
            request_id=request.headers.get("x-rh-insights-request-id"),
        ).dict(),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level=settings.log_level.lower(),
    )

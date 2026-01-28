# Insights On-Premise Single Pod Application

A Python application using FastAPI that receives archives from Insights Operator, processes them with [insights-core](https://github.com/RedHatInsights/insights-core), and stores results in PostgreSQL. This is a simplified, synchronous version suitable for on-premise deployment.

Unlike full pipeline deployment, it doesn't utilize Kafka nor S3-compatible storage for communication between individual components.

As of now, the PoC replicates some of the logic originally contained in `ingress`, `ccx-data-pipeline`, `insights-content-service` and `insights-results-aggregator`.


## Project Structure

```
insights-on-premise-poc/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI application and routes
│   ├── config.py                # Configuration management
│   ├── models.py                # Database models (SQLAlchemy)
│   ├── schemas.py               # Pydantic schemas for API
│   ├── auth.py                  # x-rh-identity header parsing
│   ├── processor.py             # insights-core processing logic
│   ├── database.py              # Database connection and session
│   ├── content_parser_yaml.py   # YAML-based rule content parser
│   └── content_service.py       # Content service for rule metadata
├── migrations/                  # Database migrations (Alembic)
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 001_initial_schema.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # pytest configuration and fixtures
│   ├── test_auth.py             # Authentication tests
│   ├── test_upload.py           # Upload endpoint tests
│   └── test_new_endpoints.py    # Additional endpoint tests
├── deploy/                      # Kubernetes deployment manifests
│   ├── namespace.yml
│   ├── insights.yml             # Main deployment
│   └── service.yml
├── requirements.txt
├── docker-compose.yml           # PostgreSQL + app
├── Dockerfile
├── alembic.ini
├── config.yml                   # Application configuration
├── .env.example                 # Environment variables template
├── .gitignore
├── deploy.sh                    # Deployment script
├── quickstart.sh                # Quick start script
├── update_rules_content.sh      # Script to update rules content
└── README.md
```

## Prerequisites

- Docker and Docker Compose (recommended)
- OR Python 3.11+ and PostgreSQL 15+
- **For full CCX functionality**: Access to Red Hat internal Nexus repository for CCX packages (`ccx-rules-ocp`, `ccx-rules-processing`, `ccx-ocp-core`)
  - These packages provide OpenShift-specific rules and recommendations
  - Without these packages, the application will fall back to basic insights-core functionality

## Quick Start with Docker

1. **Clone the repository:**
   ```bash
   cd insights-on-premise-poc
   ```

2. **Copy environment file:**
   ```bash
   cp .env.example .env
   ```

3. **Clone rules content (optional - included in Docker build):**
   ```bash
   # This step is optional - Docker build automatically clones content
   # Only needed for local development outside Docker
   ./update_rules_content.sh
   ```

4. **Start services with Docker Compose:**
   ```bash
   docker-compose up -d
   ```

5. **Run database migrations:**
   ```bash
   docker-compose exec app alembic upgrade head
   ```

6. **Verify services are running:**
   ```bash
   curl http://localhost:8000/health
   ```

   Expected response:
   ```json
   {"status": "healthy"}
   ```

## Local Development Setup

1. **Create and activate virtual environment:**
   ```bash
   python3.11 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install Red Hat corporate certificates (required for Nexus access):**

   **On RHEL/Fedora (same as ccx-data-pipeline):**
   ```bash
   # Download Red Hat corporate certificates
   sudo curl -o /etc/pki/ca-trust/source/anchors/2022-IT-Root-CA.pem \
     https://certs.corp.redhat.com/certs/2022-IT-Root-CA.pem
   sudo curl -o /etc/pki/ca-trust/source/anchors/Current-IT-Root-CAs.pem \
     https://certs.corp.redhat.com/certs/Current-IT-Root-CAs.pem

   # Update certificate trust store
   sudo update-ca-trust

   # Set environment variable for Python requests
   export REQUESTS_CA_BUNDLE=/etc/pki/tls/certs/ca-bundle.crt
   ```

   ```bash
   # Download Red Hat corporate certificates
   sudo wget -O /usr/local/share/ca-certificates/2022-IT-Root-CA.crt \
     https://certs.corp.redhat.com/certs/2022-IT-Root-CA.pem
   sudo wget -O /usr/local/share/ca-certificates/Current-IT-Root-CAs.crt \
     https://certs.corp.redhat.com/certs/Current-IT-Root-CAs.pem

   # Update certificate trust store
   sudo update-ca-certificates

   # Set environment variable for Python requests
   export REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
   ```

3. **Install dependencies:**

   **With Red Hat internal repository access (full CCX functionality):**
   ```bash
   pip install -r requirements.txt
   ```

   **Without Red Hat internal repository (basic functionality):**
   ```bash
   # Install without CCX packages
   pip install fastapi uvicorn[standard] python-multipart sqlalchemy psycopg2-binary \
               alembic "insights-core>=3.2.26" pydantic pydantic-settings \
               python-dotenv pyyaml pytest pytest-cov httpx
   ```

   **Note**: Without CCX packages, the application will use basic insights-core parsers and fall back to `insights.formats._json.JsonFormat` for output.

4. **Copy environment file:**
   ```bash
   cp .env.example .env
   ```

5. **Start PostgreSQL:**
   ```bash
   docker-compose up -d postgres
   ```

6. **Run database migrations:**
   ```bash
   alembic upgrade head
   ```

7. **Start the application:**
   ```bash
   uvicorn app.main:app --reload
   ```

   The API will be available at http://localhost:8000

## PoC setup

1. Download a Kubernetes secret from Quay for `insights_on_prem_poc` account ([here](https://quay.io/organization/ccxdev?tab=robots)) and store it as `ccxdev-insights-on-prem-poc-secret.yml` under `deploy` directory.
1. Create an Openshift cluster (e.g. using Cluster bot) and install ACM + create a multihubcluster. Use default name for namespace (`open_cluster_management`) during installation.
1. Check that `search_postgres` deployment was created under `open_cluster_management` with `oc get deploy/search_postgres -n open_cluster_management`.
1. Run `./deploy.sh`. The script does the following:
   - Creates `insights-on-prem-poc` namespace for this application.
   - Copies secret for `search_postgres` database into that namespace.
   - Creates a pull secret for Quay used to fetch a PoC image.
   - Creates a deployment with PoC pods + a service.
   - (**TODO**) Configures `insights-client` in `open_cluster_management` to use the created service as new processing backend.
   - (**TODO**) Configures `insights-operator` in `openshift-insights` namespace with new URL for pushing Insights archives.

## API Usage

### Upload Insights Archive

**Endpoint:** `POST /api/ingress/v1/upload`

**Headers:**
- `x-rh-identity`: Base64-encoded JSON with identity information
- `x-rh-insights-request-id`: UUID (optional)
- `Content-Type`: multipart/form-data

**Example Request:**

1. Create identity header:
   ```bash
   # Original JSON:
   # {"identity": {"account_number": "12345", "org_id": "67890", "type": "User"}}

   IDENTITY=$(echo -n '{"identity":{"account_number":"12345","org_id":"67890","type":"User"}}' | base64)
   ```

2. Upload archive:
   ```bash
   curl -X POST http://localhost:8000/api/ingress/v1/upload \
     -H "x-rh-identity: $IDENTITY" \
     -F "file=@/path/to/insights-archive.tar.gz"
   ```

**Response (202 Accepted):**
```json
{
  "request_id": "123e4567-e89b-12d3-a456-426614174000",
  "status": "processed",
  "cluster_id": "cluster-name",
  "rules_found": 5,
  "uploaded_at": "2026-01-21T10:30:00.000000"
}
```

**Error Responses:**
- 400 Bad Request: Invalid file or headers
- 401 Unauthorized: Invalid x-rh-identity
- 500 Internal Server Error: Processing failure

### Health Check

```bash
curl http://localhost:8000/health
```

### API Documentation

Interactive API documentation is available at:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Database Schema

### Tables

**report:**
- `org_id` (INTEGER): Organization ID
- `cluster` (VARCHAR): Unique cluster identifier
- `report` (VARCHAR): JSON report data
- `reported_at` (TIMESTAMP): First report timestamp
- `last_checked_at` (TIMESTAMP): Last update timestamp
- `kafka_offset` (BIGINT): Compatibility field (default 0)
- `gathered_at` (TIMESTAMP): When data was gathered

**rule_hit:**
- `org_id` (INTEGER): Organization ID
- `cluster_id` (VARCHAR): Cluster identifier
- `rule_fqdn` (VARCHAR): Fully qualified rule name
- `error_key` (VARCHAR): Error key for the rule
- `template_data` (VARCHAR): JSON template data
- `updated_at` (TIMESTAMP): Last update timestamp

**report_info:**
- `org_id` (INTEGER): Organization ID
- `cluster_id` (VARCHAR): Cluster identifier
- `version_info` (VARCHAR): JSON version information

### Querying the Database

Connect to PostgreSQL:
```bash
docker-compose exec postgres psql -U insights -d insights
```

Example queries:
```sql
-- View all reports
SELECT org_id, cluster, last_checked_at FROM report;

-- View rule hits for a cluster
SELECT rule_fqdn, error_key, updated_at
FROM rule_hit
WHERE cluster_id = 'your-cluster-id';

-- Count rules by cluster
SELECT cluster_id, COUNT(*) as rule_count
FROM rule_hit
GROUP BY cluster_id;
```

## Configuration

Configuration is managed through environment variables or `config.yml` configuration file. See `.env.example` for all available options.

**Key Configuration:**
- `POSTGRES_HOST`: Database host (default: localhost)
- `POSTGRES_PORT`: Database port (default: 5432)
- `POSTGRES_DB`: Database name (default: insights)
- `POSTGRES_USER`: Database user (default: insights)
- `POSTGRES_PASSWORD`: Database password (default: insights)
- `MAX_FILE_SIZE`: Maximum upload size in bytes (default: 104857600 = 100MB)
- `TEMP_UPLOAD_DIR`: Temporary upload directory (default: /tmp/insights-uploads)
- `LOG_LEVEL`: Logging level (default: INFO)

## Testing

Run tests with pytest:
```bash
pytest tests/ -v
```

Run with coverage:
```bash
pytest --cov=app tests/
```

## Database Migrations

### Create a new migration:
```bash
alembic revision --autogenerate -m "description of changes"
```

### Apply migrations:
```bash
alembic upgrade head
```

### Rollback last migration:
```bash
alembic downgrade -1
```

### View migration history:
```bash
alembic history
```

## Development

### Running in development mode:
```bash
uvicorn app.main:app --reload --log-level debug
```

### Viewing logs:
```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f app
docker-compose logs -f postgres
```

### Rebuilding containers:
```bash
docker-compose down
docker-compose build --no-cache
docker-compose up -d
```

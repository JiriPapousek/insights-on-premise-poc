# Use Red Hat UBI9 minimal - same as ccx-data-pipeline
FROM registry.access.redhat.com/ubi9-minimal:latest

ENV HOME=/app \
    VENV=/app-venv \
    REQUESTS_CA_BUNDLE=/etc/pki/tls/certs/ca-bundle.crt

# Download Red Hat corporate certificates - same as ccx-data-pipeline
ADD https://certs.corp.redhat.com/certs/2022-IT-Root-CA.pem https://certs.corp.redhat.com/certs/Current-IT-Root-CAs.pem /etc/pki/ca-trust/source/anchors/

WORKDIR $HOME

# Copy application code
COPY . $HOME

ENV PATH="$VENV/bin:$PATH"

# Install dependencies and setup - matching ccx-data-pipeline approach
# Added: file, tar, unzip - required by insights-core for archive processing
# Added: git - required to clone ccx-rules-ocp content
RUN microdnf install --nodocs -y python3.11 python3.11-devel gcc postgresql-devel file tar unzip git && \
    python3.11 -m venv $VENV && \
    update-ca-trust && \
    pip install --no-cache-dir -U pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt && \
    microdnf clean all && \
    chmod -R g=u $HOME $VENV && \
    chgrp -R 0 $HOME $VENV

# Clone rules content from ccx-rules-ocp repository
RUN chmod +x $HOME/update_rules_content.sh && \
    $HOME/update_rules_content.sh && \
    chmod -R g=u $HOME/rules-content && \
    chgrp -R 0 $HOME/rules-content

# Create temp upload directory
RUN mkdir -p /tmp/insights-uploads && chmod 777 /tmp/insights-uploads

# Expose port
EXPOSE 8000

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

USER 1001

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

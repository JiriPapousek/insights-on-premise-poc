#!/bin/bash

# Insights On-Premise Quick Start Script
# This script helps you get the application up and running quickly

set -e

echo "============================================"
echo "Insights On-Premise Quick Start"
echo "============================================"
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker compose &> /dev/null; then
    echo "Error: Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file from .env.example..."
    cp .env.example .env
    echo "✓ .env file created"
else
    echo "✓ .env file already exists"
fi

# Create temp upload directory
echo ""
echo "Creating temporary upload directory..."
mkdir -p /tmp/insights-uploads
chmod 777 /tmp/insights-uploads
echo "✓ Temporary upload directory created"

# Start services
echo ""
echo "Starting services with Docker Compose..."
docker compose up -d

# Wait for PostgreSQL to be ready
echo ""
echo "Waiting for PostgreSQL to be ready..."
sleep 10

# Run database migrations
echo ""
echo "Running database migrations..."
docker compose exec -T app alembic upgrade head
echo "✓ Database migrations completed"

# Check service health
echo ""
echo "Checking service health..."
sleep 5

if curl -s http://localhost:8000/health | grep -q "healthy"; then
    echo "✓ Application is running and healthy!"
else
    echo "⚠ Warning: Application may not be fully ready yet"
fi

echo ""
echo "============================================"
echo "Quick Start Complete!"
echo "============================================"
echo ""
echo "Services are running:"
echo "  - Application: http://localhost:8000"
echo "  - API Docs: http://localhost:8000/docs"
echo "  - PostgreSQL: localhost:5432"
echo ""
echo "Test the API:"
echo "  curl http://localhost:8000/health"
echo ""
echo "View logs:"
echo "  docker compose logs -f app"
echo ""
echo "Stop services:"
echo "  docker compose down"
echo ""
echo "For more information, see README.md"
echo ""

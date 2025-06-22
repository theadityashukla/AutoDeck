#!/bin/bash

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Docker is installed and running
if ! command -v docker &> /dev/null; then
    print_error "Docker is not installed. Please install Docker first."
    exit 1
fi

if ! docker info &> /dev/null; then
    print_error "Docker daemon is not running. Please start Docker first."
    exit 1
fi

# Create logs directory
mkdir -p grobid-logs

# Build the custom ARM64 image
print_status "Building custom ARM64 GROBID image..."
docker-compose build

if [ $? -ne 0 ]; then
    print_error "Failed to build GROBID image"
    exit 1
fi

# Start the service
print_status "Starting GROBID service..."
docker-compose up -d

# Wait for service to be ready
print_status "Waiting for GROBID service to be ready..."
for i in {1..30}; do
    if curl -s http://localhost:8070/api/isalive | grep -q "true"; then
        print_status "GROBID service is ready!"
        exit 0
    fi
    echo -n "."
    sleep 2
done

print_error "GROBID service did not become available within timeout"
print_error "Check logs with: docker-compose logs"
exit 1 
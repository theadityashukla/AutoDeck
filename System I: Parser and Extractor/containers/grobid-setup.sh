#!/bin/bash
# grobid-setup.sh - Complete GROBID Docker setup script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
IMAGE_NAME="grobid-custom"
IMAGE_TAG="latest"
CONTAINER_NAME="grobid-daemon"
PORT="8070"

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

check_docker() {
    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed or not in PATH"
        exit 1
    fi
    
    if ! docker info &> /dev/null; then
        print_error "Docker daemon is not running"
        exit 1
    fi
    
    print_status "Docker is available and running"
}

build_image() {
    print_status "Building GROBID Docker image..."
    print_warning "This may take 10-15 minutes depending on your internet connection"
    
    # Create Dockerfile if it doesn't exist
    if [[ ! -f "$SCRIPT_DIR/Dockerfile" ]]; then
        print_error "Dockerfile not found in $SCRIPT_DIR"
        print_status "Creating Dockerfile..."
        
        cat > "$SCRIPT_DIR/Dockerfile" << 'EOF'
# Multi-stage build for GROBID on ARM64 (Mac M1/M2/M3 compatible)
FROM openjdk:11-jdk-slim as builder

# Install required tools for building
RUN apt-get update && apt-get install -y \
    git \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /opt

# Clone GROBID repository
RUN git clone https://github.com/kermitt2/grobid.git

# Build GROBID
WORKDIR /opt/grobid
RUN ./gradlew clean assemble

# Runtime stage
FROM openjdk:11-jre-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create grobid user
RUN useradd -r -s /bin/false grobid

# Copy built GROBID from builder stage
COPY --from=builder /opt/grobid /opt/grobid

# Set ownership
RUN chown -R grobid:grobid /opt/grobid

# Switch to grobid user
USER grobid

# Set working directory
WORKDIR /opt/grobid

# Expose GROBID service port
EXPOSE 8070

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8070/api/isalive || exit 1

# Start GROBID service
CMD ["./gradlew", "run"]
EOF
    fi
    
    docker build -t "$IMAGE_NAME:$IMAGE_TAG" "$SCRIPT_DIR"
    print_status "Docker image built successfully: $IMAGE_NAME:$IMAGE_TAG"
}

start_daemon() {
    print_status "Starting GROBID daemon..."
    
    # Stop existing container if running
    if docker ps -q -f name="$CONTAINER_NAME" | grep -q .; then
        print_warning "Stopping existing GROBID container..."
        docker stop "$CONTAINER_NAME" || true
        docker rm "$CONTAINER_NAME" || true
    fi
    
    # Start new container
    docker run -d \
        --name "$CONTAINER_NAME" \
        --restart unless-stopped \
        -p "$PORT:8070" \
        "$IMAGE_NAME:$IMAGE_TAG"
    
    print_status "GROBID daemon started as container: $CONTAINER_NAME"
    print_status "Service will be available at: http://localhost:$PORT"
    
    # Wait for service to be ready
    print_status "Waiting for GROBID service to be ready..."
    for i in {1..60}; do
        if curl -s "http://localhost:$PORT/api/isalive" | grep -q "true"; then
            print_status "GROBID service is ready!"
            break
        fi
        if [[ $i -eq 60 ]]; then
            print_error "GROBID service did not start within timeout"
            exit 1
        fi
        sleep 2
        echo -n "."
    done
    echo
}

stop_daemon() {
    print_status "Stopping GROBID daemon..."
    if docker ps -q -f name="$CONTAINER_NAME" | grep -q .; then
        docker stop "$CONTAINER_NAME"
        docker rm "$CONTAINER_NAME"
        print_status "GROBID daemon stopped"
    else
        print_warning "GROBID daemon is not running"
    fi
}

status_daemon() {
    if docker ps -q -f name="$CONTAINER_NAME" | grep -q .; then
        print_status "GROBID daemon is running"
        echo "Container ID: $(docker ps -q -f name="$CONTAINER_NAME")"
        echo "Port mapping: $PORT:8070"
        echo "Service URL: http://localhost:$PORT"
        
        # Test service
        if curl -s "http://localhost:$PORT/api/isalive" | grep -q "true"; then
            print_status "Service is responding correctly"
        else
            print_warning "Service is not responding"
        fi
    else
        print_warning "GROBID daemon is not running"
    fi
}

logs_daemon() {
    if docker ps -q -f name="$CONTAINER_NAME" | grep -q .; then
        docker logs -f "$CONTAINER_NAME"
    else
        print_error "GROBID daemon is not running"
        exit 1
    fi
}

usage() {
    echo "Usage: $0 {build|start|stop|restart|status|logs}"
    echo ""
    echo "Commands:"
    echo "  build   - Build the GROBID Docker image"
    echo "  start   - Start the GROBID daemon"
    echo "  stop    - Stop the GROBID daemon"
    echo "  restart - Restart the GROBID daemon"
    echo "  status  - Show daemon status"
    echo "  logs    - Show daemon logs (follow mode)"
    echo ""
    echo "The daemon will be available at: http://localhost:$PORT"
}

main() {
    check_docker
    
    case "${1:-}" in
        build)
            build_image
            ;;
        start)
            start_daemon
            ;;
        stop)
            stop_daemon
            ;;
        restart)
            stop_daemon
            start_daemon
            ;;
        status)
            status_daemon
            ;;
        logs)
            logs_daemon
            ;;
        *)
            usage
            exit 1
            ;;
    esac
}

main "$@"
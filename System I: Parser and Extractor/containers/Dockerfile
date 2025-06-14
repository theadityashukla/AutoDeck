# Multi-stage build for GROBID on ARM64 (Mac M1/M2/M3 compatible)
FROM openjdk:11-jdk-slim as builder

# Install required tools for building
# Using --no-install-recommends reduces image size
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /opt

# Clone GROBID repository (using --depth 1 for a faster, smaller clone)
RUN git clone --depth 1 https://github.com/kermitt2/grobid.git

# Build GROBID
WORKDIR /opt/grobid
RUN ./gradlew clean assemble

# --- Runtime stage ---
FROM openjdk:11-jre-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create a non-root user for security
RUN useradd -r -s /bin/false grobid

# Copy built GROBID from the builder stage
COPY --from=builder /opt/grobid /opt/grobid

# Create a directory for Gradle if it doesn't exist, and ensure the grobid user owns it.
# The -p flag prevents an error if the directory already exists from the build stage.
RUN mkdir -p /opt/grobid/.gradle && chown -R grobid:grobid /opt/grobid

# Set the GRADLE_USER_HOME environment variable to the directory we just created.
ENV GRADLE_USER_HOME=/opt/grobid/.gradle

# Switch to the non-root user
USER grobid

# Set working directory
WORKDIR /opt/grobid

# Expose GROBID service and admin ports
EXPOSE 8070 8071

# Health check to ensure the service is alive
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8070/api/isalive || exit 1

# Start GROBID service
CMD ["./gradlew", "run"]
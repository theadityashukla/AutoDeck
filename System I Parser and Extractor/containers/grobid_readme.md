# Custom GROBID Docker Setup

This setup creates a custom GROBID Docker image that's fully compatible with Mac ARM64 architecture (M1/M2/M3) and can be used as a daemon service.

## Quick Start

### 1. Setup Files

Create the following files in your project directory:

- `Dockerfile` (from the first artifact)
- `docker-compose.yml` (from the third artifact)  
- `grobid-setup.sh` (from the second artifact)
- Update your Python code with the improved version

### 2. Make Setup Script Executable

```bash
chmod +x grobid-setup.sh
```

### 3. Build and Start GROBID

```bash
# Build the custom GROBID image (first time only)
./grobid-setup.sh build

# Start the GROBID daemon
./grobid-setup.sh start
```

### 4. Alternative: Use Docker Compose

```bash
# Build and start in one command
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f

# Stop the service
docker-compose down
```

## Usage

### With the Management Script

```bash
# Check daemon status
./grobid-setup.sh status

# View logs
./grobid-setup.sh logs

# Restart daemon
./grobid-setup.sh restart

# Stop daemon
./grobid-setup.sh stop
```

### In Your Python Code

```python
from grobid_parser import GrobidParser

# Simple usage (assumes daemon is running)
parser = GrobidParser()
xml_result = parser.process_pdf("your_document.pdf")
structured_data = parser.parse_grobid_xml(xml_result)

# With automatic daemon management
from grobid_parser import GrobidDaemon

with GrobidDaemon(auto_start=True) as parser:
    xml_result = parser.process_pdf("your_document.pdf")
    structured_data = parser.parse_grobid_xml(xml_result)
```

## Key Features

1. **ARM64 Native**: Built specifically for Mac M1/M2/M3 processors
2. **Daemon Mode**: Runs as a persistent background service
3. **Auto-restart**: Container automatically restarts if it crashes
4. **Health Checks**: Built-in health monitoring
5. **Standard API**: Compatible with grobid-python and other GROBID clients
6. **Easy Management**: Simple scripts for start/stop/status operations

## API Endpoints

Once running, GROBID will be available at `http://localhost:8070` with all standard endpoints:

- `/api/isalive` - Health check
- `/api/processFulltextDocument` - Full document processing
- `/api/processHeaderDocument` - Header/metadata only
- `/api/processReferences` - References only
- And all other standard GROBID endpoints

## Troubleshooting

### Build Issues

**Problem**: Build fails with "git clone" errors
```bash
# Solution: Check internet connection and try again
./grobid-setup.sh build
```

**Problem**: Build takes too long or hangs
```bash
# Solution: Increase Docker memory allocation in Docker Desktop
# Go to Docker Desktop > Settings > Resources > Memory (recommend 8GB+)
```

**Problem**: "Platform mismatch" warnings
```bash
# For Intel Macs or forcing x86 compatibility:
docker build --platform linux/amd64 -t grobid-custom:latest .
```

### Runtime Issues

**Problem**: Service not responding after startup
```bash
# Check container logs
./grobid-setup.sh logs

# Or with docker-compose
docker-compose logs grobid
```

**Problem**: "Connection refused" errors
```bash
# Ensure service is running
./grobid-setup.sh status

# Check if port is available
lsof -i :8070

# Restart the service
./grobid-setup.sh restart
```

**Problem**: Out of memory errors
```bash
# Increase Java heap size in docker-compose.yml
environment:
  - JAVA_OPTS=-Xmx8g  # Increase from 4g to 8g
```

### Python Integration Issues

**Problem**: Python can't connect to GROBID
```python
# Test connection manually
import requests
response = requests.get("http://localhost:8070/api/isalive")
print(response.text)  # Should print "true"
```

**Problem**: PDF processing fails
```python
# Enable debug logging
import logging
logging.basicConfig(level=logging.DEBUG)

# Check if PDF file exists and is readable
import os
print(os.path.exists("your_file.pdf"))
print(os.access("your_file.pdf", os.R_OK))
```

## Performance Tuning

### Memory Configuration

For large documents, increase memory allocation:

```yaml
# In docker-compose.yml
environment:
  - JAVA_OPTS=-Xmx8g -Xms2g
```

### Processing Multiple PDFs

```python
# Batch processing example
from concurrent.futures import ThreadPoolExecutor
import os

def process_single_pdf(pdf_path):
    parser = GrobidParser()
    return parser.process_pdf(pdf_path)

pdf_files = ["doc1.pdf", "doc2.pdf", "doc3.pdf"]

# Process up to 3 PDFs concurrently (adjust based on memory)
with ThreadPoolExecutor(max_workers=3) as executor:
    results = list(executor.map(process_single_pdf, pdf_files))
```

## Integration with Other Tools

### With grobid-python

```bash
# Install grobid-python
pip install grobid-python

# Use with your daemon
from grobid import GrobidClient

client = GrobidClient(grobid_server="http://localhost:8070")
result = client.process_pdf("document.pdf")
```

### With Jupyter Notebooks

```python
# Cell 1: Start daemon if needed
from grobid_parser import GrobidParser
parser = GrobidParser()

if not parser.is_service_available():
    print("Starting GROBID daemon...")
    parser.start_daemon()

# Cell 2: Process documents
xml_result = parser.process_pdf("research_paper.pdf")
structured_data = parser.parse_grobid_xml(xml_result)

# Cell 3: Analyze results
import pandas as pd
df = pd.DataFrame(structured_data)
print(df.groupby('type').size())
```

## Docker Image Details

### Image Size
- Build image: ~2GB (includes JDK and build tools)
- Runtime image: ~800MB (JRE only)

### Architecture Support
- ARM64 (Apple Silicon M1/M2/M3)
- AMD64 (Intel/AMD x86_64)

### Base Images
- Builder stage: `openjdk:11-jdk-slim`
- Runtime stage: `openjdk:11-jre-slim`

## Advanced Configuration

### Custom GROBID Configuration

```bash
# Create custom config directory
mkdir -p grobid-config

# Mount it in docker-compose.yml
volumes:
  - ./grobid-config:/opt/grobid/grobid-home/config
```

### SSL/HTTPS Setup

```yaml
# Add to docker-compose.yml for HTTPS
volumes:
  - ./ssl-certs:/opt/grobid/ssl
environment:
  - GROBID_SSL=true
```

### Monitoring and Metrics

```bash
# Add health check endpoint monitoring
curl -f http://localhost:8070/api/isalive

# Monitor container resource usage
docker stats grobid-daemon
```

## Updating GROBID

To update to a newer version of GROBID:

```bash
# Stop current daemon
./grobid-setup.sh stop

# Rebuild with latest GROBID
docker-compose build --no-cache

# Start updated daemon
./grobid-setup.sh start
```

## Cleanup

```bash
# Stop and remove containers
./grobid-setup.sh stop

# Remove images
docker rmi grobid-custom:latest

# Clean up Docker system
docker system prune -f
```

## Support

For GROBID-specific issues, consult:
- [GROBID Documentation](https://grobid.readthedocs.io/)
- [GROBID GitHub Issues](https://github.com/kermitt2/grobid/issues)

For Docker-related issues:
- [Docker Documentation](https://docs.docker.com/)
- [Docker Desktop for Mac](https://docs.docker.com/desktop/mac/)
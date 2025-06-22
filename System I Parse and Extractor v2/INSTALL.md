# SuperGrobid Installation Guide

This guide will help you install and set up SuperGrobid on your system.

## Prerequisites

- **Python 3.8 or higher**
- **Conda** (recommended for environment management)
- **Git** (for cloning the repository)

## Step-by-Step Installation

### 1. Clone the Repository

```bash
git clone <repository-url>
cd "System I Parse and Extractor v2"
```

### 2. Set Up Conda Environment

```bash
# Create a new conda environment
conda create -n supergrobid python=3.9

# Activate the environment
conda activate supergrobid
```

### 3. Install Core Dependencies

```bash
# Install basic requirements
pip install -r requirements.txt
```

### 4. Install Optional Dependencies (Recommended)

Some components require additional setup:

#### PyMuPDF (Core - Required)
```bash
pip install PyMuPDF
```

#### LayoutParser (Optional - for layout detection)
```bash
pip install layoutparser[ocr]
```

#### Camelot (Optional - for table extraction)
```bash
# Install system dependencies (Ubuntu/Debian)
sudo apt-get install ghostscript python3-tk

# Install Camelot
pip install camelot-py[cv]
```

#### Nougat (Optional - for advanced structure understanding)
```bash
pip install nougat-ocr
```

### 5. Verify Installation

```bash
# Test basic functionality
python -c "from supergrobid import SuperGrobidParser; print('✅ SuperGrobid installed successfully!')"

# Check system information
python cli.py info
```

## Platform-Specific Instructions

### macOS

```bash
# Install Homebrew if not already installed
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install system dependencies
brew install ghostscript poppler

# Install Python dependencies
pip install -r requirements.txt
```

### Windows

```bash
# Install Ghostscript from: https://www.ghostscript.com/download/gsdnld.html

# Install Python dependencies
pip install -r requirements.txt
```

### Linux (Ubuntu/Debian)

```bash
# Install system dependencies
sudo apt-get update
sudo apt-get install -y \
    ghostscript \
    poppler-utils \
    python3-tk \
    libgl1-mesa-glx \
    libglib2.0-0

# Install Python dependencies
pip install -r requirements.txt
```

## Quick Start

### 1. Basic Usage

```bash
# Parse a single PDF file
python cli.py parse "path/to/your/document.pdf" --output "output.md"

# Parse multiple PDF files
python cli.py batch "path/to/pdf/directory" --output-dir "output"
```

### 2. Programmatic Usage

```python
from supergrobid import SuperGrobidParser

# Initialize parser
parser = SuperGrobidParser("config.yaml")

# Parse a document
result = parser.parse("document.pdf", "markdown", "output.md")

if result["success"]:
    print(f"✅ Parsed successfully in {result['parsing_time']:.2f} seconds")
else:
    print(f"❌ Failed: {result['error']}")
```

### 3. Run Examples

```bash
# Run comprehensive examples
python example_usage.py
```

## Troubleshooting

### Common Issues

#### 1. Import Errors

**Problem**: `ModuleNotFoundError` for dependencies
**Solution**: Ensure you're in the correct conda environment and all dependencies are installed

```bash
conda activate supergrobid
pip install -r requirements.txt
```

#### 2. LayoutParser Issues

**Problem**: LayoutParser fails to load models
**Solution**: Install additional dependencies

```bash
pip install layoutparser[ocr]
pip install "detectron2@git+https://github.com/facebookresearch/detectron2.git@v0.6#egg=detectron2"
```

#### 3. Camelot Issues

**Problem**: Camelot fails to extract tables
**Solution**: Install Ghostscript and ensure proper system dependencies

```bash
# Ubuntu/Debian
sudo apt-get install ghostscript python3-tk

# macOS
brew install ghostscript
```

#### 4. Memory Issues

**Problem**: Out of memory errors with large PDFs
**Solution**: Adjust configuration

```yaml
# In config.yaml
performance:
  batch_size: 1
  max_workers: 2
```

### Getting Help

1. **Check the logs**: Look for detailed error messages in the console output
2. **Verify dependencies**: Run `python cli.py info` to check component status
3. **Test with simple PDF**: Try with a basic text-only PDF first
4. **Check file permissions**: Ensure you have read access to PDF files

## Development Setup

### For Contributors

```bash
# Install development dependencies
pip install -r requirements.txt
pip install -e .

# Install development tools
pip install pytest black flake8 mypy

# Run tests
pytest tests/

# Format code
black supergrobid/

# Lint code
flake8 supergrobid/
```

### Environment Variables

```bash
# Set environment variables for development
export SUPERGROBID_DEBUG=1
export SUPERGROBID_LOG_LEVEL=DEBUG
```

## Performance Optimization

### For Large Documents

1. **Increase memory allocation**:
```bash
export PYTHONPATH="${PYTHONPATH}:/path/to/supergrobid"
```

2. **Use batch processing** for multiple documents:
```bash
python cli.py batch "pdf_directory" --output-dir "output"
```

3. **Adjust configuration** for your use case:
```yaml
performance:
  batch_size: 1
  max_workers: 4
  cache_results: true
```

## Next Steps

1. **Read the documentation**: Check `README.md` for detailed usage
2. **Try the examples**: Run `python example_usage.py`
3. **Explore the CLI**: Use `python cli.py --help` for all options
4. **Customize configuration**: Modify `config.yaml` for your needs

## Support

If you encounter issues:

1. Check the troubleshooting section above
2. Review the logs for detailed error messages
3. Try with a simple test PDF first
4. Open an issue on GitHub with detailed information

---

**Happy parsing! 🚀** 
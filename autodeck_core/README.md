# AutoDeck Core

This package contains the core logic for the AutoDeck multi-agent system.

## Components

### Ingestion Agent
Responsible for parsing PDFs, chunking text using a local LLM (Gemma 3), and storing data in ChromaDB.

**Usage:**
```bash
# Activate conda environment
conda activate autodeck

# Run Ingestion Agent
python autodeck_core/agents/ingestion_agent.py <path_to_pdf>
```

### LLM Client
A wrapper around the local Gemma 3 Flax model.
Requires the model weights to be present in `gemma3-12b-int4`.

### Vector Store
Uses ChromaDB to store document chunks and metadata.
Persists data to `chroma_db` directory.

## Setup
1. Install dependencies: `pip install -r requirements.txt` (or use conda env)
2. Download Gemma 3 model: `python download_gemma3.py`
3. Ensure `gemma` library is installed.

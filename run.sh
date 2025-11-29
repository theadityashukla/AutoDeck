#!/bin/bash
# Helper script to run AutoDeck
echo "Starting AutoDeck..."
export TOKENIZERS_PARALLELISM=false
conda run -n autodeck streamlit run app.py

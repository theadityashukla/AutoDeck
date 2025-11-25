# AutoDeck: AI-Powered Presentation Generator

AutoDeck is an intelligent agentic system that transforms scientific documents (PDFs) into structured PowerPoint presentations. It uses a local LLM (Gemma 3 12B via MLX) and a RAG (Retrieval-Augmented Generation) pipeline to analyze content, plan slides, and generate detailed speaker notes.

## 🚀 Features

-   **PDF Ingestion**: Parses text and extracts images from scientific papers.
-   **Page-Aware Chunking**: Intelligently chunks text while preserving page context.
-   **Smart Image Association**: Uses LLM to link relevant images to text chunks.
-   **Agentic Workflow**:
    -   **Ingestion Agent**: Processes documents into a Vector DB (ChromaDB).
    -   **Retrieval Agent**: Performs semantic search for context.
    -   **Outline Agent**: Plans the presentation structure based on topic and audience.
    -   **Content Agent**: Generates detailed slide content and speaker notes using RAG.
-   **Interactive UI**: Streamlit-based interface for end-to-end control with feedback loops.

## 🛠️ Installation

1.  **Prerequisites**:
    -   macOS with Apple Silicon (M1/M2/M3).
    -   Conda (Miniconda or Anaconda).

2.  **Environment Setup**:
    ```bash
    conda create -n autodeck python=3.11
    conda activate autodeck
    pip install -r requirements.txt  # If you have one, otherwise install dependencies manually
    # Key dependencies: mlx, mlx-lm, streamlit, chromadb, pymupdf, langchain
    ```

3.  **Model Setup**:
    The system uses `mlx-community/gemma-3-12b-it-qat-4bit`. It will be downloaded automatically on the first run, or you can pre-download it using `scripts/download_gemma3.py`.

## 🖥️ Usage

1.  **Start the Application**:
    ```bash
    conda activate autodeck
    streamlit run app.py
    ```

2.  **Workflow**:
    -   **Tab 1: Ingestion**: Place your PDF in `0. Input Data/` and click "Ingest Document".
    -   **Tab 2: Outline**: Enter a topic (e.g., "Oral Semaglutide") and audience. Generate the outline. You can edit/refine it using the chat interface.
    -   **Tab 3: Content**: Select a slide to generate its content. The agent will retrieve context, suggest images, and write speaker notes. You can refine specific slides with feedback.

## 📂 Project Structure

```plaintext
AutoDeck/
├── app.py                  # Main Streamlit Application
├── autodeck_core/          # Core Package
│   ├── agents/             # Agent Implementations
│   │   ├── ingestion_agent.py
│   │   ├── retrieval_agent.py
│   │   ├── outline_agent.py
│   │   └── content_agent.py
│   ├── ingestion/          # Parsing & Vector DB Logic
│   │   ├── parser.py
│   │   ├── chunker.py
│   │   └── vector_store.py
│   └── llm/                # LLM Client (MLX Wrapper)
│       └── gemma_client.py
├── scripts/                # Utility & Test Scripts
├── 0. Input Data/          # Place PDFs here
├── chroma_db/              # Vector Database Storage
└── extracted_images/       # Images extracted from PDFs
```

## 🤖 Agents Overview

1.  **Ingestion Agent**: Reads PDF, extracts text/images, chunks content using LLM, and stores in ChromaDB.
2.  **Retrieval Agent**: Provides a `retrieve(query)` interface to find relevant chunks.
3.  **Slide Outline Agent**: Planner. Takes high-level goal -> produces JSON list of slides.
4.  **Slide Content Agent**: Executor. Takes slide goal -> RAG -> produces Title, Bullets, Image, Notes.
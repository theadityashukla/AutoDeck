# AutoDeck: Intelligent Presentation Studio

AutoDeck is an advanced agentic system that transforms scientific documents (PDFs) into professional, structured PowerPoint presentations. By leveraging a hybrid AI architecture—combining local LLMs (Gemma 3 12B via MLX) for speed and privacy with cloud-based Vision models (Gemini Flash) for complex visual analysis—AutoDeck automates the entire lifecycle of deck creation, from reading papers to designing pixel-perfect slides.

![AutoDeck UI Screenshot](static/ui_mockup.png)
*(Note: Screenshot placeholder)*

## 🚀 Key Features

*   **Multi-Agent Architecture**: Specialized AI agents for Ingestion, Retrieval, Outlining, Content Generation, and Design.
*   **Hybrid AI Pipeline**:
    *   **Local**: Gemma 3 12B (4-bit quantized) via MLX for fast text generation, chunking, and reasoning on Apple Silicon.
    *   **Cloud**: Gemini 1.5 Flash for high-fidelity vision tasks (slide auditing, image analysis).
*   **Intelligent Ingestion**:
    *   Parses complex PDFs with page-aware text chunking.
    *   **Vision-Augmented Ingestion**: Uses local vision to describe figures/charts during ingestion for better semantic search.
*   **Agentic Design Studio**:
    *   **Visual Auditing**: A dedicated Design Agent scans generated slides using computer vision to identify layout issues (overflow, contrast, alignment) and auto-corrects them.
    *   **Text Fitting**: Smart algorithms that read actual PPTX template placeholders to ensure text fits perfectly without overflow.
*   **Material Expressive UI**: A modern, professional interface built on Streamlit with custom CSS.
*   **Template-Based Generation**: Renders final outputs into branded `.pptx` templates, respecting master slide layouts and typography.

## 🛠️ Installation & Setup

### Prerequisites
*   **Hardware**: macOS with Apple Silicon (M1/M2/M3/M4) is required for MLX.
*   **Software**: Conda (Miniconda/Anaconda).

### 1. Clone & Environment
```bash
git clone https://github.com/theadityashukla/AutoDeck.git
cd AutoDeck

# Create Conda environment
conda create -n autodeck python=3.11
conda activate autodeck

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Variables
Create a `.env` file in the root directory:
```bash
cp .env.example .env
```
Edit `.env` and add your Google Gemini API key (required for Vision capabilities):
```ini
GEMINI_API_KEY=your_api_key_here
```

### 3. Model Setup
The system automatically downloads the local LLM (`mlx-community/gemma-3-12b-it-qat-4bit`) on first run.

## 🖥️ Usage Guide

1.  **Launch the Studio**:
    ```bash
    streamlit run app.py
    ```
    Access the UI at `http://localhost:8501`.

2.  **Step 1: Ingestion**:
    *   Upload a PDF (scientific paper, report) in the *Ingestion* tab.
    *   The system parses text and analyzes images using local vision.

3.  **Step 2: Outline**:
    *   Define your topic and audience.
    *   The *Agenda Agent* proposes a storyline. You can edit/refine this outline interactively.

4.  **Step 3: Content Generation**:
    *   The *Content Agent* uses RAG to write detailed bullet points and speaker notes for each slide.
    *   It retrieves relevant figures from the paper to attach to slides.

5.  **Step 4: Agentic Design & Export**:
    *   Go to *Agentic Design*.
    *   Click **"Generate Full Deck"**. The system renders slides, audits them visually, and iteratively improves them (e.g., shortening text if it overflows).
    *   Click **"Export Presentation"** to download the final `.pptx` file.

## 🏗️ Architecture

The system is built on a modular "Agent Swarm" pattern:

1.  **IngestionAgent**: Prepares data. Uses `AgenticChunker` with vision capabilities to create semantically rich chunks.
2.  **RetrievalAgent**: Semantic search engine using ChromaDB and optimized embeddings.
3.  **AgendaAgent (Planner)**: specialized in narrative structure and pacing.
4.  **ContentAgent (Writer)**: specialized in summarization, RAG, and speaker note generation.
5.  **DesignAgent (Critic/Fixer)**: A multimodal agent that *looks* at rendered slides using Gemini Vision. It acts as a human designer, spotting issues like "text is cut off" or "image overlaps header" and issuing specific correction commands (e.g., `REDUCE_FONT_SIZE`, `MOVE_IMAGE`).
6.  **PPTGenerator**: The rendering engine that interfaces with `python-pptx` to manipulate the actual slide objects.

## 🧗 Challenges & Solutions

During development, we tackled several critical engineering challenges:

### 1. Text Overflow in PPTX
*   **Challenge**: LLMs often generate too much text, causing it to run off the slide. Hardcoded limits were inaccurate because font rendering varies by template.
*   **Solution**: Implemented a `TextFitter` module that reads the *exact* dimensions of placeholders from the master slide template (in EMUs). We calculate fit dynamically and use the Design Agent's visual feedback loop as a final safety net to detect any remaining overflow.

### 2. Hallucinating Vision Models
*   **Challenge**: Early attempts with Vision models (Gemma local) for design critique resulted in hallucinations—the model would claim text was overlapping when it wasn't, or miss obvious errors.
*   **Solution**: We adopted a **Hybrid Approach**:
    *   Use **Gemini 1.5 Flash** (via API) solely for the high-stakes "Design Critique" step, as it has superior OCR and spatial reasoning.
    *   Use **Gemma 3 (Local)** for all text generation and content tasks to maintain speed and privacy.
    *   Refined the Vision Prompt to be extremely conservative ("innocent until proven guilty") to prevent false positives.

### 3. Template Integrity
*   **Challenge**: Generating slides that look "native" to a corporate template rather than generic Python-generated layouts.
*   **Solution**: Instead of creating text boxes from scratch, we shifted to **populating existing placeholders** within the slide master. This ensures that fonts, colors, and margins defined in the `.pptx` template are automatically respected.

### 4. Interactive State Management
*   **Challenge**: Managing a long-running multi-step pipeline (Generate -> Render -> Audit -> Fix -> Render...) in Streamlit, which is stateless by default.
*   **Solution**: Implemented a robust `session_state` machine with flags for `pipeline_running`, `review_queue`, and intermediate checkpoints, allowing the user to pause, inspect, and resume generation.

## 🔮 Future Enhancements

*   **Advanced Layout Engine**: Move beyond standard "Title + Body" layouts. Implement an AI that can select from 10+ smart layouts (Grid, 2-Column, Hero Image) based on content type.
*   **Chart Generation**: Instead of pasting static images from PDFs, use the LLM to extract data tables and generate native, editable PowerPoint charts.
*   **Style Transfer**: A module that can ingest a user's existing presentation, learn their specific writing style and visual preferences (fonts, colors), and apply it to new decks.
*   **Fully Local Vision**: As local VLM (Vision Language Model) performance improves, migrate the Design Agent from Gemini to a quantized local model (like LLaVA or future Gemma Vision variants) for a 100% offline stack.

## 📂 Project Structure

```plaintext
AutoDeck/
├── app.py                  # Main Application Entry Point
├── autodeck_core/          # Core Logic Package
│   ├── agents/             # Specialist Agents (Design, Content, Ingestion)
│   ├── ingestion/          # PDF Parsing & Vector Store
│   ├── llm/                # Model Clients (Gemma, Gemini)
│   ├── ppt_generator.py    # PowerPoint Rendering Engine
│   └── text_fitter.py      # Dynamic Text Sizing Logic
├── templates/              # PPTX Master Templates
├── static/                 # CSS & UI Assets
└── scripts/                # Utility Scripts
```
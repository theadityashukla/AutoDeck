**Project Plan: GROBID Mark II - A Hybrid, Python-Native Scientific Document Parser**

---

### **Overview**

This project aims to build a modular, extensible, and fully Python-native document ingestion pipeline for scientific PDFs, designed to surpass the usability and reliability of GROBID. It will fuse deterministic PDF parsing, visual layout modeling, CRF-style segmentation, and deep learning components for high-fidelity, hallucination-free structured output.

---

### **Phase 0: Setup & Infrastructure (Week 1)**

**Goals:**

- Setup repository with modular architecture
- Define input/output formats (Markdown, JSON, TEI-lite)
- Establish testbed of academic PDFs (2-column, equations, tables, figures)

**Deliverables:**

- GitHub repository
- `config.yaml` for document-wide parameters
- `/docs/input_papers/` and `/docs/ground_truth/`
- Baseline performance metrics for PyMuPDF and PDFX

---

### **Phase 1: Core Extraction Modules (Week 2-3)**

#### 1. **Text Extractor: PyMuPDF**

- Extract all text blocks with bounding boxes, fonts, and metadata
- Output JSON with block structure:
  ```json
  {
    "page": 1,
    "blocks": [
      {"bbox": [x0, y0, x1, y1], "text": "...", "font_size": 12, ... }
    ]
  }
  ```

#### 2. **Visual Layout: Nougat Integration**

- Run Nougat on same page to extract Markdown scaffold
- Extract semantic structure (e.g., headings, lists, figures)
- Save output as parsed Markdown JSON:
  ```json
  [{"type": "section", "text": "Introduction"}, ...]
  ```

#### 3. **LayoutParser for Region Detection**

- Use `PubLayNet` model to identify regions:
  - Title
  - Abstract
  - Body
  - References
  - Figures
- Save to JSON layout annotation

---

### **Phase 2: Reconciliation Logic (Week 4-5)**

#### 1. **Fuzzy Text Matcher**

- Use Levenshtein/cosine similarity to align Nougat elements with PyMuPDF blocks
- Replace hallucinated text with exact PyMuPDF content

#### 2. **Self-Correction Module**

- Orphan Detection:
  - Unmatched PyMuPDF blocks → assign to nearest scaffold element
- Hallucination Filter:
  - Nougat elements with < X% match → discard

#### 3. **Unified Representation Generator**

- Output TEI-lite XML or Markdown with positional fidelity

---

### **Phase 3: Specialized Content Parsers (Week 6-7)**

#### 1. **Tables**

- TableNet to detect table regions
- Extract using Camelot (stream/lattice)
- If parsing fails → fallback to LLM-based table OCR from screenshot

#### 2. **Equations**

- Detect bounding box using Nougat + PyMuPDF alignment
- Crop region → Im2Latex to generate LaTeX code

#### 3. **References**

- Use PDFX to extract reference block
- Optional: Fine-tune SciBERT for reference segmentation (author, title, year)
- Match citations inline with parsed references

---

### **Phase 4: Pipeline Orchestration (Week 8)**

- Combine modules into a modular CLI + Python API
- Define workflows:
  - `--parse` (end-to-end parse)
  - `--reconcile` (Nougat + PyMuPDF)
  - `--export xml|md|json`
- Include CLI for batch parsing of PDFs

---

### **Phase 5: Testing & Benchmarking (Week 9)**

- Compare output against GROBID on:
  - Parsing accuracy (sections, tables, refs)
  - Speed & resource usage
  - Robustness to malformed PDFs

---

### **Phase 6: Packaging & Deployment (Week 10)**

- Package as `supergrobid` Python library
- Add Dockerfile + pip install support
- Publish documentation (readthedocs or mkdocs)
- Optional: Streamlit UI or Gradio demo

---

### **Bonus Extensions (Future Roadmap)**

- LLM-enhanced summarizer & slide generator
- PDF annotation support with citation linkbacks
- LangChain/RAG-native output format
- Language support for non-English documents

---

### **Team Roles (Suggested)**

- **NLP/ML Engineer:** Reconciliation, SciBERT training, Im2Latex fine-tuning
- **Python Dev:** Pipeline orchestration, API/CLI
- **Data Engineer:** Dataset generation, benchmarking
- **Documentation Lead:** Examples, usage guides

---

### **KPIs for Success**

- ≥90% accuracy in section + ref parsing on testbed
- <2 hallucinated lines per document
- Time to parse full paper: <10 seconds on M1/M2 chip
- 100% Python-native (no Java/Gradle/CRF requirements)

---

This plan provides a realistic path to building a practical, extensible replacement for GROBID tailored to modern RAG use cases, multimodal documents, and Python-native infrastructure.


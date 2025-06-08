**Brainstorm: RAG‑driven PowerPoint Generation**

**1. Objectives & Requirements**

* **User Input:** Structured prompts capturing:

  * **Overall Topic:** What the presentation is about.
  * **Subtopics / Keywords:** Specific areas to cover.
  * **Time Allocation:** Desired duration per subtopic or total runtime.
  * **Audience Profile:** Technical level (e.g., general public, domain experts).
  * **Document Selection Mode:** User choice: (a) select specific docs from library, or (b) use all available resources.
* **Knowledge Source:** Scientific documents parsed via GROBID (text only).
* **Retrieval:** Vector search over text chunks in Vector DB.
* **LLM Chains & Agents:** Orchestrate retrieval, summarization, slide drafting, reviews.
* **Output:** `.pptx` file with slides, titles, bullet points, speaker notes, and placeholders for images/tables.

---

**2. System Architecture**

```plaintext
[User Input UI] → [Prompt Parser] → [RAG Retriever] ↔ [Vector DB]
                                   ↓
                        [Agent Orchestrator]
                                   ↓
                            [Slide Builder]
                                   ↓
                              [PowerPoint]
```

**3. Component Breakdown**

| Component | Description |
|-----------|-------------|
| **Frontend / CLI** | Web UI or CLI collecting structured inputs & allowing doc selection. |
| **Storage Layer** | Meta DB for document inventory + Vector DB (e.g., Chroma, Pinecone). |
| **Parsing & Embedding** | GROBID → raw text chunks; Embedding service to vectorize. |
| **Retriever** | LangChain `VectorStoreRetriever` to fetch top‐k chunks. |
| **Agent / Workflow Engine** | LangChain Agent manages retrieval loops, summarization, refinement. |
| **LLM Chains** | Chains for outline generation, slide content, notes, error‐checking. |
| **Slide Builder** | `python-pptx` to assemble slides; stub for image/table insertion. |

---

**4. Pipeline Steps**

1. **Prompt Parsing:** Extract topic, subtopics, timing, audience, doc mode.
2. **Document Selection:** If user-chosen, present list; else select all.
3. **Initial Retrieval:** Fetch text chunks from Vector DB.
4. **Outline Generation:** LLM drafts slide structure & titles.
5. **Content Expansion:** For each slide, retrieve context → draft bullets & speaker notes.
6. **Review & Refine (Agent):** Check for gaps/hallucinations; re-retrieve as needed.
7. **PPT Construction:** Use `python-pptx`, insert slide text, leave placeholders for images/tables.
8. **Post-Processing:** Resolve placeholders by extracting figures/tables from original PDFs (future).
9. **Export & Delivery:** Save and return `.pptx`.


**5. Open Questions & Next Steps**

* Strategy for **images & tables**: How to extract, store, embed in slides.
* User-driven **template selection** & theming.
* Citation formatting on slides.
* Chart generation & figure creation from data.
* Auth, multi-user, deployment.

---

**6. Status & Enhancement Tracker**

| Status | Tasks |
|--------|-------|
| **Completed** | • Initial architecture & pseudocode<br>• GROBID parsing for text |
| **In Progress** | • Vector DB ingestion<br>• Designing structured user input and doc-selection UI |
| **Enhancements** | • Image/table encoding (extract & embed figures)<br>• Custom templates & themes<br>• Citation/reference formatting<br>• Chart/figure auto-generation<br>• Placeholder resolution workflows |
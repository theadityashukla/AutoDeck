Below is a detailed pseudo code/algorithm based on the provided project plan (`super_grobid_plan.md`) and README (`README.md`) for the Hybrid "Compare and Reconcile" Parsing Strategy. This algorithm serves as a foundation for designing a Python-native solution to ingest scientific PDFs into a structured format suitable for a Retrieval-Augmented Generation (RAG) pipeline. It combines deterministic parsing (PyMuPDF), visual layout modeling (Nougat), and specialized content parsing to achieve high-fidelity, hallucination-free output.

---

### Detailed Pseudo Code/Algorithm

This algorithm outlines the complete workflow for processing a scientific PDF, including text extraction, structural scaffolding, reconciliation, specialized content parsing, and output generation. Each function is detailed to facilitate implementation.

#### **Main Pipeline**
The main function orchestrates the entire process, taking a PDF file path and desired output format as inputs.

```pseudo
function main(pdf_path, output_format='markdown'):
    # Step 1: Extract raw text blocks with PyMuPDF
    pymupdf_output = extract_text_with_pymupdf(pdf_path)
    
    # Step 2: Generate structural scaffold with Nougat
    nougat_output = generate_markdown_with_nougat(pdf_path)
    
    # Step 3: Detect layout regions with LayoutParser (optional guidance)
    layout_output = detect_regions_with_layoutparser(pdf_path)
    
    # Step 4: Reconcile Nougat structure with PyMuPDF text
    reconciled_output = reconcile_outputs(nougat_output, pymupdf_output, layout_output)
    
    # Step 5: Parse specialized content (tables, equations, references)
    tables = parse_tables(reconciled_output, layout_output)
    equations = parse_equations(reconciled_output, layout_output)
    references = parse_references(reconciled_output, layout_output)
    
    # Step 6: Generate final structured output
    final_output = generate_unified_output(reconciled_output, tables, equations, references, output_format)
    
    return final_output
```

---

#### **Step 1: Text Extraction with PyMuPDF**
Extracts all text blocks from the PDF with their metadata (e.g., bounding boxes, font sizes).

```pseudo
function extract_text_with_pymupdf(pdf_path):
    doc = fitz.open(pdf_path)  # Open PDF using PyMuPDF
    all_blocks = []  # List to store text blocks
    
    for page_num in range(len(doc)):
        page = doc.load_page(page_num)
        blocks = page.get_text("dict")["blocks"]  # Extract blocks with metadata
        
        for block in blocks:
            if block["type"] == 0:  # Filter for text blocks only
                bbox = block["bbox"]  # [x0, y0, x1, y1]
                text = ""
                font_size = None
                for line in block["lines"]:
                    for span in line["spans"]:
                        text += span["text"] + " "
                        font_size = span["size"]  # Capture font size (assumes uniform per block)
                all_blocks.append({
                    "page": page_num + 1,
                    "bbox": bbox,
                    "text": text.strip(),
                    "font_size": font_size
                })
    
    return all_blocks
```

---

#### **Step 2: Generate Markdown Scaffold with Nougat**
Uses Nougat to create a structured Markdown representation of the PDF.

```pseudo
function generate_markdown_with_nougat(pdf_path):
    # Execute Nougat to generate Markdown (via CLI or API)
    markdown_str = run_nougat_on_pdf(pdf_path)  # Placeholder for Nougat execution
    
    # Parse Markdown into a structured list of elements
    parsed_markdown = parse_markdown(markdown_str)
    
    return parsed_markdown

function parse_markdown(markdown_str):
    elements = []  # List of structural elements
    # Pseudo logic to parse Markdown (assumes a Markdown parser library)
    lines = markdown_str.split("\n")
    for line in lines:
        if line.startswith("#"):
            elements.append({"type": "header", "text": line.strip("# ").strip()})
        elif line.startswith("-") or line.startswith("*"):
            elements.append({"type": "list", "text": line.strip("-* ").strip()})
        elif line.startswith("!["):
            elements.append({"type": "figure", "text": line})  # Placeholder for figure
        elif line.startswith("|"):
            elements.append({"type": "table", "text": line})  # Placeholder for table
        else:
            elements.append({"type": "paragraph", "text": line.strip()})
    return elements
```

---

#### **Step 3: Detect Regions with LayoutParser**
Identifies key regions (e.g., title, abstract) using LayoutParser for additional context.

```pseudo
function detect_regions_with_layoutparser(pdf_path):
    regions = []  # List of detected regions
    # Pseudo logic for LayoutParser with PubLayNet model
    # Convert PDF pages to images and process with LayoutParser
    for page_image in convert_pdf_to_images(pdf_path):
        layout = run_layoutparser(page_image, model="PubLayNet")
        for region in layout:
            regions.append({
                "page": region.page,
                "type": region.type,  # e.g., "title", "abstract", "body", "figure", "table"
                "bbox": region.bbox  # [x0, y0, x1, y1]
            })
    return regions
```

---

#### **Step 4: Reconcile Nougat and PyMuPDF Outputs**
Aligns Nougat’s structural elements with PyMuPDF’s exact text, correcting hallucinations and handling orphans.

```pseudo
function reconcile_outputs(nougat_output, pymupdf_output, layout_output):
    reconciled = []  # Final reconciled output
    pymupdf_index = 0  # Tracks position in PyMuPDF blocks
    
    for element in nougat_output:
        if element["type"] in ["header", "paragraph", "list"]:  # Text elements
            # Find matching PyMuPDF blocks
            matched_blocks, new_index = find_matching_blocks(element["text"], pymupdf_output, pymupdf_index)
            if matched_blocks:
                exact_text = " ".join([block["text"] for block in matched_blocks])
                reconciled.append({
                    "type": element["type"],
                    "text": exact_text,
                    "blocks": matched_blocks  # Store for positional reference
                })
                pymupdf_index = new_index
            else:
                # Discard element if no match (hallucination filter, < X% similarity)
                continue
        elif element["type"] in ["figure", "table"]:
            # Handle non-text elements using surrounding context
            if reconciled and reconciled[-1]["type"] in ["header", "paragraph", "list"]:
                prev_blocks = reconciled[-1]["blocks"]
                next_blocks = find_next_text_blocks(pymupdf_output, pymupdf_index)
                if next_blocks:
                    bbox = calculate_element_bbox(prev_blocks, next_blocks)
                    if element["type"] == "figure":
                        figure_image = crop_image_from_pdf(pdf_path, bbox)
                        reconciled.append({"type": "figure", "image": figure_image})
                    elif element["type"] == "table":
                        table_data = extract_table_from_bbox(pdf_path, bbox)
                        reconciled.append({"type": "table", "data": table_data})
    
    # Append orphan blocks
    while pymupdf_index < len(pymupdf_output):
        orphan = pymupdf_output[pymupdf_index]
        if reconciled and reconciled[-1]["type"] in ["header", "paragraph", "list"]:
            reconciled[-1]["text"] += " " + orphan["text"]
        pymupdf_index += 1
    
    return reconciled

function find_matching_blocks(nougat_text, pymupdf_output, start_index):
    matched_blocks = []
    max_similarity = 0.8  # Threshold for match (configurable)
    best_match_end = start_index
    
    # Sliding window to find best match
    for i in range(start_index, len(pymupdf_output)):
        window_text = " ".join([block["text"] for block in pymupdf_output[start_index:i+1]])
        similarity = compute_similarity(nougat_text, window_text)  # e.g., Levenshtein or cosine
        if similarity >= max_similarity:
            matched_blocks = pymupdf_output[start_index:i+1]
            best_match_end = i + 1
    
    return matched_blocks, best_match_end

function find_next_text_blocks(pymupdf_output, start_index):
    next_blocks = []
    for i in range(start_index, len(pymupdf_output)):
        next_blocks.append(pymupdf_output[i])
        if len(next_blocks) >= 3:  # Arbitrary limit for next block sequence
            break
    return next_blocks

function calculate_element_bbox(prev_blocks, next_blocks):
    prev_bottom = max([b["bbox"][3] for b in prev_blocks])  # y1 of last prev block
    next_top = min([b["bbox"][1] for b in next_blocks])  # y0 of first next block
    return [prev_blocks[0]["bbox"][0], prev_bottom, next_blocks[-1]["bbox"][2], next_top]
```

---

#### **Step 5: Parse Specialized Content**
Parses tables, equations, and references using dedicated tools.

- **Tables**:
```pseudo
function parse_tables(reconciled_output, layout_output):
    tables = []
    table_regions = [r for r in layout_output if r["type"] == "table"]
    
    for region in table_regions:
        table_data = extract_table_with_camelot(pdf_path, region["bbox"])
        if table_data:
            tables.append({"bbox": region["bbox"], "data": table_data})
        else:
            # Fallback to LLM-based OCR
            table_image = crop_image_from_pdf(pdf_path, region["bbox"])
            table_markdown = llm_table_ocr(table_image)
            tables.append({"bbox": region["bbox"], "data": table_markdown})
    
    return tables
```

- **Equations**:
```pseudo
function parse_equations(reconciled_output, layout_output):
    equations = []
    # Detect equations from reconciled output or layout
    equation_regions = [e for e in reconciled_output if e["type"] == "equation"] or \
                      [r for r in layout_output if r["type"] == "equation"]
    
    for region in equation_regions:
        equation_image = crop_image_from_pdf(pdf_path, region["bbox"])
        latex_code = im2latex(equation_image)
        equations.append({"bbox": region["bbox"], "latex": latex_code})
    
    return equations
```

- **References**:
```pseudo
function parse_references(reconciled_output, layout_output):
    ref_region = [r for r in layout_output if r["type"] == "references"][0]  # Assume one ref section
    references_block = extract_references_with_pdfx(pdf_path, ref_region["bbox"])
    
    if use_scibert:
        references = segment_references_with_scibert(references_block)
    else:
        references = parse_references_simple(references_block)  # Basic string splitting
    
    return references
```

---

#### **Step 6: Generate Unified Output**
Combines all parsed content into the specified format.

```pseudo
function generate_unified_output(reconciled_output, tables, equations, references, output_format):
    if output_format == 'markdown':
        output = build_markdown(reconciled_output, tables, equations, references)
    elif output_format == 'xml':
        output = build_tei_xml(reconciled_output, tables, equations, references)
    else:
        output = build_json(reconciled_output, tables, equations, references)
    return output

function build_markdown(reconciled_output, tables, equations, references):
    markdown = ""
    table_idx, eq_idx = 0, 0
    for element in reconciled_output:
        if element["type"] == "header":
            markdown += f"# {element['text']}\n\n"
        elif element["type"] == "paragraph":
            markdown += f"{element['text']}\n\n"
        elif element["type"] == "list":
            markdown += f"- {element['text']}\n"
        elif element["type"] == "table" and table_idx < len(tables):
            markdown += f"{tables[table_idx]['data']}\n\n"
            table_idx += 1
        elif element["type"] == "equation" and eq_idx < len(equations):
            markdown += f"$${equations[eq_idx]['latex']}$$\n\n"
            eq_idx += 1
    markdown += "## References\n" + "\n".join(references)
    return markdown

function build_tei_xml(reconciled_output, tables, equations, references):
    xml = "<TEI>\n<body>\n"
    for element in reconciled_output:
        if element["type"] == "header":
            xml += f"<head>{element['text']}</head>\n"
        elif element["type"] == "paragraph":
            xml += f"<p>{element['text']}</p>\n"
    xml += "</body>\n<back>\n<listBibl>\n"
    for ref in references:
        xml += f"<bibl>{ref}</bibl>\n"
    xml += "</listBibl>\n</back>\n</TEI>"
    return xml

function build_json(reconciled_output, tables, equations, references):
    return {
        "text": [{"type": e["type"], "content": e["text"]} for e in reconciled_output],
        "tables": tables,
        "equations": equations,
        "references": references
    }
```

---

#### **CLI Orchestration**
Provides a command-line interface for running the pipeline.

```pseudo
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SuperGrobid PDF Parser")
    parser.add_argument("--pdf", required=True, help="Path to input PDF")
    parser.add_argument("--output", default="output.md", help="Output file path")
    parser.add_argument("--format", choices=["markdown", "xml", "json"], default="markdown")
    args = parser.parse_args()
    
    result = main(args.pdf, args.format)
    with open(args.output, "w") as f:
        f.write(result)
```

---
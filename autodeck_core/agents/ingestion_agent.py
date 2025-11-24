import os
from typing import List, Dict, Any
from autodeck_core.ingestion.parser import PDFParser
from autodeck_core.ingestion.chunker import AgenticChunker
from autodeck_core.ingestion.vector_store import VectorStore

class IngestionAgent:
    def __init__(self, mock_llm: bool = False):
        self.parser = PDFParser()
        self.chunker = AgenticChunker(mock=mock_llm)
        self.vector_store = VectorStore()

    def ingest(self, pdf_path: str):
        print(f"Starting ingestion for: {pdf_path}")
        
        # 1. Parse PDF
        print("Parsing PDF...")
        parsed_data = self.parser.parse(pdf_path)
        full_text = parsed_data['full_text']
        images = []
        for page in parsed_data['pages']:
            images.extend(page['images'])
            
        print(f"Extracted {len(full_text)} characters and {len(images)} images.")
        
        # 2. Page-Aware Chunking & Image Association
        print("Chunking text page by page (this may take time with local LLM)...")
        processed_chunks = []
        
        for page_data in parsed_data['pages']:
            page_num = page_data['page_number']
            page_text = page_data['text']
            page_images = page_data['images']
            
            if not page_text.strip():
                continue
                
            print(f"Processing Page {page_num}...")
            
            # Chunk the page text, passing available images
            page_chunks = self.chunker.chunk(page_text, images=page_images)
            
            # Process chunks and resolve image indices to paths
            for i, chunk in enumerate(page_chunks):
                # Resolve image indices to actual paths
                related_image_paths = []
                related_indices = chunk.get('related_images', [])
                
                for idx in related_indices:
                    if isinstance(idx, int) and 0 <= idx < len(page_images):
                        related_image_paths.append(page_images[idx]['path'])
                
                meta = {
                    "source": parsed_data['filename'],
                    "title": chunk.get('title', 'Untitled'),
                    "summary": chunk.get('summary', ''),
                    "page_number": page_num,
                    "chunk_index": len(processed_chunks) + i,
                    "related_images": str(related_image_paths) # Store as string representation
                }
                
                processed_chunks.append({
                    "content": chunk.get('content', ''),
                    "metadata": meta
                })
            

            
        print(f"Generated {len(processed_chunks)} total chunks.")
            
        # 4. Store in Vector DB
        print("Storing in Vector DB...")
        self.vector_store.add_documents(processed_chunks)
        print("Ingestion complete!")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        agent = IngestionAgent()
        agent.ingest(sys.argv[1])
    else:
        print("Usage: python ingestion_agent.py <path_to_pdf>")

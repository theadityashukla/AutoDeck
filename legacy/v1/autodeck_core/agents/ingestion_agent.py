import os
from typing import List, Dict, Any
from autodeck_core.ingestion.parser import PDFParser
from autodeck_core.ingestion.chunker import AgenticChunker
from autodeck_core.ingestion.vector_store import VectorStore

from autodeck_core.logger import setup_logger

class IngestionAgent:
    def __init__(self, mock_llm: bool = False):
        self.parser = PDFParser()
        self.chunker = AgenticChunker(mock=mock_llm)
        self.vector_store = VectorStore()
        self.logger = setup_logger("IngestionAgent")

    def ingest(self, pdf_path: str, progress_callback=None, stop_check=None, log_callback=None):
        # Update logger with callback if provided
        if log_callback:
            self.logger = setup_logger("IngestionAgent", log_callback=log_callback)

        filename = os.path.basename(pdf_path)
        self.logger.info(f"Starting ingestion for: {filename}")
        
        # 1. Parse PDF
        if progress_callback:
            progress_callback(0, "Parsing PDF...")
        
        parsed_data = self.parser.parse(pdf_path)
        full_text = parsed_data['full_text']
        images = []
        for page in parsed_data['pages']:
            images.extend(page['images'])
            
        self.logger.info(f"Extracted {len(full_text)} characters and {len(images)} images.")
        
        # 2. Check for existing pages (Resume Logic)
        existing_pages = self.vector_store.get_existing_pages(filename)
        self.logger.info(f"Found {len(existing_pages)} existing pages in DB.")
        
        # 3. Page-Aware Chunking & Image Association
        total_pages = len(parsed_data['pages'])
        
        for i, page_data in enumerate(parsed_data['pages']):
            # Check for stop signal
            if stop_check and stop_check():
                self.logger.info("Ingestion stopped by user.")
                if progress_callback:
                    progress_callback(i / total_pages, "Ingestion stopped.")
                return

            page_num = page_data['page_number']
            
            # Skip if already processed
            if page_num in existing_pages:
                self.logger.info(f"Skipping Page {page_num} (already processed).")
                if progress_callback:
                    progress_callback((i + 1) / total_pages, f"Skipping Page {page_num} (already done)...")
                continue

            page_text = page_data['text']
            page_images = page_data['images']
            
            if not page_text.strip():
                continue
                
            self.logger.info(f"Processing Page {page_num}...")
            if progress_callback:
                progress_callback((i + 0.1) / total_pages, f"Processing Page {page_num} of {total_pages}...")
            
            # Chunk the page text, passing available images
            page_chunks = self.chunker.chunk(page_text, images=page_images)
            
            processed_chunks = []
            # Process chunks and resolve image indices to paths
            for j, chunk in enumerate(page_chunks):
                # Resolve image indices to actual paths
                related_image_paths = []
                related_indices = chunk.get('related_images', [])
                
                for idx in related_indices:
                    if isinstance(idx, int) and 0 <= idx < len(page_images):
                        related_image_paths.append(page_images[idx]['path'])
                
                meta = {
                    "source": filename,
                    "title": chunk.get('title', 'Untitled'),
                    "summary": chunk.get('summary', ''),
                    "page_number": page_num,
                    "chunk_index": j, # Index within page
                    "related_images": str(related_image_paths)
                }
                
                processed_chunks.append({
                    "content": chunk.get('content', ''),
                    "metadata": meta
                })
            
            # Store IMMEDIATELY after processing the page to allow resume
            if processed_chunks:
                self.vector_store.add_documents(processed_chunks)
            
            if progress_callback:
                progress_callback((i + 1) / total_pages, f"Completed Page {page_num}")
            
        self.logger.info("Ingestion complete!")
        if progress_callback:
            progress_callback(1.0, "Ingestion Complete!")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        agent = IngestionAgent()
        agent.ingest(sys.argv[1])
    else:
        print("Usage: python ingestion_agent.py <path_to_pdf>")
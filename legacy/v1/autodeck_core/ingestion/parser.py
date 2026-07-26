import fitz  # PyMuPDF
import os
from pathlib import Path
from typing import List, Dict, Any, Tuple
import hashlib

class PDFParser:
    def __init__(self, output_dir: str = "extracted_images"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def parse(self, pdf_path: str) -> Dict[str, Any]:
        """
        Parses a PDF file to extract text and images.
        
        Args:
            pdf_path: Path to the PDF file.
            
        Returns:
            A dictionary containing:
            - text: Full text content.
            - pages: List of page content (text and image metadata).
            - metadata: PDF metadata.
        """
        doc = fitz.open(pdf_path)
        pdf_name = Path(pdf_path).stem
        
        # Create specific directory for this PDF's images
        pdf_image_dir = self.output_dir / pdf_name
        pdf_image_dir.mkdir(exist_ok=True)
        
        full_text = []
        pages_data = []
        
        for page_num, page in enumerate(doc):
            # Extract text
            text = page.get_text()
            full_text.append(text)
            
            # Extract images
            image_list = page.get_images(full=True)
            page_images = []
            
            for img_index, img in enumerate(image_list):
                xref = img[0]
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]
                
                # Generate a unique filename based on content hash to avoid duplicates
                image_hash = hashlib.md5(image_bytes).hexdigest()
                image_filename = f"img_{page_num+1}_{img_index+1}_{image_hash[:8]}.{image_ext}"
                image_path = pdf_image_dir / image_filename
                
                # Save image
                with open(image_path, "wb") as f:
                    f.write(image_bytes)
                
                page_images.append({
                    "path": str(image_path.absolute()),
                    "page": page_num + 1,
                    "index": img_index,
                    "ext": image_ext,
                    "xref": xref
                })
            
            pages_data.append({
                "page_number": page_num + 1,
                "text": text,
                "images": page_images
            })
            
        return {
            "filename": Path(pdf_path).name,
            "full_text": "\n".join(full_text),
            "pages": pages_data,
            "metadata": doc.metadata
        }

if __name__ == "__main__":
    # Simple test
    import sys
    if len(sys.argv) > 1:
        parser = PDFParser()
        result = parser.parse(sys.argv[1])
        print(f"Parsed {result['filename']}")
        print(f"Total pages: {len(result['pages'])}")
        print(f"Total images extracted: {sum(len(p['images']) for p in result['pages'])}")

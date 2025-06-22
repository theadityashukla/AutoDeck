import os
import re
import logging
from typing import List, Dict, Any, Optional
import fitz  # PyMuPDF
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PyMuPDFParser:
    """
    A fast and reliable PDF parser using PyMuPDF (fitz) that works perfectly on ARM Macs.
    This is a great alternative to GROBID for most use cases.
    """
    
    def __init__(self):
        self.doc = None
    
    def process_pdf(self, pdf_path: str) -> List[Dict[str, Any]]:
        """
        Process a PDF file and extract structured content.
        
        Args:
            pdf_path: Path to the PDF file
            
        Returns:
            List of content blocks with structure similar to GROBID output
        """
        if not os.path.exists(pdf_path):
            logger.error(f"PDF file not found at {pdf_path}")
            return []
        
        try:
            self.doc = fitz.open(pdf_path)
            content_blocks = []
            
            # Extract metadata
            metadata = self.doc.metadata
            if metadata.get('title'):
                content_blocks.append({
                    "type": "metadata",
                    "title": metadata.get('title', ''),
                    "author": metadata.get('author', ''),
                    "subject": metadata.get('subject', ''),
                    "creator": metadata.get('creator', '')
                })
            
            # Process each page
            for page_num in range(len(self.doc)):
                page = self.doc[page_num]
                page_blocks = self._process_page(page, page_num)
                content_blocks.extend(page_blocks)
            
            return content_blocks
            
        except Exception as e:
            logger.error(f"Error processing PDF: {e}")
            return []
        finally:
            if self.doc:
                self.doc.close()
    
    def _process_page(self, page, page_num: int) -> List[Dict[str, Any]]:
        """Process a single page and extract structured content."""
        blocks = []
        
        # Extract text blocks with positioning
        text_dict = page.get_text("dict")
        
        for block in text_dict.get("blocks", []):
            if "lines" in block:  # Text block
                block_text = ""
                for line in block["lines"]:
                    for span in line["spans"]:
                        block_text += span["text"] + " "
                
                block_text = block_text.strip()
                if block_text:
                    blocks.append({
                        "type": "paragraph",
                        "text": block_text,
                        "page": page_num + 1,
                        "bbox": block["bbox"],
                        "headers": self._extract_headers(block_text)
                    })
        
        # Extract images
        image_list = page.get_images()
        for img_index, img in enumerate(image_list):
            xref = img[0]
            bbox = page.get_image_bbox(img)
            if bbox:
                blocks.append({
                    "type": "image",
                    "page": page_num + 1,
                    "bbox": bbox,
                    "image_index": img_index,
                    "xref": xref
                })
        
        # Extract tables (basic detection)
        tables = page.find_tables()
        for table in tables:
            blocks.append({
                "type": "table",
                "page": page_num + 1,
                "bbox": table.bbox,
                "rows": table.extract(),
                "headers": self._extract_table_headers(table)
            })
        
        return blocks
    
    def _extract_headers(self, text: str) -> List[str]:
        """Extract potential headers from text based on formatting."""
        headers = []
        lines = text.split('\n')
        for line in lines:
            line = line.strip()
            # Simple header detection (can be improved)
            if (len(line) < 100 and 
                line.isupper() or 
                line.endswith(':') or
                re.match(r'^[0-9]+\.', line)):
                headers.append(line)
        return headers
    
    def _extract_table_headers(self, table) -> List[str]:
        """Extract headers from table."""
        if table.extract():
            return table.extract()[0]  # First row as headers
        return []
    
    def extract_images(self, pdf_path: str, output_dir: str = "extracted_images") -> List[str]:
        """
        Extract images from PDF for further processing.
        
        Args:
            pdf_path: Path to PDF file
            output_dir: Directory to save extracted images
            
        Returns:
            List of paths to extracted images
        """
        if not os.path.exists(pdf_path):
            return []
        
        Path(output_dir).mkdir(exist_ok=True)
        image_paths = []
        
        try:
            doc = fitz.open(pdf_path)
            
            for page_num in range(len(doc)):
                page = doc[page_num]
                image_list = page.get_images()
                
                for img_index, img in enumerate(image_list):
                    xref = img[0]
                    pix = fitz.Pixmap(doc, xref)
                    
                    if pix.n - pix.alpha < 4:  # GRAY or RGB
                        img_filename = f"page_{page_num + 1}_img_{img_index}.png"
                        img_path = os.path.join(output_dir, img_filename)
                        pix.save(img_path)
                        image_paths.append(img_path)
                    
                    pix = None  # Free memory
            
            doc.close()
            return image_paths
            
        except Exception as e:
            logger.error(f"Error extracting images: {e}")
            return []


class UnstructuredParser:
    """
    Alternative parser using unstructured library - great for complex documents.
    """
    
    def __init__(self):
        try:
            from unstructured.partition.auto import partition
            from unstructured.documents.elements import Table, Text, Title
            self.partition = partition
            self.available = True
        except ImportError:
            logger.warning("unstructured library not available. Install with: pip install unstructured")
            self.available = False
    
    def process_pdf(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Process PDF using unstructured library."""
        if not self.available:
            return []
        
        try:
            elements = self.partition(pdf_path)
            content_blocks = []
            
            for element in elements:
                if isinstance(element, Text):
                    content_blocks.append({
                        "type": "paragraph",
                        "text": str(element),
                        "metadata": element.metadata
                    })
                elif isinstance(element, Title):
                    content_blocks.append({
                        "type": "title",
                        "text": str(element),
                        "metadata": element.metadata
                    })
                elif isinstance(element, Table):
                    content_blocks.append({
                        "type": "table",
                        "text": str(element),
                        "metadata": element.metadata
                    })
            
            return content_blocks
            
        except Exception as e:
            logger.error(f"Error processing PDF with unstructured: {e}")
            return []


class PDFPlumberParser:
    """
    Alternative parser using pdfplumber - excellent for table extraction.
    """
    
    def __init__(self):
        try:
            import pdfplumber
            self.pdfplumber = pdfplumber
            self.available = True
        except ImportError:
            logger.warning("pdfplumber not available. Install with: pip install pdfplumber")
            self.available = False
    
    def process_pdf(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Process PDF using pdfplumber."""
        if not self.available:
            return []
        
        content_blocks = []
        
        try:
            with self.pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages):
                    # Extract text
                    text = page.extract_text()
                    if text:
                        content_blocks.append({
                            "type": "paragraph",
                            "text": text,
                            "page": page_num + 1
                        })
                    
                    # Extract tables
                    tables = page.extract_tables()
                    for table_num, table in enumerate(tables):
                        if table:
                            content_blocks.append({
                                "type": "table",
                                "data": table,
                                "page": page_num + 1,
                                "table_num": table_num
                            })
            
            return content_blocks
            
        except Exception as e:
            logger.error(f"Error processing PDF with pdfplumber: {e}")
            return []


# Factory function to get the best available parser
def get_best_parser() -> Any:
    """
    Returns the best available PDF parser for your system.
    Prioritizes PyMuPDF as it works best on ARM Macs.
    """
    try:
        import fitz
        logger.info("Using PyMuPDF parser (recommended for ARM Macs)")
        return PyMuPDFParser()
    except ImportError:
        logger.warning("PyMuPDF not available. Install with: pip install PyMuPDF")
        
        try:
            from unstructured.partition.auto import partition
            logger.info("Using Unstructured parser")
            return UnstructuredParser()
        except ImportError:
            try:
                import pdfplumber
                logger.info("Using PDFPlumber parser")
                return PDFPlumberParser()
            except ImportError:
                logger.error("No PDF parser available. Install one of: PyMuPDF, unstructured, or pdfplumber")
                return None


if __name__ == '__main__':
    # Example usage
    PDF_FILE = "/Users/aditya/Documents/Codes/Projects/Gen AI assited Keynotes/AutoDeck/0. Input Data/AlphaFold.pdf"
    
    if not os.path.exists(PDF_FILE):
        print(f"PDF file not found: {PDF_FILE}")
        print("Please update the PDF_FILE path to test the parser.")
        exit(1)
    
    # Get the best available parser
    parser = get_best_parser()
    
    if parser:
        print(f"Using parser: {parser.__class__.__name__}")
        content_blocks = parser.process_pdf(PDF_FILE)
        
        print(f"\n--- Structured Document Output ---")
        import json
        print(json.dumps(content_blocks[:3], indent=2))  # Show first 3 chunks
        print(f"\nSuccessfully parsed document into {len(content_blocks)} chunks.")
        
        # If using PyMuPDF, also extract images
        if isinstance(parser, PyMuPDFParser):
            print("\nExtracting images...")
            image_paths = parser.extract_images(PDF_FILE)
            print(f"Extracted {len(image_paths)} images")
    else:
        print("No PDF parser available. Please install one of the recommended libraries.") 
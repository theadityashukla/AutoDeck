"""
Extractors module for SuperGrobid
Contains PyMuPDF, Nougat, and LayoutParser implementations
"""

import fitz  # PyMuPDF
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path
import numpy as np
from pdf2image import convert_from_path
import layoutparser as lp
from PIL import Image
import torch
import platform
import os
import subprocess

from .utils import clean_text, format_bbox


class PyMuPDFExtractor:
    """Extract text blocks with metadata using PyMuPDF."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger('supergrobid.extractors.pymupdf')
    
    def extract(self, pdf_path: str) -> List[Dict[str, Any]]:
        """
        Extract all text blocks from PDF with metadata.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            List of text blocks with metadata
        """
        self.logger.info(f"Extracting text from {pdf_path}")
        
        try:
            doc = fitz.open(pdf_path)
            all_blocks = []
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                blocks = page.get_text("dict")["blocks"]
                
                for block in blocks:
                    if block["type"] == 0:  # Text block
                        text_blocks = self._process_text_block(block, page_num + 1)
                        all_blocks.extend(text_blocks)
            
            doc.close()
            self.logger.info(f"Extracted {len(all_blocks)} text blocks")
            return all_blocks
            
        except Exception as e:
            self.logger.error(f"Error extracting text from {pdf_path}: {e}")
            raise
    
    def _process_text_block(self, block: Dict[str, Any], page_num: int) -> List[Dict[str, Any]]:
        """Process a single text block and extract text with metadata."""
        text_blocks = []
        bbox = block["bbox"]
        
        for line in block["lines"]:
            line_text = ""
            font_size = None
            font_name = None
            
            for span in line["spans"]:
                line_text += span["text"]
                if font_size is None:
                    font_size = span["size"]
                    font_name = span["font"]
            
            if line_text.strip():
                text_blocks.append({
                    "page": page_num,
                    "bbox": bbox,
                    "text": clean_text(line_text),
                    "font_size": font_size,
                    "font_name": font_name,
                    "type": "text"
                })
        
        return text_blocks


class NougatExtractor:
    """Generate structured Markdown using Nougat."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger('supergrobid.extractors.nougat')
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Load Nougat model."""
        try:
            from nougat import NougatModel
            from nougat.utils.dataset import ImageDataset
            from nougat.utils.checkpoint import get_checkpoint
            
            model_name = self.config.get('text_extraction', {}).get('nougat', {}).get('model_name', 'facebook/nougat-base')
            # Use Metal (MPS) if available on Apple Silicon
            if torch.backends.mps.is_available() and platform.system() == 'Darwin':
                device = 'mps'
            elif torch.cuda.is_available():
                device = 'cuda'
            else:
                device = 'cpu'
            
            # Workaround for compression_type issue
            try:
                # Try to patch the configuration if needed
                os.environ['NOUGAT_COMPRESSION_TYPE'] = 'jpeg'
                
                self.model = NougatModel.from_pretrained(
                    model_name,
                    device_map=device,
                    torch_dtype=torch.float16 if device in ("cuda", "mps") else torch.float32
                )
            except Exception as e:
                self.logger.warning(f"Advanced loading failed: {e}, trying basic loading")
                try:
                    self.model = NougatModel.from_pretrained(model_name)
                    self.model.to(device)
                except Exception as e2:
                    self.logger.warning(f"Basic loading also failed: {e2}, using fallback method")
                    self.model = None
                    return
            
            self.model.eval()
            self.logger.info(f"Loaded Nougat model: {model_name} on {device}")
        except Exception as e:
            self.logger.warning(f"Nougat model loading failed: {e}, using fallback method")
            self.model = None
    
    def extract(self, pdf_path: str) -> List[Dict[str, Any]]:
        """
        Generate structured Markdown using Nougat.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            List of structured elements
        """
        self.logger.info(f"Generating structured content from {pdf_path}")
        
        if self.model is None:
            return self._fallback_extraction(pdf_path)
        
        try:
            # Convert PDF to images
            images = convert_from_path(pdf_path)
            structured_elements = []
            
            for page_num, image in enumerate(images):
                page_elements = self._process_page_with_nougat(image, page_num + 1)
                structured_elements.extend(page_elements)
            
            self.logger.info(f"Generated {len(structured_elements)} structured elements")
            return structured_elements
            
        except Exception as e:
            self.logger.error(f"Error in Nougat extraction: {e}")
            return self._fallback_extraction(pdf_path)
    
    def _process_page_with_nougat(self, image: Image.Image, page_num: int) -> List[Dict[str, Any]]:
        """Process a single page with Nougat."""
        try:
            if self.model is None:
                return []
            
            # Convert image to tensor format expected by Nougat
            from nougat.utils.dataset import ImageDataset
            
            # Create a simple dataset with the image
            dataset = ImageDataset([image], max_length=self.config.get('text_extraction', {}).get('nougat', {}).get('max_length', 4096))
            
            # Get the first (and only) item
            batch = dataset[0]
            
            # Generate markdown using the model's generate method
            with torch.no_grad():
                try:
                    # Try the inference method first
                    output = self.model.inference(image=batch["image"], max_length=batch["max_length"])
                except AttributeError:
                    # Fallback to generate method
                    output = self.model.generate(batch["image"], max_length=batch["max_length"])
                except Exception as e:
                    self.logger.error(f"Error in Nougat generation: {e}")
                    return []
            
            # Parse the markdown output into structured elements
            elements = self._parse_markdown_output(output, page_num)
            
            return elements
            
        except Exception as e:
            self.logger.error(f"Error processing page {page_num} with Nougat: {e}")
            return []
    
    def _parse_markdown_output(self, markdown_text: str, page_num: int) -> List[Dict[str, Any]]:
        """Parse Nougat markdown output into structured elements."""
        elements = []
        lines = markdown_text.split('\n')
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            if line.startswith('#'):
                # Header
                level = len(line) - len(line.lstrip('#'))
                text = line.lstrip('#').strip()
                elements.append({
                    "page": page_num,
                    "type": f"header_{level}",
                    "text": text,
                    "bbox": [0, 0, 0, 0],  # Placeholder
                    "confidence": 0.9
                })
            elif line.startswith('- ') or line.startswith('* '):
                # List item
                text = line[2:].strip()
                elements.append({
                    "page": page_num,
                    "type": "list_item",
                    "text": text,
                    "bbox": [0, 0, 0, 0],  # Placeholder
                    "confidence": 0.8
                })
            elif line.startswith('|') and line.endswith('|'):
                # Table row
                elements.append({
                    "page": page_num,
                    "type": "table_row",
                    "text": line,
                    "bbox": [0, 0, 0, 0],  # Placeholder
                    "confidence": 0.7
                })
            else:
                # Regular paragraph
                elements.append({
                    "page": page_num,
                    "type": "paragraph",
                    "text": line,
                    "bbox": [0, 0, 0, 0],  # Placeholder
                    "confidence": 0.8
                })
        
        return elements
    
    def _fallback_extraction(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Fallback extraction when Nougat is not available."""
        self.logger.info("Using fallback extraction method")
        
        # Simple fallback using PyMuPDF to extract basic structure
        doc = fitz.open(pdf_path)
        elements = []
        
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            text = page.get_text()
            
            # Simple parsing of text into paragraphs
            paragraphs = text.split('\n\n')
            for i, para in enumerate(paragraphs):
                if para.strip():
                    elements.append({
                        "page": page_num + 1,
                        "type": "paragraph",
                        "text": clean_text(para),
                        "bbox": [0, 0, 0, 0],  # Placeholder
                        "confidence": 1.0
                    })
        
        doc.close()
        return elements


class LayoutParserExtractor:
    """Detect layout regions using LayoutParser."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger('supergrobid.extractors.layoutparser')
        self.model = None
        self._load_model()
    
    def _load_model(self):
        """Load LayoutParser model."""
        try:
            model_config = self.config.get('layout_detection', {}).get('layoutparser', {})
            model_name = model_config.get('model_name', 'PubLayNet')
            
            if model_name == 'PubLayNet':
                try:
                    # Try the PaddleDetectionLayoutModel first
                    self.model = lp.PaddleDetectionLayoutModel(
                        config_path='lp://PubLayNet/ppyolov2_r50vd_dcn_365e',
                        label_map={0: "Text", 1: "Title", 2: "List", 3: "Table", 4: "Figure"}
                    )
                    # Set threshold after instantiation (API fix for latest layoutparser)
                    self.model.threshold = model_config.get('confidence_threshold', 0.5)
                except AttributeError:
                    # Fallback to AutoLayoutModel
                    self.logger.warning("PaddleDetectionLayoutModel not available, trying AutoLayoutModel")
                    self.model = lp.AutoLayoutModel('lp://PubLayNet/faster_rcnn_R_50_FPN_3x')
                except Exception as e:
                    self.logger.warning(f"LayoutParser model loading failed: {e}")
                    self.model = None
            else:
                try:
                    self.model = lp.AutoLayoutModel(model_name)
                except Exception as e:
                    self.logger.warning(f"Could not load LayoutParser model {model_name}: {e}")
                    self.model = None
            
            if self.model:
                self.logger.info(f"Loaded LayoutParser model: {model_name}")
            else:
                self.logger.warning("No LayoutParser model available, layout detection will be disabled")
            
        except Exception as e:
            self.logger.warning(f"Could not load LayoutParser model: {e}")
            self.model = None
    
    def extract(self, pdf_path: str) -> List[Dict[str, Any]]:
        """
        Detect layout regions in PDF.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            List of detected regions
        """
        self.logger.info(f"Detecting layout regions in {pdf_path}")
        
        if self.model is None:
            return []
        
        try:
            # Convert PDF to images with explicit poppler path
            # Try to find poppler path
            poppler_path = None
            try:
                result = subprocess.run(['which', 'pdftoppm'], capture_output=True, text=True)
                if result.returncode == 0:
                    poppler_path = os.path.dirname(result.stdout.strip())
                    self.logger.info(f"Found poppler at: {poppler_path}")
            except Exception as e:
                self.logger.warning(f"Could not find poppler path: {e}")
            
            # Convert PDF to images
            if poppler_path:
                images = convert_from_path(pdf_path, poppler_path=poppler_path)
            else:
                images = convert_from_path(pdf_path)
            
            all_regions = []
            
            for page_num, image in enumerate(images):
                page_regions = self._detect_regions_on_page(image, page_num + 1)
                all_regions.extend(page_regions)
            
            self.logger.info(f"Detected {len(all_regions)} layout regions")
            return all_regions
            
        except Exception as e:
            self.logger.error(f"Error in layout detection: {e}")
            return []
    
    def _detect_regions_on_page(self, image: Image.Image, page_num: int) -> List[Dict[str, Any]]:
        """Detect regions on a single page."""
        try:
            # Convert PIL image to numpy array
            image_array = np.array(image)
            
            # Detect layout
            layout = self.model.detect(image_array)
            
            regions = []
            for region in layout:
                regions.append({
                    "page": page_num,
                    "type": region.type,
                    "bbox": region.block.coordinates,
                    "confidence": region.score,
                    "text": ""  # LayoutParser doesn't extract text
                })
            
            return regions
            
        except Exception as e:
            self.logger.error(f"Error detecting regions on page {page_num}: {e}")
            return []
    
    def get_region_by_type(self, regions: List[Dict[str, Any]], region_type: str) -> List[Dict[str, Any]]:
        """Get regions of a specific type."""
        return [r for r in regions if r["type"].lower() == region_type.lower()] 
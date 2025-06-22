"""
Specialized content parsers for SuperGrobid
Handles tables, equations, and references
"""

import logging
from typing import Dict, List, Any, Optional
import fitz
from pdf2image import convert_from_path
from PIL import Image
import numpy as np

from .utils import clean_text, merge_bboxes


class TableParser:
    """Parse tables from PDF using Camelot and fallback methods."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger('supergrobid.specialized.table')
        
        table_config = config.get('specialized_content', {}).get('tables', {})
        self.camelot_config = table_config.get('camelot', {})
        self.use_fallback_llm = table_config.get('fallback_llm', True)
    
    def parse_tables(self, pdf_path: str, table_regions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Parse tables from detected table regions.
        
        Args:
            pdf_path: Path to PDF file
            table_regions: List of detected table regions
            
        Returns:
            List of parsed tables with data
        """
        self.logger.info(f"Parsing {len(table_regions)} tables")
        parsed_tables = []
        
        for region in table_regions:
            try:
                table_data = self._extract_table_with_camelot(pdf_path, region["bbox"])
                
                if table_data and table_data.get("data"):
                    parsed_tables.append({
                        "bbox": region["bbox"],
                        "page": region["page"],
                        "data": table_data["data"],
                        "accuracy": table_data.get("accuracy", 0.0),
                        "method": "camelot"
                    })
                elif self.use_fallback_llm:
                    # Fallback to LLM-based OCR
                    table_data = self._extract_table_with_llm(pdf_path, region["bbox"])
                    if table_data:
                        parsed_tables.append({
                            "bbox": region["bbox"],
                            "page": region["page"],
                            "data": table_data,
                            "accuracy": 0.7,  # Estimated accuracy for LLM
                            "method": "llm_ocr"
                        })
                
            except Exception as e:
                self.logger.error(f"Error parsing table in region {region['bbox']}: {e}")
                continue
        
        self.logger.info(f"Successfully parsed {len(parsed_tables)} tables")
        return parsed_tables
    
    def _extract_table_with_camelot(self, pdf_path: str, bbox: List[float]) -> Optional[Dict[str, Any]]:
        """Extract table using Camelot."""
        try:
            import camelot
            
            # Convert bbox to Camelot format (page, area)
            page_num = int(bbox[0]) if len(bbox) > 4 else 1
            area = f"{bbox[1]},{bbox[2]},{bbox[3]},{bbox[4]}" if len(bbox) > 4 else None
            
            # Extract table
            tables = camelot.read_pdf(
                pdf_path,
                pages=str(page_num),
                area=area,
                flavor=self.camelot_config.get('flavor', 'stream'),
                edge_tol=self.camelot_config.get('edge_tol', 500),
                row_tol=self.camelot_config.get('row_tol', 10)
            )
            
            if tables:
                best_table = max(tables, key=lambda t: t.accuracy)
                return {
                    "data": best_table.df.to_dict('records'),
                    "accuracy": best_table.accuracy
                }
            
        except ImportError:
            self.logger.warning("Camelot not available")
        except Exception as e:
            self.logger.error(f"Error in Camelot extraction: {e}")
        
        return None
    
    def _extract_table_with_llm(self, pdf_path: str, bbox: List[float]) -> Optional[str]:
        """Extract table using LLM-based OCR (placeholder)."""
        # This would integrate with an LLM service for table OCR
        # For now, return a placeholder
        self.logger.info("LLM-based table OCR not implemented yet")
        return None


class EquationParser:
    """Parse equations from PDF using Im2Latex."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger('supergrobid.specialized.equation')
        
        eq_config = config.get('specialized_content', {}).get('equations', {})
        self.confidence_threshold = eq_config.get('im2latex', {}).get('confidence_threshold', 0.7)
    
    def parse_equations(self, pdf_path: str, equation_regions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Parse equations from detected equation regions.
        
        Args:
            pdf_path: Path to PDF file
            equation_regions: List of detected equation regions
            
        Returns:
            List of parsed equations with LaTeX
        """
        self.logger.info(f"Parsing {len(equation_regions)} equations")
        parsed_equations = []
        
        for region in equation_regions:
            try:
                equation_data = self._extract_equation_with_im2latex(pdf_path, region["bbox"])
                
                if equation_data and equation_data.get("latex"):
                    parsed_equations.append({
                        "bbox": region["bbox"],
                        "page": region["page"],
                        "latex": equation_data["latex"],
                        "confidence": equation_data.get("confidence", 0.0),
                        "method": "im2latex"
                    })
                
            except Exception as e:
                self.logger.error(f"Error parsing equation in region {region['bbox']}: {e}")
                continue
        
        self.logger.info(f"Successfully parsed {len(parsed_equations)} equations")
        return parsed_equations
    
    def _extract_equation_with_im2latex(self, pdf_path: str, bbox: List[float]) -> Optional[Dict[str, Any]]:
        """Extract equation using Im2Latex."""
        try:
            # Convert PDF region to image
            images = convert_from_path(pdf_path)
            if not images:
                return None
            
            # Crop image to equation region
            page_num = int(bbox[0]) if len(bbox) > 4 else 0
            if page_num >= len(images):
                return None
            
            image = images[page_num]
            if len(bbox) > 4:
                # Crop to bbox coordinates
                x0, y0, x1, y1 = bbox[1:5]
                cropped_image = image.crop((x0, y0, x1, y1))
            else:
                cropped_image = image
            
            # Convert to LaTeX (placeholder implementation)
            latex_code = self._image_to_latex(cropped_image)
            
            if latex_code:
                return {
                    "latex": latex_code,
                    "confidence": 0.8  # Placeholder confidence
                }
            
        except Exception as e:
            self.logger.error(f"Error in Im2Latex extraction: {e}")
        
        return None
    
    def _image_to_latex(self, image: Image.Image) -> Optional[str]:
        """Convert image to LaTeX code (placeholder)."""
        # This would use the actual Im2Latex model
        # For now, return a placeholder
        self.logger.info("Im2Latex model not implemented yet")
        return None


class ReferenceParser:
    """Parse references from PDF using PDFX and optional SciBERT."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger('supergrobid.specialized.reference')
        
        ref_config = config.get('specialized_content', {}).get('references', {})
        self.use_scibert = ref_config.get('scibert', {}).get('enabled', False)
        self.extract_citations = ref_config.get('pdfx', {}).get('extract_citations', True)
    
    def parse_references(self, pdf_path: str, reference_regions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Parse references from detected reference regions.
        
        Args:
            pdf_path: Path to PDF file
            reference_regions: List of detected reference regions
            
        Returns:
            List of parsed references
        """
        self.logger.info(f"Parsing references from {len(reference_regions)} regions")
        parsed_references = []
        
        for region in reference_regions:
            try:
                references_data = self._extract_references_with_pdfx(pdf_path, region["bbox"])
                
                if references_data:
                    if self.use_scibert:
                        # Use SciBERT for fine-grained parsing
                        segmented_refs = self._segment_references_with_scibert(references_data)
                    else:
                        # Use simple parsing
                        segmented_refs = self._parse_references_simple(references_data)
                    
                    for ref in segmented_refs:
                        parsed_references.append({
                            "bbox": region["bbox"],
                            "page": region["page"],
                            "text": ref.get("text", ""),
                            "authors": ref.get("authors", []),
                            "title": ref.get("title", ""),
                            "year": ref.get("year", ""),
                            "journal": ref.get("journal", ""),
                            "doi": ref.get("doi", ""),
                            "method": "scibert" if self.use_scibert else "simple"
                        })
                
            except Exception as e:
                self.logger.error(f"Error parsing references in region {region['bbox']}: {e}")
                continue
        
        self.logger.info(f"Successfully parsed {len(parsed_references)} references")
        return parsed_references
    
    def _extract_references_with_pdfx(self, pdf_path: str, bbox: List[float]) -> Optional[str]:
        """Extract references using PDFX."""
        try:
            import pdfx
            
            # Extract references from PDF
            pdf = pdfx.PDFx(pdf_path)
            references = pdf.get_references()
            
            if references:
                return "\n".join(references)
            
        except ImportError:
            self.logger.warning("PDFX not available")
        except Exception as e:
            self.logger.error(f"Error in PDFX extraction: {e}")
        
        return None
    
    def _segment_references_with_scibert(self, references_text: str) -> List[Dict[str, Any]]:
        """Segment references using SciBERT (placeholder)."""
        # This would use SciBERT for fine-grained reference parsing
        # For now, return simple parsing
        self.logger.info("SciBERT reference segmentation not implemented yet")
        return self._parse_references_simple(references_text)
    
    def _parse_references_simple(self, references_text: str) -> List[Dict[str, Any]]:
        """Simple reference parsing using basic string operations."""
        references = []
        
        if not references_text:
            return references
        
        # Split by common reference separators
        ref_lines = references_text.split('\n')
        
        for line in ref_lines:
            line = line.strip()
            if not line:
                continue
            
            # Simple parsing (this is a basic implementation)
            ref = {
                "text": line,
                "authors": [],
                "title": "",
                "year": "",
                "journal": "",
                "doi": ""
            }
            
            # Try to extract year (4-digit number)
            import re
            year_match = re.search(r'\b(19|20)\d{2}\b', line)
            if year_match:
                ref["year"] = year_match.group()
            
            # Try to extract DOI
            doi_match = re.search(r'10\.\d{4,}/[-._;()/:\w]+', line)
            if doi_match:
                ref["doi"] = doi_match.group()
            
            references.append(ref)
        
        return references
    
    def extract_citations(self, pdf_path: str) -> List[Dict[str, Any]]:
        """Extract inline citations from the document."""
        if not self.extract_citations:
            return []
        
        try:
            import pdfx
            
            pdf = pdfx.PDFx(pdf_path)
            citations = pdf.get_citations()
            
            return [{"text": citation} for citation in citations]
            
        except Exception as e:
            self.logger.error(f"Error extracting citations: {e}")
            return [] 
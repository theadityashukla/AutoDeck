"""
Core SuperGrobid parser
Main orchestrator for the hybrid parsing pipeline
"""

import logging
from typing import Dict, List, Any, Optional
from pathlib import Path
import time

from .utils import load_config, setup_logging, is_pdf_file
from .extractors import PyMuPDFExtractor, NougatExtractor, LayoutParserExtractor
from .reconciliation import ReconciliationEngine
from .specialized import TableParser, EquationParser, ReferenceParser
from .output import OutputGenerator


class SuperGrobidParser:
    """Main SuperGrobid parser that orchestrates the entire pipeline."""
    
    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize SuperGrobid parser.
        
        Args:
            config_path: Path to configuration file
        """
        # Load configuration
        self.config = load_config(config_path)
        
        # Setup logging
        self.logger = setup_logging(self.config)
        self.logger.info("Initializing SuperGrobid parser")
        
        # Initialize components
        self.pymupdf_extractor = PyMuPDFExtractor(self.config)
        self.nougat_extractor = NougatExtractor(self.config)
        self.layout_extractor = LayoutParserExtractor(self.config)
        self.reconciliation_engine = ReconciliationEngine(self.config)
        self.table_parser = TableParser(self.config)
        self.equation_parser = EquationParser(self.config)
        self.reference_parser = ReferenceParser(self.config)
        self.output_generator = OutputGenerator(self.config)
        
        self.logger.info("SuperGrobid parser initialized successfully")
    
    def parse(self, pdf_path: str, output_format: str = "markdown", 
              output_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Parse a PDF document using the hybrid approach.
        
        Args:
            pdf_path: Path to input PDF file
            output_format: Desired output format ('markdown', 'json', 'xml')
            output_path: Path to save output file (optional)
            
        Returns:
            Dictionary containing parsing results and statistics
        """
        start_time = time.time()
        self.logger.info(f"Starting parsing of {pdf_path}")
        
        # Validate input
        if not is_pdf_file(pdf_path):
            raise ValueError(f"Input file is not a PDF: {pdf_path}")
        
        if not Path(pdf_path).exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        
        try:
            # Step 1: Extract raw text blocks with PyMuPDF
            self.logger.info("Step 1: Extracting text with PyMuPDF")
            pymupdf_output = self.pymupdf_extractor.extract(pdf_path)
            
            # Step 2: Generate structural scaffold with Nougat (if enabled)
            nougat_output = []
            if self.config.get('text_extraction', {}).get('nougat', {}).get('enabled', True):
                self.logger.info("Step 2: Generating structure with Nougat")
                nougat_output = self.nougat_extractor.extract(pdf_path)
            else:
                self.logger.info("Step 2: Nougat disabled, skipping structure generation")
            
            # Step 3: Detect layout regions with LayoutParser (if enabled)
            layout_output = []
            if self.config.get('layout_detection', {}).get('layoutparser', {}).get('enabled', True):
                self.logger.info("Step 3: Detecting layout regions")
                layout_output = self.layout_extractor.extract(pdf_path)
            else:
                self.logger.info("Step 3: LayoutParser disabled, skipping layout detection")
            
            # Step 4: Reconcile Nougat structure with PyMuPDF text
            self.logger.info("Step 4: Reconciling outputs")
            reconciled_output = self.reconciliation_engine.reconcile(
                nougat_output, pymupdf_output, layout_output
            )
            
            # Step 5: Parse specialized content (if enabled)
            self.logger.info("Step 5: Parsing specialized content")
            tables = []
            equations = []
            references = []
            
            if self.config.get('specialized_parsing', {}).get('tables', {}).get('enabled', True):
                tables = self._parse_tables(pdf_path, layout_output)
            
            if self.config.get('specialized_parsing', {}).get('equations', {}).get('enabled', True):
                equations = self._parse_equations(pdf_path, layout_output)
            
            if self.config.get('specialized_parsing', {}).get('references', {}).get('enabled', True):
                references = self._parse_references(pdf_path, layout_output)
            
            # Step 6: Generate final structured output
            self.logger.info("Step 6: Generating output")
            final_output = self.output_generator.generate_output(
                reconciled_output, tables, equations, references, output_format
            )
            
            # Save output if path provided
            if output_path:
                self.output_generator.save_output(final_output, output_path)
            
            # Calculate statistics
            parsing_time = time.time() - start_time
            reconciliation_stats = self.reconciliation_engine.get_statistics(reconciled_output)
            output_stats = self.output_generator.get_output_statistics(
                reconciled_output, tables, equations, references
            )
            
            # Compile results
            results = {
                "success": True,
                "input_file": pdf_path,
                "output_format": output_format,
                "output_path": output_path,
                "parsing_time": parsing_time,
                "statistics": {
                    "pymupdf_blocks": len(pymupdf_output),
                    "nougat_elements": len(nougat_output),
                    "layout_regions": len(layout_output),
                    "reconciled_elements": len(reconciled_output),
                    "tables": len(tables),
                    "equations": len(equations),
                    "references": len(references),
                    "reconciliation": reconciliation_stats,
                    "output": output_stats
                },
                "output": final_output
            }
            
            self.logger.info(f"Parsing completed successfully in {parsing_time:.2f} seconds")
            return results
            
        except Exception as e:
            self.logger.error(f"Error during parsing: {e}")
            return {
                "success": False,
                "error": str(e),
                "input_file": pdf_path,
                "parsing_time": time.time() - start_time
            }
    
    def _parse_tables(self, pdf_path: str, layout_output: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Parse tables from layout regions."""
        table_regions = self.layout_extractor.get_region_by_type(layout_output, "table")
        return self.table_parser.parse_tables(pdf_path, table_regions)
    
    def _parse_equations(self, pdf_path: str, layout_output: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Parse equations from layout regions."""
        equation_regions = self.layout_extractor.get_region_by_type(layout_output, "equation")
        return self.equation_parser.parse_equations(pdf_path, equation_regions)
    
    def _parse_references(self, pdf_path: str, layout_output: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Parse references from layout regions."""
        reference_regions = self.layout_extractor.get_region_by_type(layout_output, "references")
        return self.reference_parser.parse_references(pdf_path, reference_regions)
    
    def parse_batch(self, pdf_paths: List[str], output_format: str = "markdown", 
                   output_dir: str = "output") -> List[Dict[str, Any]]:
        """
        Parse multiple PDF files in batch.
        
        Args:
            pdf_paths: List of PDF file paths
            output_format: Desired output format
            output_dir: Directory to save output files
            
        Returns:
            List of parsing results
        """
        self.logger.info(f"Starting batch parsing of {len(pdf_paths)} files")
        
        results = []
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        for i, pdf_path in enumerate(pdf_paths):
            self.logger.info(f"Processing file {i+1}/{len(pdf_paths)}: {pdf_path}")
            
            # Generate output filename
            pdf_name = Path(pdf_path).stem
            output_file = output_path / f"{pdf_name}.{output_format}"
            
            # Parse single file
            result = self.parse(pdf_path, output_format, str(output_file))
            results.append(result)
            
            if not result["success"]:
                self.logger.error(f"Failed to parse {pdf_path}: {result.get('error', 'Unknown error')}")
        
        # Summary statistics
        successful = sum(1 for r in results if r["success"])
        total_time = sum(r.get("parsing_time", 0) for r in results)
        
        self.logger.info(f"Batch parsing completed: {successful}/{len(pdf_paths)} successful, "
                        f"total time: {total_time:.2f} seconds")
        
        return results
    
    def get_config(self) -> Dict[str, Any]:
        """Get current configuration."""
        return self.config.copy()
    
    def update_config(self, new_config: Dict[str, Any]) -> None:
        """Update configuration."""
        self.config.update(new_config)
        self.logger.info("Configuration updated")
        
        # Reinitialize components with new config
        self.reconciliation_engine = ReconciliationEngine(self.config)
        self.table_parser = TableParser(self.config)
        self.equation_parser = EquationParser(self.config)
        self.reference_parser = ReferenceParser(self.config)
        self.output_generator = OutputGenerator(self.config)
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics and capabilities."""
        return {
            "version": "1.0.0",
            "components": {
                "pymupdf": "Available",
                "nougat": "Available" if self.nougat_extractor.model else "Not available",
                "layoutparser": "Available" if self.layout_extractor.model else "Not available",
                "camelot": "Available",  # Will be checked at runtime
                "im2latex": "Not implemented",  # Placeholder
                "pdfx": "Available"  # Will be checked at runtime
            },
            "supported_formats": ["markdown", "json", "xml"],
            "configuration": {
                "similarity_method": self.config.get('reconciliation', {}).get('similarity', {}).get('method', 'levenshtein'),
                "similarity_threshold": self.config.get('reconciliation', {}).get('similarity', {}).get('threshold', 0.8),
                "output_formats": self.config.get('output', {}).get('formats', [])
            }
        } 
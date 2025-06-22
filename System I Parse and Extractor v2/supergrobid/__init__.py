"""
SuperGrobid - A Hybrid, Python-Native Scientific Document Parser

A modular, extensible document ingestion pipeline for scientific PDFs that combines
deterministic PDF parsing (PyMuPDF), visual layout modeling (Nougat), and specialized
content parsing to achieve high-fidelity, hallucination-free structured output.
"""

__version__ = "1.0.0"
__author__ = "SuperGrobid Team"

from .core import SuperGrobidParser
from .extractors import PyMuPDFExtractor, NougatExtractor, LayoutParserExtractor
from .reconciliation import ReconciliationEngine
from .specialized import TableParser, EquationParser, ReferenceParser
from .output import OutputGenerator

__all__ = [
    "SuperGrobidParser",
    "PyMuPDFExtractor", 
    "NougatExtractor",
    "LayoutParserExtractor",
    "ReconciliationEngine",
    "TableParser",
    "EquationParser", 
    "ReferenceParser",
    "OutputGenerator"
] 
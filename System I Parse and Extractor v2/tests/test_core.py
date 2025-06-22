"""
Unit tests for SuperGrobid core functionality
"""

import pytest
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch

from supergrobid import SuperGrobidParser
from supergrobid.utils import load_config, setup_logging, calculate_similarity


class TestSuperGrobidParser:
    """Test the main SuperGrobid parser class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Create a temporary config file
        self.temp_dir = tempfile.mkdtemp()
        self.config_path = os.path.join(self.temp_dir, "test_config.yaml")
        
        # Write minimal test config
        with open(self.config_path, "w") as f:
            f.write("""
logging:
  level: "INFO"
  console: true
text_extraction:
  pymupdf:
    extract_images: false
  nougat:
    model_name: "facebook/nougat-base"
reconciliation:
  similarity:
    method: "levenshtein"
    threshold: 0.8
output:
  formats: ["markdown", "json"]
  include_metadata: true
""")
    
    def teardown_method(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)
    
    def test_initialization(self):
        """Test parser initialization."""
        parser = SuperGrobidParser(self.config_path)
        assert parser is not None
        assert parser.config is not None
        assert parser.logger is not None
    
    def test_config_loading(self):
        """Test configuration loading."""
        config = load_config(self.config_path)
        assert config is not None
        assert "logging" in config
        assert "text_extraction" in config
        assert "reconciliation" in config
    
    def test_logging_setup(self):
        """Test logging setup."""
        config = load_config(self.config_path)
        logger = setup_logging(config)
        assert logger is not None
        assert logger.level <= 20  # INFO level
    
    @patch('supergrobid.extractors.PyMuPDFExtractor.extract')
    @patch('supergrobid.extractors.NougatExtractor.extract')
    @patch('supergrobid.extractors.LayoutParserExtractor.extract')
    def test_parse_success(self, mock_layout, mock_nougat, mock_pymupdf):
        """Test successful parsing."""
        # Mock the extractors
        mock_pymupdf.return_value = [
            {"page": 1, "text": "Test text", "bbox": [0, 0, 100, 20], "type": "text"}
        ]
        mock_nougat.return_value = [
            {"type": "paragraph", "text": "Test text", "page": 1}
        ]
        mock_layout.return_value = []
        
        # Create a temporary PDF file
        pdf_path = os.path.join(self.temp_dir, "test.pdf")
        with open(pdf_path, "w") as f:
            f.write("%PDF-1.4\n%Test PDF\n")
        
        parser = SuperGrobidParser(self.config_path)
        result = parser.parse(pdf_path, "markdown")
        
        assert result["success"] is True
        assert "parsing_time" in result
        assert "statistics" in result
        assert "output" in result
    
    def test_parse_invalid_file(self):
        """Test parsing with invalid file."""
        parser = SuperGrobidParser(self.config_path)
        result = parser.parse("nonexistent.pdf", "markdown")
        
        assert result["success"] is False
        assert "error" in result
    
    def test_parse_non_pdf_file(self):
        """Test parsing with non-PDF file."""
        # Create a text file
        txt_path = os.path.join(self.temp_dir, "test.txt")
        with open(txt_path, "w") as f:
            f.write("This is a text file")
        
        parser = SuperGrobidParser(self.config_path)
        result = parser.parse(txt_path, "markdown")
        
        assert result["success"] is False
        assert "error" in result
    
    def test_get_statistics(self):
        """Test getting system statistics."""
        parser = SuperGrobidParser(self.config_path)
        stats = parser.get_statistics()
        
        assert "version" in stats
        assert "components" in stats
        assert "supported_formats" in stats
        assert "configuration" in stats
    
    def test_update_config(self):
        """Test configuration updates."""
        parser = SuperGrobidParser(self.config_path)
        
        # Get original config
        original_config = parser.get_config()
        original_threshold = original_config["reconciliation"]["similarity"]["threshold"]
        
        # Update config
        new_config = {
            "reconciliation": {
                "similarity": {
                    "threshold": 0.9
                }
            }
        }
        parser.update_config(new_config)
        
        # Verify update
        updated_config = parser.get_config()
        assert updated_config["reconciliation"]["similarity"]["threshold"] == 0.9
        assert updated_config["reconciliation"]["similarity"]["threshold"] != original_threshold


class TestUtils:
    """Test utility functions."""
    
    def test_calculate_similarity_levenshtein(self):
        """Test Levenshtein similarity calculation."""
        # Test identical strings
        similarity = calculate_similarity("hello", "hello", "levenshtein")
        assert similarity == 1.0
        
        # Test similar strings
        similarity = calculate_similarity("hello", "helo", "levenshtein")
        assert 0.8 <= similarity <= 1.0
        
        # Test different strings
        similarity = calculate_similarity("hello", "world", "levenshtein")
        assert similarity < 0.5
        
        # Test empty strings
        similarity = calculate_similarity("", "", "levenshtein")
        assert similarity == 0.0
    
    def test_calculate_similarity_fuzzy(self):
        """Test fuzzy similarity calculation."""
        # Test partial matches
        similarity = calculate_similarity("hello world", "hello", "fuzzy")
        assert similarity > 0.5
        
        # Test substring matches
        similarity = calculate_similarity("hello world", "world", "fuzzy")
        assert similarity > 0.5
    
    def test_calculate_similarity_cosine(self):
        """Test cosine similarity calculation."""
        # Test similar content
        similarity = calculate_similarity("hello world", "hello world", "cosine")
        assert similarity == 1.0
        
        # Test different content
        similarity = calculate_similarity("hello world", "goodbye universe", "cosine")
        assert similarity < 1.0
    
    def test_calculate_similarity_invalid_method(self):
        """Test invalid similarity method."""
        with pytest.raises(ValueError):
            calculate_similarity("hello", "world", "invalid_method")


class TestConfiguration:
    """Test configuration handling."""
    
    def test_missing_config_file(self):
        """Test handling of missing config file."""
        with pytest.raises(FileNotFoundError):
            load_config("nonexistent_config.yaml")
    
    def test_invalid_yaml_config(self):
        """Test handling of invalid YAML config."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write("invalid: yaml: content: [")
            config_path = f.name
        
        try:
            with pytest.raises(Exception):  # Should raise YAML parsing error
                load_config(config_path)
        finally:
            os.unlink(config_path)


if __name__ == "__main__":
    pytest.main([__file__]) 
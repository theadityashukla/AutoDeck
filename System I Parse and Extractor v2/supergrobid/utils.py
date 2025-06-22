"""
Utility functions for SuperGrobid
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, List, Tuple
import numpy as np
from fuzzywuzzy import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """Load configuration from YAML file."""
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    return config


def setup_logging(config: Dict[str, Any]) -> logging.Logger:
    """Setup logging configuration."""
    log_config = config.get('logging', {})
    level = getattr(logging, log_config.get('level', 'INFO'))
    
    logger = logging.getLogger('supergrobid')
    logger.setLevel(level)
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Console handler
    if log_config.get('console', True):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(level)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
    
    # File handler
    if log_config.get('file'):
        file_handler = logging.FileHandler(log_config['file'])
        file_handler.setLevel(level)
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger


def calculate_similarity(text1: str, text2: str, method: str = "levenshtein") -> float:
    """
    Calculate similarity between two text strings.
    
    Args:
        text1: First text string
        text2: Second text string
        method: Similarity method ('levenshtein', 'cosine', 'fuzzy')
    
    Returns:
        Similarity score between 0 and 1
    """
    if not text1 or not text2:
        return 0.0
    
    if method == "levenshtein":
        return fuzz.ratio(text1.lower(), text2.lower()) / 100.0
    
    elif method == "fuzzy":
        return fuzz.partial_ratio(text1.lower(), text2.lower()) / 100.0
    
    elif method == "cosine":
        # TF-IDF vectorization for cosine similarity
        vectorizer = TfidfVectorizer(stop_words='english')
        try:
            tfidf_matrix = vectorizer.fit_transform([text1, text2])
            similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
            return float(similarity)
        except:
            return 0.0
    
    else:
        raise ValueError(f"Unknown similarity method: {method}")


def calculate_bbox_distance(bbox1: List[float], bbox2: List[float]) -> float:
    """
    Calculate Euclidean distance between two bounding boxes.
    
    Args:
        bbox1: [x0, y0, x1, y1] for first bounding box
        bbox2: [x0, y0, x1, y1] for second bounding box
    
    Returns:
        Distance in pixels
    """
    # Calculate center points
    center1 = [(bbox1[0] + bbox1[2]) / 2, (bbox1[1] + bbox1[3]) / 2]
    center2 = [(bbox2[0] + bbox2[2]) / 2, (bbox2[1] + bbox2[3]) / 2]
    
    # Euclidean distance
    return np.sqrt((center1[0] - center2[0])**2 + (center1[1] - center2[1])**2)


def merge_bboxes(bboxes: List[List[float]]) -> List[float]:
    """
    Merge multiple bounding boxes into a single bounding box.
    
    Args:
        bboxes: List of bounding boxes [x0, y0, x1, y1]
    
    Returns:
        Merged bounding box [x0, y0, x1, y1]
    """
    if not bboxes:
        return [0, 0, 0, 0]
    
    x0 = min(bbox[0] for bbox in bboxes)
    y0 = min(bbox[1] for bbox in bboxes)
    x1 = max(bbox[2] for bbox in bboxes)
    y1 = max(bbox[3] for bbox in bboxes)
    
    return [x0, y0, x1, y1]


def clean_text(text: str) -> str:
    """
    Clean and normalize text.
    
    Args:
        text: Raw text string
    
    Returns:
        Cleaned text string
    """
    if not text:
        return ""
    
    # Remove extra whitespace
    text = ' '.join(text.split())
    
    # Remove special characters that might cause issues
    text = text.replace('\x00', '')
    
    return text.strip()


def ensure_directory(path: str) -> None:
    """Ensure directory exists, create if it doesn't."""
    Path(path).mkdir(parents=True, exist_ok=True)


def get_file_extension(file_path: str) -> str:
    """Get file extension from file path."""
    return Path(file_path).suffix.lower()


def is_pdf_file(file_path: str) -> bool:
    """Check if file is a PDF."""
    return get_file_extension(file_path) == '.pdf'


def format_bbox(bbox: List[float]) -> str:
    """Format bounding box for display."""
    return f"[{bbox[0]:.1f}, {bbox[1]:.1f}, {bbox[2]:.1f}, {bbox[3]:.1f}]" 
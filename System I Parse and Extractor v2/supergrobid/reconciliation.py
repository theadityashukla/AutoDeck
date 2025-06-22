"""
Reconciliation engine for SuperGrobid
Aligns Nougat structural elements with PyMuPDF exact text content
"""

import logging
from typing import Dict, List, Any, Tuple, Optional
from .utils import calculate_similarity, calculate_bbox_distance, merge_bboxes


class ReconciliationEngine:
    """Reconcile Nougat structure with PyMuPDF text content."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.logger = logging.getLogger('supergrobid.reconciliation')
        
        # Get reconciliation settings
        recon_config = config.get('reconciliation', {})
        self.similarity_method = recon_config.get('similarity', {}).get('method', 'levenshtein')
        self.similarity_threshold = recon_config.get('similarity', {}).get('threshold', 0.8)
        self.hallucination_threshold = recon_config.get('hallucination', {}).get('detection_threshold', 0.6)
        self.discard_threshold = recon_config.get('hallucination', {}).get('discard_threshold', 0.4)
        self.orphan_max_distance = recon_config.get('orphan', {}).get('max_distance', 100)
    
    def reconcile(self, nougat_output: List[Dict[str, Any]], 
                  pymupdf_output: List[Dict[str, Any]], 
                  layout_output: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Reconcile Nougat structural elements with PyMuPDF text blocks.
        
        Args:
            nougat_output: Structured elements from Nougat
            pymupdf_output: Text blocks from PyMuPDF
            layout_output: Layout regions from LayoutParser
            
        Returns:
            Reconciled output with exact text and structure
        """
        self.logger.info("Starting reconciliation process")
        
        reconciled = []
        pymupdf_index = 0
        used_pymupdf_blocks = set()
        
        # Process each Nougat element
        for element in nougat_output:
            if element["type"] in ["header", "paragraph", "list"]:
                # Find matching PyMuPDF blocks for text elements
                matched_blocks, new_index, similarity = self._find_matching_blocks(
                    element["text"], pymupdf_output, pymupdf_index
                )
                
                if matched_blocks and similarity >= self.similarity_threshold:
                    # Use exact text from PyMuPDF
                    exact_text = " ".join([block["text"] for block in matched_blocks])
                    reconciled.append({
                        "type": element["type"],
                        "text": exact_text,
                        "blocks": matched_blocks,
                        "bbox": merge_bboxes([block["bbox"] for block in matched_blocks]),
                        "page": matched_blocks[0]["page"],
                        "confidence": similarity
                    })
                    
                    # Mark blocks as used
                    for i in range(pymupdf_index, new_index):
                        used_pymupdf_blocks.add(i)
                    
                    pymupdf_index = new_index
                    
                elif similarity >= self.hallucination_threshold:
                    # Keep element but mark as potential hallucination
                    self.logger.warning(f"Potential hallucination detected: {element['text'][:50]}...")
                    reconciled.append({
                        "type": element["type"],
                        "text": element["text"],
                        "blocks": [],
                        "bbox": element.get("bbox", [0, 0, 0, 0]),
                        "page": element.get("page", 1),
                        "confidence": similarity,
                        "hallucination_warning": True
                    })
                else:
                    # Discard element (below discard threshold)
                    self.logger.info(f"Discarding element with low similarity: {element['text'][:50]}...")
                    continue
            
            elif element["type"] in ["figure", "table"]:
                # Handle non-text elements
                non_text_element = self._handle_non_text_element(
                    element, pymupdf_output, pymupdf_index, layout_output
                )
                if non_text_element:
                    reconciled.append(non_text_element)
        
        # Handle orphan PyMuPDF blocks
        orphan_elements = self._handle_orphan_blocks(
            pymupdf_output, used_pymupdf_blocks, reconciled
        )
        reconciled.extend(orphan_elements)
        
        self.logger.info(f"Reconciliation complete: {len(reconciled)} elements")
        return reconciled
    
    def _find_matching_blocks(self, nougat_text: str, pymupdf_output: List[Dict[str, Any]], 
                             start_index: int) -> Tuple[List[Dict[str, Any]], int, float]:
        """
        Find PyMuPDF blocks that match a Nougat element.
        
        Returns:
            Tuple of (matched_blocks, new_index, best_similarity)
        """
        matched_blocks = []
        best_similarity = 0.0
        best_end_index = start_index
        
        # Sliding window approach to find best match
        for window_size in range(1, min(10, len(pymupdf_output) - start_index + 1)):
            for i in range(start_index, len(pymupdf_output) - window_size + 1):
                window_blocks = pymupdf_output[i:i + window_size]
                window_text = " ".join([block["text"] for block in window_blocks])
                
                similarity = calculate_similarity(nougat_text, window_text, self.similarity_method)
                
                if similarity > best_similarity:
                    best_similarity = similarity
                    matched_blocks = window_blocks
                    best_end_index = i + window_size
        
        return matched_blocks, best_end_index, best_similarity
    
    def _handle_non_text_element(self, element: Dict[str, Any], 
                                pymupdf_output: List[Dict[str, Any]], 
                                pymupdf_index: int,
                                layout_output: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Handle non-text elements like figures and tables."""
        
        # Find surrounding text blocks to infer bounding box
        prev_blocks = self._find_previous_text_blocks(pymupdf_output, pymupdf_index)
        next_blocks = self._find_next_text_blocks(pymupdf_output, pymupdf_index)
        
        if prev_blocks or next_blocks:
            # Calculate inferred bounding box
            bbox = self._calculate_element_bbox(prev_blocks, next_blocks)
            
            return {
                "type": element["type"],
                "text": element.get("text", ""),
                "bbox": bbox,
                "page": element.get("page", 1),
                "confidence": element.get("confidence", 1.0),
                "surrounding_blocks": {
                    "previous": prev_blocks,
                    "next": next_blocks
                }
            }
        
        return None
    
    def _find_previous_text_blocks(self, pymupdf_output: List[Dict[str, Any]], 
                                  current_index: int, max_blocks: int = 3) -> List[Dict[str, Any]]:
        """Find text blocks before current position."""
        start_index = max(0, current_index - max_blocks)
        return pymupdf_output[start_index:current_index]
    
    def _find_next_text_blocks(self, pymupdf_output: List[Dict[str, Any]], 
                              current_index: int, max_blocks: int = 3) -> List[Dict[str, Any]]:
        """Find text blocks after current position."""
        end_index = min(len(pymupdf_output), current_index + max_blocks)
        return pymupdf_output[current_index:end_index]
    
    def _calculate_element_bbox(self, prev_blocks: List[Dict[str, Any]], 
                               next_blocks: List[Dict[str, Any]]) -> List[float]:
        """Calculate bounding box for non-text element based on surrounding text."""
        if not prev_blocks and not next_blocks:
            return [0, 0, 0, 0]
        
        all_blocks = prev_blocks + next_blocks
        return merge_bboxes([block["bbox"] for block in all_blocks])
    
    def _handle_orphan_blocks(self, pymupdf_output: List[Dict[str, Any]], 
                             used_blocks: set, 
                             reconciled: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Handle PyMuPDF blocks that weren't matched to any Nougat element."""
        orphan_elements = []
        
        for i, block in enumerate(pymupdf_output):
            if i not in used_blocks and block["text"].strip():
                # Try to append to nearest reconciled element
                if reconciled:
                    nearest_element = self._find_nearest_element(block, reconciled)
                    if nearest_element and self._is_within_distance(block, nearest_element):
                        # Append to existing element
                        nearest_element["text"] += " " + block["text"]
                        nearest_element["blocks"].append(block)
                        nearest_element["bbox"] = merge_bboxes([
                            nearest_element["bbox"], block["bbox"]
                        ])
                    else:
                        # Create new orphan element
                        orphan_elements.append({
                            "type": "orphan",
                            "text": block["text"],
                            "blocks": [block],
                            "bbox": block["bbox"],
                            "page": block["page"],
                            "confidence": 1.0
                        })
                else:
                    # No reconciled elements yet, create new orphan
                    orphan_elements.append({
                        "type": "orphan",
                        "text": block["text"],
                        "blocks": [block],
                        "bbox": block["bbox"],
                        "page": block["page"],
                        "confidence": 1.0
                    })
        
        self.logger.info(f"Handled {len(orphan_elements)} orphan blocks")
        return orphan_elements
    
    def _find_nearest_element(self, block: Dict[str, Any], 
                             reconciled: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Find the nearest reconciled element to an orphan block."""
        if not reconciled:
            return None
        
        nearest_element = None
        min_distance = float('inf')
        
        for element in reconciled:
            if element["page"] == block["page"]:
                distance = calculate_bbox_distance(block["bbox"], element["bbox"])
                if distance < min_distance:
                    min_distance = distance
                    nearest_element = element
        
        return nearest_element
    
    def _is_within_distance(self, block: Dict[str, Any], element: Dict[str, Any]) -> bool:
        """Check if block is within acceptable distance of element."""
        if block["page"] != element["page"]:
            return False
        
        distance = calculate_bbox_distance(block["bbox"], element["bbox"])
        return distance <= self.orphan_max_distance
    
    def get_statistics(self, reconciled: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Get statistics about the reconciliation process."""
        stats = {
            "total_elements": len(reconciled),
            "text_elements": len([e for e in reconciled if e["type"] in ["header", "paragraph", "list"]]),
            "non_text_elements": len([e for e in reconciled if e["type"] in ["figure", "table"]]),
            "orphan_elements": len([e for e in reconciled if e["type"] == "orphan"]),
            "hallucination_warnings": len([e for e in reconciled if e.get("hallucination_warning", False)]),
            "average_confidence": sum(e.get("confidence", 1.0) for e in reconciled) / len(reconciled) if reconciled else 0
        }
        
        return stats 
"""
AgenticPipeline: Orchestrates automated slide generation for entire decks.

Uses SlideProcessor for individual slide processing.
This is now a thin orchestration layer.
"""

import logging
import os
from typing import Dict, Any, Generator, Optional

from autodeck_core.config import update_config, get_config
from autodeck_core.slide_processor import (
    SlideProcessor,
    SlideResult,
    SlideStatus,
    IterationRecord,
    get_slide_processor
)

# Re-export for backward compatibility
__all__ = ['AgenticPipeline', 'SlideResult', 'SlideStatus', 'IterationRecord']


class AgenticPipeline:
    """
    Orchestrates deck generation by processing each slide through SlideProcessor.
    
    This is now a thin wrapper that:
    1. Iterates over slides in the outline
    2. Delegates each slide to SlideProcessor
    3. Yields results as they complete
    """
    
    def __init__(
        self, 
        output_dir: str = "generated_decks", 
        max_iterations: int = 3, 
        target_score: float = 8.0,
        template_path: Optional[str] = None
    ):
        # Update global config
        update_config(
            output_dir=output_dir,
            max_iterations=max_iterations,
            target_score=target_score,
            template_path=template_path
        )
        
        self.output_dir = output_dir
        self.max_iterations = max_iterations
        self.target_score = target_score
        
        self.logger = logging.getLogger("AgenticPipeline")
        
        # Use shared SlideProcessor
        self._processor: Optional[SlideProcessor] = None
        
        os.makedirs(output_dir, exist_ok=True)
    
    @property
    def processor(self) -> SlideProcessor:
        """Get the SlideProcessor instance."""
        if self._processor is None:
            self._processor = SlideProcessor(
                max_iterations=self.max_iterations,
                target_score=self.target_score
            )
        return self._processor
    
    def generate_deck(self, session_data: Dict[str, Any]) -> Generator[SlideResult, None, None]:
        """
        Generate entire deck, yielding each slide as it's finalized.
        
        Args:
            session_data: Session containing outline and content.
            
        Yields:
            SlideResult for each finalized slide.
        """
        outline = session_data.get("outline", [])
        content_dict = session_data.get("content", {})
        
        self.logger.info(f"Starting deck generation: {len(outline)} slides")
        
        for index, outline_item in enumerate(outline):
            content_key = str(index)
            content_item = content_dict.get(content_key, {})
            
            # Use outline title if content title missing
            if not content_item.get("title"):
                content_item["title"] = outline_item.get("title", f"Slide {index + 1}")
            
            # Process this slide through the shared processor
            result = self.processor.process_slide(
                content=content_item,
                index=index,
                title=content_item.get("title")
            )
            
            yield result
        
        self.logger.info(f"Deck generation complete: {len(outline)} slides")
    
    def approve_slide(self, result: SlideResult, comments: Optional[list] = None) -> SlideResult:
        """Mark a slide as approved by human reviewer."""
        result.status = SlideStatus.APPROVED
        if comments:
            result.human_comments.extend(comments)
        return result

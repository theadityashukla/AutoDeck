"""
SlideProcessor - Unified slide processing with iteration history.

This is the single source of truth for processing a slide through:
render → analyze → fix → repeat

Used by:
- Single Slide Tools (Render & Analyze button)
- AgenticPipeline (for each slide in deck)
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum

from autodeck_core.config import get_config
from autodeck_core.slide_factory import get_slide_factory
from autodeck_core.agents.design_agent import DesignAgent


class SlideStatus(Enum):
    PENDING = "pending"
    GENERATING = "generating"
    IMPROVING = "improving"
    FINALIZED = "finalized"
    APPROVED = "approved"


@dataclass
class IterationRecord:
    """Record of a single improvement iteration."""
    iteration: int
    score: float
    issues: List[str]
    suggested_actions: List[str]
    actions_applied: List[str]
    content_before: Dict[str, Any]
    content_after: Dict[str, Any]
    raw_response: str = ""  # Raw LLM response for debugging


@dataclass
class SlideResult:
    """Result of processing a single slide."""
    index: int
    title: str
    status: SlideStatus
    content: Dict[str, Any]
    final_score: float = 0.0
    iterations: int = 0
    image_path: Optional[str] = None
    critique: Optional[Dict[str, Any]] = None
    human_comments: List[str] = field(default_factory=list)
    iteration_history: List[IterationRecord] = field(default_factory=list)


class SlideProcessor:
    """
    Processes a single slide through the full improvement cycle.
    
    Usage:
        processor = SlideProcessor()
        result = processor.process_slide(content, index=0)
        # result.iteration_history contains all feedback rounds
    """
    
    def __init__(
        self,
        max_iterations: int = None,
        target_score: float = None
    ):
        """
        Initialize SlideProcessor.
        
        Args:
            max_iterations: Override config's max_iterations if provided.
            target_score: Override config's target_score if provided.
        """
        self.config = get_config()
        self.max_iterations = max_iterations or self.config.max_iterations
        self.target_score = target_score or self.config.target_score
        
        self.logger = logging.getLogger("SlideProcessor")
        
        # Lazy-init components
        self._design_agent: Optional[DesignAgent] = None
        self._slide_factory = None
    
    @property
    def design_agent(self) -> DesignAgent:
        if self._design_agent is None:
            self._design_agent = DesignAgent()
        return self._design_agent
    
    @property
    def slide_factory(self):
        if self._slide_factory is None:
            self._slide_factory = get_slide_factory()
        return self._slide_factory
    
    def process_slide(
        self,
        content: Dict[str, Any],
        index: int = 0,
        title: str = None
    ) -> SlideResult:
        """
        Process a slide through render → analyze → fix cycle.
        
        Args:
            content: Slide content dict with 'title', 'bullet_points', etc.
            index: Slide index (for logging).
            title: Override title for result.
            
        Returns:
            SlideResult with iteration_history containing all feedback rounds.
        """
        slide_title = title or content.get("title", f"Slide {index + 1}")
        
        result = SlideResult(
            index=index,
            title=slide_title,
            status=SlideStatus.IMPROVING,
            content=content.copy()
        )
        
        for iteration in range(self.max_iterations):
            result.iterations = iteration + 1
            
            # Store content before this iteration
            content_before = result.content.copy()
            
            # 0. DETERMINISTIC FIT: Apply auto-sizing before render
            from autodeck_core.text_fitter import auto_fit_slide
            result.content = auto_fit_slide(result.content)
            
            # 0b. Set template flag for vision model constraints
            from autodeck_core.config import get_config
            if get_config().template_path:
                result.content["_has_template"] = True

            
            # 1. Render slide to image
            try:
                result.image_path = self.slide_factory.render_to_image(result.content)
            except Exception as e:
                self.logger.error(f"Render failed: {e}")
                result.status = SlideStatus.FINALIZED
                result.final_score = 5.0
                return result
            
            if not result.image_path:
                self.logger.error("Render returned None")
                result.status = SlideStatus.FINALIZED
                result.final_score = 5.0
                return result
            
            # 2. Analyze with vision model
            critique = self.design_agent.analyze_slide(result.image_path, result.content)
            result.critique = critique
            
            score = critique.get("score", 0)
            issues = critique.get("issues", [])
            suggested_actions = critique.get("suggested_actions", [])
            raw_response = critique.get("_raw_response", "")
            result.final_score = score
            
            self.logger.info(f"Slide {index+1} iteration {iteration+1}: score={score}, issues={len(issues)}, suggestions={len(suggested_actions)}")
            
            # 3. Check if good enough OR no suggestions to apply
            # Exit early if score is good OR if there are no suggestions (even on first iteration)
            if score >= self.target_score or not suggested_actions:
                # Record final iteration
                reason = "Target score reached" if score >= self.target_score else "No suggestions to apply"
                record = IterationRecord(
                    iteration=iteration + 1,
                    score=score,
                    issues=issues,
                    suggested_actions=suggested_actions,
                    actions_applied=[f"{reason} - stopping"],
                    content_before=content_before,
                    content_after=result.content,
                    raw_response=raw_response
                )
                result.iteration_history.append(record)
                result.status = SlideStatus.FINALIZED
                self.logger.info(f"Slide {index+1} finalized: {reason}, score={score}")
                return result
            
            # 4. Apply fixes if not at max iterations
            actions_applied = []
            if iteration < self.max_iterations - 1:
                content_after_fixes = self.design_agent.apply_fixes(result.content, critique)
                
                # Track what changed
                if content_after_fixes.get("visual_overrides") != result.content.get("visual_overrides"):
                    actions_applied.append(f"Updated visual_overrides: {content_after_fixes.get('visual_overrides')}")
                if content_after_fixes.get("forced_layout") != result.content.get("forced_layout"):
                    actions_applied.append(f"Changed layout to: {content_after_fixes.get('forced_layout')}")
                if content_after_fixes.get("bullet_points") != result.content.get("bullet_points"):
                    actions_applied.append("Modified bullet points")
                if not actions_applied:
                    actions_applied = ["No changes made"]
                
                result.content = content_after_fixes
            else:
                actions_applied = ["Max iterations reached - no more fixes"]
            
            # Record this iteration
            record = IterationRecord(
                iteration=iteration + 1,
                score=score,
                issues=issues,
                suggested_actions=suggested_actions,
                actions_applied=actions_applied,
                content_before=content_before,
                content_after=result.content,
                raw_response=raw_response
            )
            result.iteration_history.append(record)
        
        # Max iterations reached
        result.status = SlideStatus.FINALIZED
        self.logger.info(f"Slide {index+1} finalized after {self.max_iterations} iterations, score={result.final_score}")
        
        return result


# Module-level singleton
_processor: Optional[SlideProcessor] = None


def get_slide_processor() -> SlideProcessor:
    """Get the global SlideProcessor instance."""
    global _processor
    if _processor is None:
        _processor = SlideProcessor()
    return _processor

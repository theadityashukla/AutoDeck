"""
Deterministic text fitting algorithm for PowerPoint slides.

Calculates available space and automatically adjusts:
1. Font size based on text length
2. Layout based on bullet count
3. Text wrapping based on available width

No LLM required - pure arithmetic.
"""

from dataclasses import dataclass
from typing import Dict, Any, List, Tuple, Optional
import math


@dataclass
class SlideConstraints:
    """Slide dimension constraints in points (1 inch = 72 points)."""
    width_pt: float = 720  # 10 inches
    height_pt: float = 540  # 7.5 inches
    
    # Content area (excluding margins)
    margin_left_pt: float = 72  # 1 inch
    margin_right_pt: float = 72
    margin_top_pt: float = 108  # 1.5 inches (for title)
    margin_bottom_pt: float = 36  # 0.5 inch
    
    # Title constraints
    title_height_pt: float = 54  # ~0.75 inches
    
    @property
    def content_width(self) -> float:
        return self.width_pt - self.margin_left_pt - self.margin_right_pt
    
    @property
    def content_height(self) -> float:
        return self.height_pt - self.margin_top_pt - self.margin_bottom_pt


@dataclass
class FontMetrics:
    """Approximate character metrics for common fonts."""
    # Average character width as fraction of point size
    # Aptos/Calibri are about 0.5-0.55 of point size per char width
    char_width_ratio: float = 0.55
    line_height_ratio: float = 1.3  # Line height as multiple of font size
    
    def chars_per_line(self, font_size_pt: float, line_width_pt: float) -> int:
        """Calculate how many characters fit in a line."""
        char_width = font_size_pt * self.char_width_ratio
        return int(line_width_pt / char_width)
    
    def lines_per_area(self, font_size_pt: float, area_height_pt: float) -> int:
        """Calculate how many lines fit in given height."""
        line_height = font_size_pt * self.line_height_ratio
        return int(area_height_pt / line_height)


class TextFitter:
    """Deterministic text fitting algorithm."""
    
    def __init__(self, constraints: Optional[SlideConstraints] = None):
        self.constraints = constraints or SlideConstraints()
        self.metrics = FontMetrics()
        
        # Font size limits
        self.MIN_FONT_SIZE = 10
        self.MAX_FONT_SIZE = 24
        self.DEFAULT_FONT_SIZE = 18
        
        # Title font limits
        self.MIN_TITLE_FONT = 18
        self.MAX_TITLE_FONT = 32
        
    def calculate_optimal_font_size(self, bullet_points: List[str], start_font: int = None) -> int:
        """
        Calculate the largest font size that fits all content.
        
        Pure arithmetic - no LLM needed.
        """
        if not bullet_points:
            return self.DEFAULT_FONT_SIZE
            
        start_font = start_font or self.MAX_FONT_SIZE
        
        for font_size in range(start_font, self.MIN_FONT_SIZE - 1, -1):
            if self._content_fits(bullet_points, font_size):
                return font_size
        
        # Even minimum font doesn't fit - return minimum anyway
        return self.MIN_FONT_SIZE
    
    def _content_fits(self, bullet_points: List[str], font_size: int) -> bool:
        """Check if content fits with given font size."""
        available_height = self.constraints.content_height
        available_width = self.constraints.content_width
        
        chars_per_line = self.metrics.chars_per_line(font_size, available_width)
        max_lines = self.metrics.lines_per_area(font_size, available_height)
        
        total_lines_needed = 0
        line_spacing_lines = 0.5  # Extra spacing between bullets
        
        for bullet in bullet_points:
            # Clean bullet text
            text = bullet.strip()
            if text.startswith("- ") or text.startswith("* "):
                text = text[2:]
            
            # Calculate lines needed for this bullet
            lines_needed = math.ceil(len(text) / chars_per_line)
            total_lines_needed += lines_needed + line_spacing_lines
        
        return total_lines_needed <= max_lines
    
    def fit_content(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply deterministic fitting to slide content.
        
        Returns modified content with visual_overrides set.
        """
        result = content.copy()
        bullet_points = content.get("bullet_points", [])
        
        if not bullet_points:
            return result
        
        # Get current font size or default
        current_overrides = content.get("visual_overrides", {})
        current_font = current_overrides.get("font_size", self.DEFAULT_FONT_SIZE)
        
        # Calculate optimal font size
        optimal_font = self.calculate_optimal_font_size(bullet_points, current_font)
        
        # Check if we need layout change
        if len(bullet_points) > 6 and optimal_font <= self.MIN_FONT_SIZE:
            # Too many bullets - suggest two-column
            result["forced_layout"] = "two_column"
            # Recalculate with half width
            self.constraints.content_width /= 2
            optimal_font = self.calculate_optimal_font_size(bullet_points[:3], self.MAX_FONT_SIZE)
            self.constraints.content_width *= 2  # Restore
        
        # Update visual overrides
        if "visual_overrides" not in result:
            result["visual_overrides"] = {}
        result["visual_overrides"]["font_size"] = optimal_font
        
        # Mark that font has been auto-fitted (so vision model knows not to suggest increase)
        result["visual_overrides"]["_auto_fitted"] = True
        
        return result

    
    def estimate_overflow(self, content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Estimate if content will overflow and by how much.
        
        Returns estimation metrics without LLM.
        """
        bullet_points = content.get("bullet_points", [])
        current_font = content.get("visual_overrides", {}).get("font_size", self.DEFAULT_FONT_SIZE)
        
        if not bullet_points:
            return {"will_overflow": False, "excess_lines": 0}
        
        available_height = self.constraints.content_height
        chars_per_line = self.metrics.chars_per_line(current_font, self.constraints.content_width)
        max_lines = self.metrics.lines_per_area(current_font, available_height)
        
        total_lines = 0
        for bullet in bullet_points:
            text = bullet.strip()
            if text.startswith("- ") or text.startswith("* "):
                text = text[2:]
            lines = math.ceil(len(text) / chars_per_line)
            total_lines += lines + 0.5
        
        excess = total_lines - max_lines
        
        return {
            "will_overflow": excess > 0,
            "excess_lines": max(0, excess),
            "current_lines": total_lines,
            "max_lines": max_lines,
            "suggested_font_size": self.calculate_optimal_font_size(bullet_points, current_font)
        }


def auto_fit_slide(content: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convenience function to auto-fit slide content.
    
    Call this BEFORE generating the PPTX to ensure content fits.
    """
    fitter = TextFitter()
    return fitter.fit_content(content)

"""
SlideRenderer - Thin wrapper for backward compatibility.

Now delegates to SlideFactory for actual rendering.
"""

import logging
from typing import Optional, Dict

from autodeck_core.config import get_config, update_config
from autodeck_core.slide_factory import get_slide_factory


class SlideRenderer:
    """
    Renders slides to images.
    
    Note: This is now a thin wrapper around SlideFactory for backward compatibility.
    New code should use SlideFactory directly.
    """
    
    def __init__(
        self, 
        output_dir: str = "rendered_slides", 
        headless_cmd: str = "/Applications/LibreOffice.app/Contents/MacOS/soffice", 
        template_path: Optional[str] = None
    ):
        """
        Initializes the SlideRenderer.
        
        Args:
            output_dir: Directory for rendered images.
            headless_cmd: Path to LibreOffice.
            template_path: Optional PPTX template path.
        """
        # Update global config with provided values
        update_config(
            rendered_slides_dir=output_dir,
            libreoffice_path=headless_cmd,
            template_path=template_path
        )
        
        self.factory = get_slide_factory()
        self.factory.cleanup_old_renders(max_age_hours=1)
        
        self.logger = logging.getLogger("SlideRenderer")
    
    def render_slide(self, slide_data: Dict, theme: str = "Default") -> Optional[str]:
        """
        Renders a single slide to an image.
        
        Args:
            slide_data: Content dictionary for the slide.
            theme: Theme name (currently unused, kept for compatibility).
            
        Returns:
            Path to PNG image, or None if failed.
        """
        return self.factory.render_to_image(slide_data)

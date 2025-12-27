"""
SlideFactory - Single point for slide creation and rendering.

Consolidates slide creation logic that was previously duplicated in:
- PPTGenerator._create_slide()
- SlideRenderer.render_slide() (via mock session)
- AgenticPipeline._create_temp_slide()
"""

import os
import uuid
import time
import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

from autodeck_core.config import get_config


class SlideFactory:
    """
    Unified interface for creating and rendering slides.
    
    Usage:
        factory = SlideFactory()
        
        # Create a slide in a presentation
        slide = factory.create_slide(prs, content)
        
        # Render content directly to image (handles temp PPTX internally)
        image_path = factory.render_to_image(content)
    """
    
    def __init__(self):
        self.config = get_config()
        self.logger = logging.getLogger("SlideFactory")
        
    def render_to_image(self, content: Dict[str, Any]) -> Optional[str]:
        """
        Render slide content directly to PNG.
        
        Creates temporary PPTX → PDF → PNG and cleans up.
        
        Args:
            content: Slide content dict with 'title', 'bullet_points', etc.
            
        Returns:
            Path to PNG image, or None if failed.
        """
        from autodeck_core.ppt_generator import PPTGenerator
        
        output_dir = Path(self.config.rendered_slides_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        temp_id = str(uuid.uuid4())[:8]
        temp_pptx = output_dir / f"temp_render_{temp_id}.pptx"
        temp_pdf = output_dir / f"temp_render_{temp_id}.pdf"
        output_png = output_dir / f"temp_render_{temp_id}.png"
        
        try:
            # 1. Create single-slide PPTX
            mock_session = {
                "name": "Temp Render",
                "outline": [{"title": content.get("title", "Preview"), "description": ""}],
                "content": {"0": content}
            }
            
            generator = PPTGenerator(
                output_path=str(temp_pptx),
                template_path=self.config.template_path
            )
            generator.generate(mock_session, include_title_slide=False)
            
            if not temp_pptx.exists():
                self.logger.error("Failed to create temp PPTX")
                return None
            
            # 2. Convert to PDF (better theme rendering)
            cmd = [
                self.config.libreoffice_path,
                "--headless",
                "--convert-to", "pdf",
                "--outdir", str(output_dir),
                str(temp_pptx)
            ]
            
            start = time.time()
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            
            if not temp_pdf.exists():
                self.logger.error(f"PDF conversion failed: {result.stderr}")
                return None
            
            # 3. Convert PDF to PNG
            try:
                from pdf2image import convert_from_path
                images = convert_from_path(str(temp_pdf), dpi=150, first_page=1, last_page=1)
                
                if images:
                    images[0].save(str(output_png), "PNG")
                    self.logger.info(f"Rendered in {time.time() - start:.2f}s")
                else:
                    self.logger.error("pdf2image returned no images")
                    return None
                    
            except ImportError:
                # Fallback to direct PNG (won't have proper backgrounds)
                self.logger.warning("pdf2image not available, using fallback")
                cmd = [
                    self.config.libreoffice_path,
                    "--headless",
                    "--convert-to", "png",
                    "--outdir", str(output_dir),
                    str(temp_pptx)
                ]
                subprocess.run(cmd, capture_output=True, text=True)
            
            # 4. Cleanup temp files
            if temp_pptx.exists():
                os.remove(temp_pptx)
            if temp_pdf.exists():
                os.remove(temp_pdf)
            
            if output_png.exists():
                return str(output_png)
            return None
            
        except Exception as e:
            self.logger.error(f"Render failed: {e}")
            # Cleanup on error
            for f in [temp_pptx, temp_pdf]:
                if f.exists():
                    os.remove(f)
            return None
    
    def cleanup_old_renders(self, max_age_hours: int = 1):
        """Remove temp render files older than max_age_hours."""
        output_dir = Path(self.config.rendered_slides_dir)
        if not output_dir.exists():
            return
            
        cutoff = time.time() - (max_age_hours * 3600)
        count = 0
        
        for f in output_dir.glob("temp_render_*"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink()
                    count += 1
            except Exception:
                pass
                
        if count > 0:
            self.logger.info(f"Cleaned up {count} old temp files")


# Module-level convenience function
_factory: Optional[SlideFactory] = None


def get_slide_factory() -> SlideFactory:
    """Get the global SlideFactory instance."""
    global _factory
    if _factory is None:
        _factory = SlideFactory()
    return _factory

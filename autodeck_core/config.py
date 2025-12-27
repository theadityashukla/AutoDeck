"""
AutoDeck Configuration - Single source of truth for all settings.
"""

from dataclasses import dataclass, field
from typing import Optional
import os


@dataclass
class AutoDeckConfig:
    """Central configuration for AutoDeck."""
    
    # Template
    template_path: Optional[str] = None
    
    # Output
    output_dir: str = "generated_decks"
    rendered_slides_dir: str = "rendered_slides"
    
    # Pipeline settings
    max_iterations: int = 3
    target_score: float = 8.0
    
    # Rendering
    libreoffice_path: str = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    
    def __post_init__(self):
        """Create directories if they don't exist."""
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.rendered_slides_dir, exist_ok=True)


# Global singleton instance
_config: Optional[AutoDeckConfig] = None


def get_config() -> AutoDeckConfig:
    """Get the global config instance."""
    global _config
    if _config is None:
        _config = AutoDeckConfig()
    return _config


def set_config(config: AutoDeckConfig) -> None:
    """Set the global config instance."""
    global _config
    _config = config


def update_config(**kwargs) -> AutoDeckConfig:
    """Update config with new values."""
    global _config
    if _config is None:
        _config = AutoDeckConfig(**kwargs)
    else:
        for key, value in kwargs.items():
            if hasattr(_config, key):
                setattr(_config, key, value)
    return _config

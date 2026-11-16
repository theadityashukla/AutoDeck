"""
Gemini API Client for Vision and Text Generation

Security Notes:
- API key is loaded from environment variable GEMINI_API_KEY
- Never commit API keys to version control
- Use .env file for local development (add to .gitignore)
"""

import os
from typing import Optional, List
from autodeck_core.logger import setup_logger

logger = setup_logger("GeminiClient")


class GeminiClient:
    """
    Secure client for Google Gemini API.
    
    API key must be set via environment variable GEMINI_API_KEY
    or passed to constructor (not recommended for production).
    """
    
    _instance = None
    
    def __new__(cls, api_key: Optional[str] = None):
        if cls._instance is None:
            cls._instance = super(GeminiClient, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance
    
    def __init__(self, api_key: Optional[str] = None):
        if self.initialized:
            return
            
        # Security: Prefer environment variable over passed key
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        
        if not self.api_key:
            logger.warning("GEMINI_API_KEY not set. Vision features will be disabled.")
            
        self.client = None
        self.initialized = True
        
    def _ensure_client(self):
        """Lazy initialization of the Gemini client."""
        if self.client is not None:
            return True
            
        if not self.api_key:
            logger.error("Cannot initialize Gemini client: API key not set")
            return False
        
        try:
            from google import genai
            # Configure the client with the API key
            self.client = genai.Client(api_key=self.api_key)
            logger.info("Gemini client initialized successfully")
            return True
        except ImportError:
            logger.error("google-genai package not installed. Run: pip install google-genai")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}")
            return False
    
    def generate_with_image(
        self,
        prompt: str,
        image_path: str,
        model: str = "gemini-3-flash-preview",
        temperature: float = 0.3
    ) -> Optional[str]:
        """
        Generate content using Gemini with an image input.
        
        Args:
            prompt: Text prompt to send with the image
            image_path: Path to the image file
            model: Gemini model to use (default: gemini-2.5-flash for vision)
            temperature: Generation temperature (lower = more focused)
            
        Returns:
            Generated text response, or None on error
        """
        if not self._ensure_client():
            return None
            
        try:
            from google.genai import types
            
            # Read image file
            with open(image_path, 'rb') as f:
                image_bytes = f.read()
            
            # Determine MIME type from extension
            ext = image_path.lower().split('.')[-1]
            mime_type = {
                'png': 'image/png',
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'gif': 'image/gif',
                'webp': 'image/webp'
            }.get(ext, 'image/png')
            
            # Generate content with image
            response = self.client.models.generate_content(
                model=model,
                contents=[
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type=mime_type,
                    ),
                    prompt
                ],
                config=types.GenerateContentConfig(
                    temperature=temperature,
                )
            )
            
            return response.text
            
        except Exception as e:
            logger.error(f"Gemini vision generation failed: {e}")
            return None
    
    def generate(
        self,
        prompt: str,
        model: str = "gemini-3-flash-preview",
        max_tokens: int = 1024,
        temperature: float = 0.7
    ) -> Optional[str]:
        """
        Generate text content using Gemini.
        
        Args:
            prompt: Text prompt
            model: Gemini model to use
            max_tokens: Maximum tokens to generate
            temperature: Generation temperature
            
        Returns:
            Generated text response, or None on error
        """
        if not self._ensure_client():
            return None
            
        try:
            from google.genai import types
            
            response = self.client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                )
            )
            
            return response.text
            
        except Exception as e:
            logger.error(f"Gemini text generation failed: {e}")
            return None
    
    def is_available(self) -> bool:
        """Check if Gemini API is available and configured."""
        return self.api_key is not None and self._ensure_client()

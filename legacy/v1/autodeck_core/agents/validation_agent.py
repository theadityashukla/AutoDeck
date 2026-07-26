import json
import os
from typing import Dict, List, Any, Optional
from autodeck_core.llm.gemma_client import GemmaClient
from autodeck_core.logger import setup_logger

class ValidationAgent:
    def __init__(self):
        self.llm = GemmaClient()
        self.logger = setup_logger("ValidationAgent")

    def validate_image(self, image_path: str, slide_context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates image quality using OpenCV (Blur, Brightness, Contrast).
        """
        self.logger.info(f"Validating image: {image_path}")
        
        try:
            import cv2
            import numpy as np
            
            if not os.path.exists(image_path):
                return {"is_valid": False, "quality_score": 0, "issues": ["Image file not found"], "improvement_suggestions": ["Provide a valid image path"]}

            img = cv2.imread(image_path)
            if img is None:
                return {"is_valid": False, "quality_score": 0, "issues": ["Image file could not be read."]}
            
            issues = []
            suggestions = []
            score = 10
            
            # 1. Check Resolution
            h, w, _ = img.shape
            if h < 480 or w < 640:
                score -= 3
                issues.append(f"Low resolution: {w}x{h}")
                suggestions.append("Use a higher resolution image (at least 640x480).")
            
            # 2. Check Blur (Laplacian Variance)
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            variance = cv2.Laplacian(gray, cv2.CV_64F).var()
            is_blurry = variance < 100
            if is_blurry:
                score -= 4
                issues.append("Image is blurry.")
                suggestions.append("Use a sharper image.")
                
            # 3. Check Brightness
            brightness = np.mean(gray)
            if brightness < 40:
                score -= 2
                issues.append("Image is too dark.")
                suggestions.append("Use a brighter image.")
            elif brightness > 220:
                score -= 2
                issues.append("Image is too bright/washed out.")
            
            # Determine validity
            is_valid = score >= 5
            
            result = {
                "is_valid": is_valid,
                "quality_score": score,
                "is_clear": not is_blurry,
                "is_relevant": True, # Cannot determine relevance without VLM, assume True or check filename?
                "issues": issues,
                "improvement_suggestions": suggestions
            }

            # If invalid, try to find a replacement
            if not is_valid:
                self.logger.info("Image validation failed. Searching for replacement...")
                replacement = self.search_replacement_image(slide_context.get('title', '') + " " + slide_context.get('description', ''))
                if replacement:
                    result["suggested_replacement"] = replacement
                    result["improvement_suggestions"].append("Auto-suggested replacement image found.")
            
            self.logger.info(f"Image validation complete. Score: {score}, Valid: {is_valid}")
            return result
            
        except Exception as e:
            self.logger.error(f"Error validating image: {e}")
            return {
                "is_valid": False,
                "quality_score": 0,
                "issues": [f"Validation error: {str(e)}"],
                "improvement_suggestions": ["Retry validation"]
            }

    def search_replacement_image(self, query: str) -> Optional[str]:
        """
        Searches for a replacement image using DuckDuckGo.
        """
        try:
            from duckduckgo_search import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.images(query, max_results=1))
                if results:
                    return results[0]['image']
        except Exception as e:
            self.logger.error(f"Error searching for image: {e}")
        return None

    def validate_content(self, slide_data: Dict[str, Any], source_docs: List[str]) -> Dict[str, Any]:
        """
        Validates slide content against source documents for factual accuracy.
        """
        self.logger.info(f"Validating content for slide: {slide_data.get('title')}")
        
        # Prepare context from source docs (limit length)
        context = "\n\n".join(source_docs)[:5000]
        
        prompt = f"""
        Verify the factual accuracy of this slide content against the provided source documents.
        
        Slide Content:
        Title: {slide_data.get('title')}
        Bullet Points: {json.dumps(slide_data.get('bullet_points', []))}
        Speaker Notes: {slide_data.get('speaker_notes', '')}
        
        Source Documents:
        {context}
        
        Check for:
        1. Factual accuracy (is it supported by the source?)
        2. Hallucinations (claims not in source)
        3. Contradictions
        
        Return your analysis in the following JSON format ONLY:
        {{
            "is_accurate": <bool>,
            "confidence": <float 0.0-1.0>,
            "issues": [<list of strings describing inaccuracies>],
            "recommendations": [<list of strings for corrections>]
        }}
        """
        
        try:
            response = self.llm.generate(prompt)
            
            # Parse JSON
            import re
            match = re.search(r'```json(.*?)```', response, re.DOTALL)
            if match:
                json_str = match.group(1)
            else:
                start = response.find('{')
                end = response.rfind('}') + 1
                if start != -1 and end != -1:
                    json_str = response[start:end]
                else:
                    json_str = response
                    
            result = json.loads(json_str)
            self.logger.info(f"Content validation complete. Accurate: {result.get('is_accurate')}")
            return result
            
        except Exception as e:
            self.logger.error(f"Error validating content: {e}")
            return {
                "is_accurate": False,
                "confidence": 0.0,
                "issues": [f"Validation error: {str(e)}"],
                "recommendations": []
            }

    def validate_coherence(self, slide_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Checks if the slide elements (title, bullets, notes) are coherent.
        """
        prompt = f"""
        Analyze the coherence of this slide.
        
        Title: {slide_data.get('title')}
        Bullet Points: {json.dumps(slide_data.get('bullet_points', []))}
        Speaker Notes: {slide_data.get('speaker_notes', '')}
        
        Check if:
        1. The title accurately reflects the content.
        2. The speaker notes expand on the bullet points (not just repeat them).
        3. The flow is logical.
        
        Return JSON:
        {{
            "is_coherent": <bool>,
            "score": <int 0-10>,
            "issues": [<list of strings>],
            "suggestions": [<list of strings>]
        }}
        """
        
        try:
            response = self.llm.generate(prompt)
             # Parse JSON
            import re
            match = re.search(r'```json(.*?)```', response, re.DOTALL)
            if match:
                json_str = match.group(1)
            else:
                start = response.find('{')
                end = response.rfind('}') + 1
                if start != -1 and end != -1:
                    json_str = response[start:end]
                else:
                    json_str = response
            
            return json.loads(json_str)
        except Exception as e:
            self.logger.error(f"Error validating coherence: {e}")
            return {"is_coherent": False, "score": 0, "issues": [str(e)], "suggestions": []}

from typing import Dict, Any, List
import json
import re
from autodeck_core.llm.gemma_client import GemmaClient
from autodeck_core.logger import setup_logger

class FormattingAgent:
    def __init__(self):
        self.llm = GemmaClient()
        self.logger = setup_logger("FormattingAgent")
        self.design_principles = """
        # McKinsey-Style Presentation Principles:
        1. **MECE (Mutually Exclusive, Collectively Exhaustive)**: Ensure points are distinct and cover the whole topic.
        2. **Visual Hierarchy**: The most important information should be biggest/boldest.
        3. **Structure determined by Content**:
           - Comparing two things? -> Use a 2-Column Comparison.
           - Four distinct pillars/aspects? -> Use a 2x2 Grid.
           - A process or sequence? -> Use a Linear Flow (or numbered list).
           - A single impactful number? -> Use a Big Stat layout.
           - General list? -> Use a Standard List (fallback).
        4. **Images/Icons**: Use them to reinforce the message, not just for decoration.
        """

    def determine_layout(self, slide_content: Dict[str, Any]) -> Dict[str, Any]:
        """
        Analyzes slide content and determines the best visual layout.
        
        Args:
            slide_content: Dict containing 'title', 'bullet_points', 'image_suggestion', 'speaker_notes'.
            
        Returns:
            Dict containing 'layout_type', 'content_mapping', 'visual_directives'.
        """
        self.logger.info(f"Determining layout for slide: {slide_content.get('title')}")
        
        prompt = f"""
        You are a Senior Presentation Designer at a top-tier consulting firm (like McKinsey or BCG).
        Your goal is to transform raw text content into a structured, visually coherent slide layout.
        
        {self.design_principles}
        
        # Input Content:
        Title: {slide_content.get('title')}
        Bullet Points: {json.dumps(slide_content.get('bullet_points', []))}
        Suggested Image: {slide_content.get('image_suggestion', 'None')}
        
        # Available Layouts:
        - "standard_list": Default for simple lists.
        - "two_column": For comparisons, pros/cons, or splitting content into two distinctive groups.
        - "grid_2x2": For 4 distinct items, matrices, or pillars.
        - "big_stat": If the content focuses heavily on a single number or metric.
        - "image_text_split": Use this if there is a valid 'Suggested Image' AND the image is relevant to explaining the text.
        
        # Instructions:
        1. Analyze the content relations. Is it a comparison? A list? A process?
        2. Check if the 'Suggested Image' is meaningful (not 'None').
        3. Select the BEST layout.
           - If good image exists -> prioritize 'image_text_split' unless 'big_stat' or 'grid_2x2' is a better fit.
        4. Map the input bullet points.
           - For "image_text_split", put points in "main_bullets".
        5. Provide "visual_directives".
        
        # Output JSON Format:
        {{
            "layout_type": "two_column",
            "content_mapping": {{
                "left_title": "Pros",
                "left_points": ["Point A", "Point B"],
                "right_title": "Cons",
                "right_points": ["Point C", "Point D"]
            }},
            "visual_directives": ["Use green check icons for left, red cross for right"]
        }}
        
        Generate JSON:
        """
        
        response = self.llm.generate(prompt, max_tokens=512, temperature=0.2)
        
        try:
            # Try to find JSON in markdown block
            match = re.search(r'```json(.*?)```', response, re.DOTALL)
            if match:
                json_str = match.group(1)
            else:
                # Try to find JSON in python docstring block (common with some models)
                match = re.search(r'"""(.*?)"""', response, re.DOTALL)
                if match:
                    json_str = match.group(1)
                else:
                    # Try to find the first outer { } block
                    match = re.search(r'(\{.*?\})', response, re.DOTALL)
                    if match:
                        json_str = match.group(1)
                    else:
                        json_str = response

            layout_data = json.loads(json_str.strip())
            
            # Basic validation/fallback
            if "layout_type" not in layout_data:
                layout_data["layout_type"] = "standard_list"
                layout_data["content_mapping"] = {"main_bullets": slide_content.get("bullet_points", [])}
                
            self.logger.info(f"Selected layout: {layout_data['layout_type']}")
            return layout_data
            
        except Exception as e:
            self.logger.error(f"Failed to parse layout JSON: {e}")
            # Fallback
            return {
                "layout_type": "standard_list",
                "content_mapping": {
                    "main_bullets": slide_content.get("bullet_points", [])
                },
                "visual_directives": []
            }

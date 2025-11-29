from typing import List, Dict, Any
from autodeck_core.llm.gemma_client import GemmaClient
import json
import re

from autodeck_core.logger import setup_logger

class SlideOutlineAgent:
    def __init__(self):
        self.llm = GemmaClient()
        self.logger = setup_logger("SlideOutlineAgent")

    def generate_outline(self, topic: str, audience: str = "General Audience", num_slides: int = 5, log_callback=None) -> List[Dict[str, str]]:
        """
        Generates a high-level slide outline for the presentation.
        
        Args:
            topic: The main topic of the presentation.
            audience: The target audience.
            num_slides: Approximate number of slides.
            
        Returns:
            List of dictionaries with 'title' and 'description' for each slide.
        """
        if log_callback:
            self.logger = setup_logger("SlideOutlineAgent", log_callback=log_callback)
        self.logger.info(f"Generating outline for topic: '{topic}' (Audience: {audience})")
        
        prompt = f"""
You are an expert presentation planner. Create a structured outline for a PowerPoint presentation.

Topic: {topic}
Target Audience: {audience}
Target Length: Approximately {num_slides} slides.

You MUST output a valid JSON list of objects. Do not output any other text or explanations.
Each object must have:
- "title": The title of the slide.
- "description": A brief 1-sentence description.

Example Output:
[
  {{"title": "Title Slide", "description": "Introduction to the topic"}},
  {{"title": "Key Concept", "description": "Explaining the main idea"}}
]

JSON Output:
"""
        self.logger.info("Calling LLM to generate outline...")
        response = self.llm.generate(prompt, max_tokens=1024, temperature=0.7)
        self.logger.info(f"Received LLM response ({len(response)} chars)")
        
        # Parse JSON
        try:
            match = re.search(r'```json(.*?)```', response, re.DOTALL)
            if match:
                json_str = match.group(1)
            else:
                # Try to find list enclosed in brackets
                match = re.search(r'\[.*\]', response, re.DOTALL)
                if match:
                    json_str = match.group(0)
                else:
                    json_str = response
            
            # Clean up potential trailing commas or whitespace
            json_str = json_str.strip()
            
            outline = json.loads(json_str)
            
            # Handle case where LLM returns a dict instead of a list
            if isinstance(outline, dict):
                # Look for common keys
                for key in ['slides', 'outline', 'presentation']:
                    if key in outline and isinstance(outline[key], list):
                        outline = outline[key]
                        break
                else:
                    # If no list found, try to wrap it or fail
                    self.logger.warning("LLM returned a dict but no list found. Trying to use as single item if valid.")
                    # If it looks like a single slide
                    if 'title' in outline and 'description' in outline:
                        outline = [outline]
                    else:
                        self.logger.error(f"Unexpected JSON structure: {type(outline)}")
                        return []

            # Clean titles
            for slide in outline:
                if 'title' in slide:
                    slide['title'] = self._clean_title(slide['title'])

            self.logger.info(f"Successfully parsed outline with {len(outline)} slides")
            return outline
        except Exception as e:
            self.logger.warning(f"JSON parsing failed: {e}. Attempting fallback text parsing.")
            # Fallback: Regex parsing for non-JSON output
            # Look for patterns like "title": "..." and "description": "..."
            # or - Title: ... \n Description: ...
            
            slides = []
            # Pattern 1: "title": "...", "description": "..." (Double quotes)
            titles = re.findall(r'"title":\s*"(.*?)"', response, re.IGNORECASE)
            descriptions = re.findall(r'"description":\s*"(.*?)"', response, re.IGNORECASE)
            
            # Pattern 2: 'title': '...', 'description': '...' (Single quotes)
            if not titles:
                titles = re.findall(r"'title':\s*'(.*?)'", response, re.IGNORECASE)
                descriptions = re.findall(r"'description':\s*'(.*?)'", response, re.IGNORECASE)

            # Use the minimum length to avoid errors if counts mismatch
            count = min(len(titles), len(descriptions))
            
            if count > 0:
                for i in range(count):
                    slides.append({"title": titles[i], "description": descriptions[i]})
            # Clean up titles
            for slide in slides:
                slide['title'] = self._clean_title(slide['title'])

            self.logger.info(f"Fallback parsing recovered {len(slides)} slides")
            return slides
            
        self.logger.error(f"Fallback parsing failed. Titles found: {len(titles)}, Descriptions found: {len(descriptions)}")
        self.logger.error(f"Raw response: {response}")
        return []

    def _clean_title(self, title: str) -> str:
        """Removes redundant prefixes like 'Slide 1:', 'Title:', etc."""
        # Remove "Slide X:" or "Slide X -"
        title = re.sub(r'^Slide\s+\d+[:\-\.]\s*', '', title, flags=re.IGNORECASE)
        # Remove "Title:"
        title = re.sub(r'^Title[:\-\.]\s*', '', title, flags=re.IGNORECASE)
        # Remove quotes if they wrap the whole title
        title = title.strip('"\'')
        return title.strip()

    def refine_outline(self, current_outline: List[Dict[str, str]], feedback: str, log_callback=None) -> List[Dict[str, str]]:
        """
        Refines the existing outline based on user feedback.
        
        Args:
            current_outline: The current list of slides.
            feedback: User's feedback or requested changes.
            
        Returns:
            Updated list of slides.
        """
        if log_callback:
            self.logger = setup_logger("SlideOutlineAgent", log_callback=log_callback)
        self.logger.info(f"Refining outline with feedback: '{feedback}'")
        
        prompt = f"""
You are an expert presentation planner. Update the following presentation outline based on the user's feedback.

Current Outline:
{json.dumps(current_outline, indent=2)}

User Feedback: "{feedback}"

Instructions:
1. Modify the outline to address the feedback (e.g., add/remove slides, change titles/descriptions).
2. Maintain the logical flow.
3. Return the COMPLETE updated outline as a JSON list.

JSON Output:
"""
        response = self.llm.generate(prompt, max_tokens=1024, temperature=0.7)
        
        # Parse JSON
        try:
            match = re.search(r'```json(.*?)```', response, re.DOTALL)
            if match:
                json_str = match.group(1)
            else:
            # Try to find list enclosed in brackets
                match = re.search(r'\[.*\]', response, re.DOTALL)
                if match:
                    json_str = match.group(0)
                else:
                    json_str = response
            
            json_str = json_str.strip()
            
            outline = json.loads(json_str)
            
            # Handle case where LLM returns a dict instead of a list
            if isinstance(outline, dict):
                for key in ['slides', 'outline', 'presentation']:
                    if key in outline and isinstance(outline[key], list):
                        outline = outline[key]
                        break
                else:
                    if 'title' in outline and 'description' in outline:
                        outline = [outline]
                    else:
                        self.logger.error(f"Unexpected JSON structure in refinement: {type(outline)}")
                        return current_outline

            self.logger.info(f"Successfully refined outline with {len(outline)} slides")
            return outline
        except Exception as e:
            self.logger.error(f"Error parsing refined outline: {e}")
            self.logger.error(f"Raw response: {response}")
            return current_outline

if __name__ == "__main__":
    agent = SlideOutlineAgent()
    # Initial generation
    outline = agent.generate_outline("Oral Semaglutide", num_slides=3)
    print("Initial Outline:", json.dumps(outline, indent=2))
    
    # Refinement
    refined = agent.refine_outline(outline, "Add a slide about cost effectiveness after the introduction.")
    print("Refined Outline:", json.dumps(refined, indent=2))

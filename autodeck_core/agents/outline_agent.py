from typing import List, Dict, Any
from autodeck_core.llm.gemma_client import GemmaClient
import json
import re

class SlideOutlineAgent:
    def __init__(self):
        self.llm = GemmaClient()

    def generate_outline(self, topic: str, audience: str = "General Audience", num_slides: int = 5) -> List[Dict[str, str]]:
        """
        Generates a high-level slide outline for the presentation.
        
        Args:
            topic: The main topic of the presentation.
            audience: The target audience.
            num_slides: Approximate number of slides.
            
        Returns:
            List of dictionaries with 'title' and 'description' for each slide.
        """
        print(f"Generating outline for topic: '{topic}' (Audience: {audience})")
        
        prompt = f"""
You are an expert presentation planner. Create a structured outline for a PowerPoint presentation.

Topic: {topic}
Target Audience: {audience}
Target Length: Approximately {num_slides} slides.

Output a JSON list of objects, where each object represents a slide and has:
- "title": The title of the slide.
- "description": A brief 1-sentence description of what this slide should cover.

Ensure the flow is logical: Title Slide -> Introduction -> Key Points -> Conclusion.

JSON Output:
"""
        response = self.llm.generate(prompt, max_tokens=1024, temperature=0.7)
        
        # Parse JSON
        try:
            match = re.search(r'```json(.*?)```', response, re.DOTALL)
            if match:
                json_str = match.group(1)
            else:
                json_str = response
            
            outline = json.loads(json_str)
            return outline
        except Exception as e:
            print(f"Error parsing outline: {e}")
            print(f"Raw response: {response}")
            return []

    def refine_outline(self, current_outline: List[Dict[str, str]], feedback: str) -> List[Dict[str, str]]:
        """
        Refines the existing outline based on user feedback.
        
        Args:
            current_outline: The current list of slides.
            feedback: User's feedback or requested changes.
            
        Returns:
            Updated list of slides.
        """
        print(f"Refining outline with feedback: '{feedback}'")
        
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
                json_str = response
            
            outline = json.loads(json_str)
            return outline
        except Exception as e:
            print(f"Error parsing refined outline: {e}")
            print(f"Raw response: {response}")
            return current_outline

if __name__ == "__main__":
    agent = SlideOutlineAgent()
    # Initial generation
    outline = agent.generate_outline("Oral Semaglutide", num_slides=3)
    print("Initial Outline:", json.dumps(outline, indent=2))
    
    # Refinement
    refined = agent.refine_outline(outline, "Add a slide about cost effectiveness after the introduction.")
    print("Refined Outline:", json.dumps(refined, indent=2))

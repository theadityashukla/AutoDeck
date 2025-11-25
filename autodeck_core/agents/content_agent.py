from typing import List, Dict, Any
from autodeck_core.llm.gemma_client import GemmaClient
from autodeck_core.agents.retrieval_agent import RetrievalAgent
import json
import re

class SlideContentAgent:
    def __init__(self):
        self.llm = GemmaClient()
        self.retriever = RetrievalAgent()

    def generate_slide_content(self, slide_title: str, slide_description: str) -> Dict[str, Any]:
        """
        Generates detailed content for a single slide using RAG.
        
        Args:
            slide_title: The title of the slide.
            slide_description: A brief description of what the slide should cover.
            
        Returns:
            Dictionary containing 'title', 'bullet_points', 'image_suggestion', 'speaker_notes'.
        """
        print(f"Generating content for slide: '{slide_title}'")
        
        # 1. Retrieve Context
        query = f"{slide_title}: {slide_description}"
        retrieved_docs = self.retriever.retrieve(query, k=3)
        
        context_text = ""
        available_images = []
        for doc in retrieved_docs:
            context_text += f"- {doc['content']}\n"
            if 'related_images' in doc['metadata']:
                # Parse string representation of list back to list if needed, or just append
                # For now, assuming it's a string representation of a list
                try:
                    imgs = eval(doc['metadata']['related_images'])
                    available_images.extend(imgs)
                except:
                    pass

        # 2. Synthesize Content
        prompt = f"""
You are an expert presentation creator. Your task is to create the content for a single PowerPoint slide based on the provided context.

Slide Title: {slide_title}
Slide Goal: {slide_description}

Context from Documents:
{context_text[:4000]} # Limit context

Available Images: {list(set(available_images))}

Instructions:
1. Refine the Slide Title if necessary to be more punchy.
2. Create 3-5 concise, high-impact bullet points.
3. Suggest the best image to use from the "Available Images" list. If none are suitable, describe a conceptual image.
4. Write engaging Speaker Notes that elaborate on the bullet points (approx. 100-150 words).

Output JSON format:
{{
  "title": "Refined Title",
  "bullet_points": ["Point 1", "Point 2", "Point 3"],
  "image_suggestion": "Path to image or description",
  "speaker_notes": "Full speaker notes text..."
}}

JSON Output:
"""
        response = self.llm.generate(prompt, max_tokens=1024, temperature=0.5)
        
        # Parse JSON
        try:
            match = re.search(r'```json(.*?)```', response, re.DOTALL)
            if match:
                json_str = match.group(1)
            else:
                json_str = response
            
            content = json.loads(json_str)
            return content
        except Exception as e:
            print(f"Error parsing slide content: {e}")
            print(f"Raw response: {response}")
            return {
                "title": slide_title,
                "bullet_points": ["Error generating content."],
                "image_suggestion": "None",
                "speaker_notes": "Error generating notes."
            }

    def refine_content(self, current_content: Dict[str, Any], feedback: str) -> Dict[str, Any]:
        """
        Refines the slide content based on user feedback.
        
        Args:
            current_content: The current slide content dictionary.
            feedback: User's feedback.
            
        Returns:
            Updated slide content dictionary.
        """
        print(f"Refining content with feedback: '{feedback}'")
        
        prompt = f"""
You are an expert presentation creator. Update the following slide content based on the user's feedback.

Current Slide Content:
{json.dumps(current_content, indent=2)}

User Feedback: "{feedback}"

Instructions:
1. Modify the content (title, bullets, notes) to address the feedback.
2. Keep the image suggestion unless explicitly asked to change it.
3. Return the COMPLETE updated content as a JSON object.

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
            
            content = json.loads(json_str)
            return content
        except Exception as e:
            print(f"Error parsing refined content: {e}")
            print(f"Raw response: {response}")
            return current_content

if __name__ == "__main__":
    agent = SlideContentAgent()
    # Initial generation
    slide_data = agent.generate_slide_content(
        slide_title="Mechanism of Action", 
        slide_description="Explain how oral semaglutide works using SNAC technology."
    )
    print("Initial Content:", json.dumps(slide_data, indent=2))
    
    # Refinement
    refined = agent.refine_content(slide_data, "Make the speaker notes more casual and simpler.")
    print("Refined Content:", json.dumps(refined, indent=2))

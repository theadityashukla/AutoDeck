from typing import List, Dict, Any
from autodeck_core.llm.gemma_client import GemmaClient
import json
import re
import os

class AgenticChunker:
    def __init__(self, mock: bool = False):
        self.mock = mock
        self.llm = GemmaClient()

    def describe_image(self, image_path: str) -> str:
        """Use vision to describe an image for better text association."""
        if not os.path.exists(image_path):
            return ""
        
        try:
            prompt = """Describe this image concisely in 1-2 sentences. 
Focus on: what type of figure/chart it is, key data or concepts shown, and any visible labels or titles.
If it's a graph, mention the axes. If it's a diagram, describe its main components."""
            
            response = self.llm.generate(prompt, images=[image_path], max_tokens=150, temperature=0.3)
            return response.strip()
        except Exception as e:
            print(f"Vision analysis failed for {image_path}: {e}")
            return ""

    def chunk(self, text: str, images: List[Dict[str, Any]] = []) -> List[Dict[str, Any]]:
        """
        Chunks the text into semantic sections using the LLM.
        Args:
            text: The text to chunk.
            images: List of image metadata (path, index, etc.) available for this text context.
        """
        if self.mock:
            print("WARNING: Using Mock Chunker")
            return [
                {"title": "Mock Chunk 1", "content": text[:500], "summary": "First mock chunk.", "related_images": []},
                {"title": "Mock Chunk 2", "content": text[500:1000], "summary": "Second mock chunk.", "related_images": []}
            ]

        # Use vision to describe each image for better context
        image_context = ""
        image_descriptions = []
        
        if images:
            image_context = "Available Images on this page:\n"
            for i, img in enumerate(images):
                img_path = img.get('path', '')
                img_name = os.path.basename(img_path)
                
                # Use vision to describe the image
                description = self.describe_image(img_path) if img_path else ""
                image_descriptions.append(description)
                
                if description:
                    image_context += f"- Image {i}: {img_name} - {description}\n"
                else:
                    image_context += f"- Image {i}: {img_name}\n"

        prompt = f"""You are an expert document analyzer. Your task is to split the following text into logical, semantic chunks.
Each chunk should represent a distinct topic or section (e.g., Introduction, Methodology, Results, specific sub-topic).

You also have access to a list of images found on the same page as this text, with descriptions of what each image contains.
For each chunk, determine if any of the available images are relevant based on:
1. Explicit references in the text (e.g., "Figure 1", "as shown in the chart")
2. Semantic relevance (the image content matches the topic of the chunk)

{image_context}

Return the result as a JSON list of objects, where each object has:
- "title": A short title for the chunk.
- "content": The exact text content of the chunk.
- "summary": A one-sentence summary of the chunk.
- "related_images": A list of indices (integers) of the relevant images from the provided list (e.g., [0, 2]). Return empty list [] if none.

Text to chunk:
{text}

JSON Output:
"""
        response = self.llm.generate(prompt, max_tokens=2048, temperature=0.2)
        print(f"DEBUG: LLM Response length: {len(response)}")
        
        # Parse JSON from response
        try:
            # extract json block if wrapped in markdown
            match = re.search(r'```json(.*?)```', response, re.DOTALL)
            if match:
                json_str = match.group(1)
            else:
                json_str = response
                
            chunks = json.loads(json_str)
            
            # Add image descriptions to chunk metadata for downstream use
            for chunk in chunks:
                related_indices = chunk.get('related_images', [])
                chunk['image_descriptions'] = [
                    image_descriptions[idx] for idx in related_indices 
                    if isinstance(idx, int) and 0 <= idx < len(image_descriptions)
                ]
            
            return chunks
        except Exception as e:
            print(f"Error parsing chunks: {e}")
            print(f"Raw response: {response[:500]}...")
            # Fallback: return whole text as one chunk
            return [{"title": "Full Text", "content": text, "summary": "Full text content (parsing failed).", "related_images": []}]


if __name__ == "__main__":
    chunker = AgenticChunker()
    print("AgenticChunker initialized with vision capabilities")

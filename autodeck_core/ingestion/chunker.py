from typing import List, Dict, Any
from autodeck_core.llm.gemma_client import GemmaClient
import json
import re
import os

class AgenticChunker:
    def __init__(self, mock: bool = False):
        self.mock = mock
        self.llm = GemmaClient()

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

        # Prepare image context for the prompt
        image_context = ""
        if images:
            image_context = "Available Images on this page:\n"
            for i, img in enumerate(images):
                image_context += f"- Image {i}: {os.path.basename(img['path'])}\n"

        prompt = f"""
You are an expert document analyzer. Your task is to split the following text into logical, semantic chunks.
Each chunk should represent a distinct topic or section (e.g., Introduction, Methodology, Results, specific sub-topic).

You also have access to a list of images found on the same page as this text. 
For each chunk, determine if any of the available images are relevant (e.g., explicitly referenced as "Figure X" or contextually relevant).

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
        print(f"DEBUG: LLM Response start: {response[:200]}...")
        
        # Parse JSON from response
        try:
            # extract json block if wrapped in markdown
            match = re.search(r'```json(.*?)```', response, re.DOTALL)
            if match:
                json_str = match.group(1)
            else:
                json_str = response
                
            chunks = json.loads(json_str)
            return chunks
        except Exception as e:
            print(f"Error parsing chunks: {e}")
            print(f"Raw response: {response}")
            # Fallback: return whole text as one chunk
            return [{"title": "Full Text", "content": text, "summary": "Full text content (parsing failed)."}]

if __name__ == "__main__":
    chunker = AgenticChunker()
    print("AgenticChunker initialized")

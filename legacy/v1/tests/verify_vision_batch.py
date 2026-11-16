
import os
import sys
import argparse
import glob
from pathlib import Path

# Add project root to path to import autodeck_core
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from autodeck_core.llm.gemma_client import GemmaClient
except ImportError:
    print("Error: Could not import GemmaClient. Make sure you are running this from the project root or tests directory.")
    sys.exit(1)

def verify_vision_batch(folder_path):
    print(f"--- Vision Batch Verifier ---")
    print(f"Scanning folder: {folder_path}")
    
    # Supported extensions
    extensions = ['*.png', '*.jpg', '*.jpeg', '*.PNG', '*.JPG', '*.JPEG']
    image_files = []
    
    for ext in extensions:
        image_files.extend(glob.glob(os.path.join(folder_path, ext)))
        
    image_files = sorted(list(set(image_files)))
    
    if not image_files:
        print(f"No images found in {folder_path}")
        return

    print(f"Found {len(image_files)} images.")
    
    print("Initializing GemmaClient (Loading Model)...")
    try:
        client = GemmaClient()
        # Force model load if lazy loaded, though generate handles it
        # But for vision it switches models.
    except Exception as e:
        print(f"Failed to initialize client: {e}")
        return

    print("Starting processing...\n")

    for i, img_path in enumerate(image_files):
        print(f"[{i+1}/{len(image_files)}] Processing: {os.path.basename(img_path)}")
        
        prompt = "Describe this image in detail."
        try:
            # We pass the full path
            response = client.generate(prompt, images=[img_path], max_tokens=256)
            
            # Handle response - might be string or object
            if hasattr(response, 'text'):
                response_text = response.text
            elif hasattr(response, '__str__'):
                response_text = str(response)
            else:
                response_text = response
                
            print(f"--- Description for {os.path.basename(img_path)} ---")
            print(response_text.strip() if isinstance(response_text, str) else response_text)
            print("----------------------------------------------------\n")
            
        except Exception as e:
            print(f"Error processing {img_path}: {e}\n")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch verify vision model on a folder of images.")
    parser.add_argument("folder", nargs="?", default=".", help="Folder containing images to process")
    
    args = parser.parse_args()
    
    if not os.path.isdir(args.folder):
        print(f"Error: {args.folder} is not a directory.")
        sys.exit(1)
        
    verify_vision_batch(args.folder)

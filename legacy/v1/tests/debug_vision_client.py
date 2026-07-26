
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from autodeck_core.llm.gemma_client import GemmaClient

def test_vision():
    print("Initializing GemmaClient...")
    client = GemmaClient()
    
    # Create a dummy image if needed, or check if we have one
    # For now, let's just assume we can pass a non-existent path and see if it tries to load the model
    # before failing on the image load. OR better, verify with a real image if possible.
    # But checking if model loads is step 1.
    
    # We will try to call _generate_vision directly or via generate to test the import/load logic
    print("Testing Vision Model Loading...")
    
    # Mock image path that doesn't strictly need to exist if we crash on load
    img_path = "tests/test.png" 
    
    # Create dummy image to be safe
    try:
        from PIL import Image
        img = Image.new('RGB', (100, 100), color = 'red')
        img.save(img_path)
    except:
        pass

    try:
        response = client.generate("Describe this image", images=[img_path])
        print(f"Response: {response}")
    except Exception as e:
        print(f"Caught expected exception (or real one): {e}")

if __name__ == "__main__":
    test_vision()

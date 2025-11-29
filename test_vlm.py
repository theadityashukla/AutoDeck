import os
print("Importing mlx_vlm...")
try:
    from mlx_vlm import load, generate
    from mlx_vlm.utils import load_image
    print("Imports successful.")
except ImportError as e:
    print(f"Import failed: {e}")
    exit(1)

model_path = "gemma-3-12b-mlx"
print(f"Loading model from {model_path}...")

try:
    model, processor = load(model_path)
    print("Model loaded.")
except Exception as e:
    print(f"Model load failed: {e}")
    exit(1)

prompt = "Describe this image."
print("Generating text (text-only test)...")
try:
    response = generate(model, processor, image=None, prompt="Hello, who are you?", verbose=True)
    print(f"Response: {response}")
except Exception as e:
    print(f"Generation failed: {e}")
    exit(1)

print("Test complete.")

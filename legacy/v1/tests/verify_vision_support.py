
import sys
import os

try:
    from mlx_vlm import load, generate, apply_chat_template
    from mlx_vlm.utils import load_image
    print("mlx_vlm imported successfully.")
except ImportError:
    print("mlx_vlm not found.")
    sys.exit(1)

model_path = "gemma-3-12b-mlx"
prompt = "Describe this image."

print(f"Attempting to load model from: {model_path} using mlx_vlm...")

try:
    model, processor = load(model_path, trust_remote_code=True)
    print("Model loaded successfully via mlx_vlm!")
    
    # Check config for vision support
    print(f"Model Config Type: {type(model.config)}")
    if hasattr(model.config, "vision_config"):
        print("Vision Config found.")
    else:
        print("WARNING: No vision_config found in model config. This might be a text-only model.")

except Exception as e:
    print(f"FAILED to load model with mlx_vlm: {e}")
    sys.exit(1)

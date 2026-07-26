#!/usr/bin/env python3
"""
Test script to verify MLX vision model functionality with a minimal example.
This uses the official mlx_vlm API to test if vision actually works.
"""

import sys
from pathlib import Path

try:
    from mlx_vlm import load, generate
    from mlx_vlm.utils import load_image
except ImportError:
    print("ERROR: mlx_vlm not installed")
    sys.exit(1)

def test_vision_model(model_name, image_path):
    """Test a vision model with a simple image description task."""
    print(f"\n{'='*60}")
    print(f"Testing Model: {model_name}")
    print(f"{'='*60}")
    
    try:
        # Load model
        print("Loading model...")
        model, processor = load(model_name, trust_remote_code=True)
        print(f"✓ Model loaded successfully")
        
        # Check for vision config
        if hasattr(model.config, 'vision_config'):
            print(f"✓ Vision config found")
        else:
            print(f"⚠ WARNING: No vision_config in model.config")
        
        # Load image
        print(f"\nLoading image: {image_path}")
        image = load_image(image_path)
        print(f"✓ Image loaded")
        
        # Generate description
        prompt = "Describe this image in detail."
        print(f"\nGenerating description...")
        print(f"Prompt: {prompt}")
        
        response = generate(
            model,
            processor,
            image,
            prompt,
            max_tokens=256,
            temp=0.7,
            verbose=False
        )
        
        print(f"\n{'='*60}")
        print("RESULT:")
        print(f"{'='*60}")
        print(response)
        print(f"{'='*60}\n")
        
        return True
        
    except Exception as e:
        print(f"\n❌ FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # Test with common MLX vision models
    # PaliGemma is Google's vision model, often available
    test_models = [
        "mlx-community/paligemma-3b-mix-448-8bit",
        "mlx-community/Qwen2-VL-2B-Instruct-4bit",
        "gemma-3-12b-mlx",  # Current model (likely text-only)
    ]
    
    # Use test image
    image_path = "/Users/aditya/Documents/Codes/Projects/Gen AI assited Keynotes/AutoDeck/0. Input Data/1. Images/2013_Porsche_918_Spyder_development_mule_in_Monaco.jpg"
    
    if not Path(image_path).exists():
        print(f"ERROR: Test image not found at {image_path}")
        sys.exit(1)
    
    print("MLX Vision Model Compatibility Test")
    print("="*60)
    
    for model_name in test_models:
        success = test_vision_model(model_name, image_path)
        if success:
            print(f"\n✓ SUCCESS: {model_name} works!")
            print(f"Recommendation: Use this model for your vision tasks.")
            break
    else:
        print("\n❌ All models failed. You may need to download a vision model first.")

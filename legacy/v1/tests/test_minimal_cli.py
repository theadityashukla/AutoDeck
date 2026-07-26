#!/usr/bin/env python3
"""
Minimal reproduction of the WORKING CLI to understand exact API usage
"""
import sys
from mlx_vlm import load, generate
from mlx_vlm.utils import load_image

# Exact model from CLI
model_path = "mlx-community/gemma-3-12b-it-qat-4bit"
image_path = "/Users/aditya/Documents/Codes/Projects/Gen AI assited Keynotes/AutoDeck/0. Input Data/1. Images/2013_Porsche_918_Spyder_development_mule_in_Monaco.jpg"
prompt = "Describe this image."

print("Loading model...")
model, processor = load(model_path, trust_remote_code=True)

print("Loading image...")
image = load_image(image_path)

print(f"Image type: {type(image)}")
print(f"Calling generate with:")
print(f"  - model")
print(f"  - processor") 
print(f"  - image (type: {type(image)})")
print(f"  - prompt: '{prompt}'")

# This is the EXACT pattern from mlx_vlm CLI
output = generate(
    model,
    processor,
    image,  # Single image object
    prompt, 
    max_tokens=100,
    temp=0.0,
    verbose=True
)

print("\n" + "="*60)
print("SUCCESS!")
print("="*60)
print(output)


from mlx_vlm import load

try:
    model_path = "gemma-3-12b-mlx"
    print(f"Loading processor from {model_path}...")
    model, processor = load(model_path, trust_remote_code=True)
    
    print("\n--- Processor Info ---")
    if hasattr(processor, "image_token"):
        print(f"Image Token: '{processor.image_token}'")
    elif hasattr(model.config, "image_token_index"):
        print(f"Image Token Index: {model.config.image_token_index}")
        # Try to decode?
    else:
        print("No explicit image_token attribute found.")
        
    # Check tokenizer
    if hasattr(processor, "tokenizer"):
         print(f"Tokenizer: {processor.tokenizer}")
         
except Exception as e:
    print(f"Error: {e}")

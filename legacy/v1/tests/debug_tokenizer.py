
from mlx_vlm import load

model_path = "gemma-3-12b-mlx"
print(f"Loading processor from {model_path}...")
model, processor = load(model_path, trust_remote_code=True)

tokenizer = processor.tokenizer
token_str = "<image_soft_token>"
token_str_simple = "<image>"

print(f"Tokenizing '{token_str}':")
ids = tokenizer.encode(token_str, add_special_tokens=False)
print(f"IDs: {ids}")
print(f"Decoded: {[tokenizer.decode([i]) for i in ids]}")

print(f"\nTokenizing '{token_str_simple}':")
ids2 = tokenizer.encode(token_str_simple, add_special_tokens=False)
print(f"IDs: {ids2}")

# Check if single token
if len(ids) == 1:
    print(f"\nSUCCESS: '{token_str}' maps to single ID: {ids[0]}")
else:
    print(f"\nFAILURE: '{token_str}' maps to multiple IDs.")
    
# Check special tokens map
print("\nSpecial Tokens Map:")
# print(tokenizer.special_tokens_map)
if hasattr(tokenizer, "image_token_id"):
     print(f"Tokenizer image_token_id: {tokenizer.image_token_id}")

from mlx_lm import load, generate
from mlx_lm.sample_utils import make_sampler

def test_model():
    print("Testing MLX Model Loading...")
    model_path = "gemma-3-12b-mlx"
    
    try:
        model, tokenizer = load(model_path)
        print("Model loaded successfully.")
        
        prompt = "Hello, how are you?"
        print(f"Generating response for: '{prompt}'")
        
        sampler = make_sampler(temp=0.7)
        
        response = generate(
            model, 
            tokenizer, 
            prompt=prompt, 
            max_tokens=50, 
            sampler=sampler,
            verbose=True
        )
        print("\nResponse:")
        print(response)
        print("\nTest Passed!")
        
    except Exception as e:
        print(f"Test Failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_model()

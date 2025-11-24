import os
from typing import Optional
try:
    from mlx_lm import load, generate
    from mlx_lm.sample_utils import make_sampler
except ImportError:
    load = None
    generate = None
    make_sampler = None

class GemmaClient:
    _instance = None

    def __new__(cls, model_path: str = "gemma-3-12b-mlx"):
        if cls._instance is None:
            cls._instance = super(GemmaClient, cls).__new__(cls)
            cls._instance.initialized = False
        return cls._instance

    def __init__(self, model_path: str = "gemma-3-12b-mlx"):
        if self.initialized:
            return
            
        self.model_path = model_path
        self.model = None
        self.tokenizer = None
        self.initialized = True
        
    def load_model(self):
        if self.model is not None:
            return

        if load is None:
            raise ImportError("mlx_lm not installed. Please install it with `pip install mlx-lm`")

        print(f"Loading Gemma 3 model from {self.model_path}...")
        try:
            self.model, self.tokenizer = load(self.model_path)
            print("Gemma 3 model loaded successfully.")
        except Exception as e:
            print(f"Failed to load model: {e}")
            raise

    def generate(self, prompt: str, max_tokens: int = 1024, temperature: float = 0.7) -> str:
        if self.model is None:
            self.load_model()
            
        sampler = make_sampler(temp=temperature)
        
        print(f"DEBUG: calling mlx_lm.generate with prompt length {len(prompt)}")
        response = generate(
            self.model,
            self.tokenizer,
            prompt=prompt,
            max_tokens=max_tokens,
            sampler=sampler,
            verbose=True # Enable verbose to see token generation progress
        )
        print("DEBUG: mlx_lm.generate returned")
        return response

if __name__ == "__main__":
    client = GemmaClient()
    # client.load_model()
    print("GemmaClient initialized (MLX)")

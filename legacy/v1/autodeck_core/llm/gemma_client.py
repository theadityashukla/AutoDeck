import os
from typing import Optional, List
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

    def generate(self, prompt: str, images: Optional[List[str]] = None, max_tokens: int = 1024, temperature: float = 0.7) -> str:
        # Check if this is a Vision Request
        if images and len(images) > 0:
            return self._generate_vision(prompt, images, max_tokens, temperature)
            
        # Standard Text Request
        if self.model is None:
            self.load_model()
            
        sampler = make_sampler(temp=temperature)
        
        print(f"DEBUG: calling mlx_lm.generate with prompt length {len(prompt)}")
        try:
            response = generate(
                self.model,
                self.tokenizer,
                prompt=prompt,
                max_tokens=max_tokens,
                sampler=sampler,
                verbose=True
            )
            return response
        except Exception as e:
            print(f"Generation error: {e}")
            return ""

    def _generate_vision(self, prompt: str, images: List[str], max_tokens: int, temperature: float) -> str:
        try:
            from mlx_vlm import load as load_vlm
            from mlx_vlm import generate as generate_vlm
            from mlx_vlm.prompt_utils import apply_chat_template
            from mlx_vlm.utils import load_image
            
            # Unload text model to save memory
            if self.model is not None:
                self.model = None
                self.tokenizer = None
                
            # Load VLM
            model_path = "mlx-community/gemma-3-12b-it-qat-4bit"
            model, processor = load_vlm(model_path, trust_remote_code=True)
            
            # Load images as PIL Image objects
            loaded_images = [load_image(img) for img in images]
            
            # Use structured messages format - let processor handle token insertion
            messages = [
                {
                    "role": "user",
                    "content": [
                        {"type": "image"},  # Processor will insert correct token
                        {"type": "text", "text": prompt}
                    ]
                }
            ]
            
            # Apply chat template - processor handles image token insertion
            formatted_prompt = apply_chat_template(
                processor,
                config=model.config,
                prompt=messages,
                num_images=len(loaded_images)
            )
            
            # Call generate with the pre-formatted prompt and images
            output = generate_vlm(
                model,
                processor,
                formatted_prompt,
                loaded_images,
                max_tokens=max_tokens,
                temp=temperature,
                verbose=True
            )
            
            return output
            
        except ImportError as e:
            print(f"Error: mlx_vlm not installed: {e}")
            return "Error: Vision library missing."
        except Exception as e:
            print(f"Vision Generation Failed: {e}")
            import traceback
            traceback.print_exc()
            return ""

if __name__ == "__main__":
    client = GemmaClient()
    # client.load_model()
    print("GemmaClient initialized (MLX)")

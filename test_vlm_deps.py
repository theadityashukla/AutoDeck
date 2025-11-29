import mlx.core as mx
print("mlx imported")
import PIL
from PIL import Image
print("PIL imported")
import transformers
print("transformers imported")
import numpy
print("numpy imported")
try:
    import mlx_vlm
    print("mlx_vlm imported")
except ImportError:
    print("mlx_vlm import failed")
except Exception as e:
    print(f"mlx_vlm crashed: {e}")

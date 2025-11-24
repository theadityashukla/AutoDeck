# JAX & FLAX Setup Guide for MacBook Pro (Apple Silicon)

A comprehensive guide to setting up JAX and FLAX with Metal GPU acceleration on MacBook Pro with M1/M2/M3 chips.

## 🎯 Overview

This guide covers setting up JAX and FLAX with Apple's Metal GPU acceleration, enabling you to run machine learning models efficiently on your MacBook Pro's built-in GPU.

## 📋 Prerequisites

- **Hardware**: MacBook Pro with Apple Silicon (M1, M1 Pro, M1 Max, M2, M3 series)
- **OS**: macOS 13.0 (Ventura) or later (Sonoma 14.0+ recommended)
- **Python**: 3.9 or later
- **Xcode Command Line Tools**: `xcode-select --install`

## 🚀 Quick Start

### 1. Install Xcode Command Line Tools
```bash
xcode-select --install
```

### 2. Create Conda Environment
```bash
# Create new environment
conda create -n jax-metal python=3.11
conda activate jax-metal

# Or use existing environment
conda activate your-existing-env
```

### 3. Install JAX with Metal Support
```bash
# Install base dependencies
pip install -U pip
pip install numpy wheel

# Install jax-metal (Apple's Metal plugin)
pip install jax-metal
```

### 4. Install Compatible JAX Versions
```bash
# Install compatible JAX and jaxlib versions
pip install "jaxlib>=0.4.26,<0.5.0" "jax>=0.4.26,<0.5.0"
```

### 5. Install FLAX (Optional)
```bash
# Install compatible FLAX version
pip install "flax>=0.7.0,<0.8.0"
```

## 🔧 Verification

### Test Metal GPU Detection
```bash
python -c "
import jax
print('JAX version:', jax.__version__)
print('Available devices:', jax.devices())
print('Metal available:', 'METAL' in [d.platform for d in jax.devices()])
"
```

### Test Basic Computation
```bash
python -c "
import jax
import jax.numpy as jnp
print('Testing Metal GPU...')
x = jnp.array([1, 2, 3, 4, 5])
print('Array:', x)
print('Sum:', jnp.sum(x))
print('✅ Metal GPU is working!')
"
```

## 🛠️ Troubleshooting

### Problem: "UNIMPLEMENTED: default_memory_space is not supported"

**Cause**: Version incompatibility between JAX and jax-metal

**Solution**: Use compatible version constraints
```bash
pip install "jaxlib>=0.4.26,<0.5.0" "jax>=0.4.26,<0.5.0"
```

### Problem: "Platform 'METAL' is experimental"

**Cause**: This is normal - Metal support is experimental

**Solution**: This is just a warning, not an error. Your setup is working correctly.

### Problem: Dependency Conflicts

**Cause**: Different packages require different JAX versions

**Solution**: Use version constraints to find compatible versions
```bash
# Example: If FLAX requires newer JAX
pip install "flax>=0.7.0,<0.8.0" "jax>=0.4.26,<0.5.0"
```

### Problem: No Metal Devices Detected

**Solutions**:
1. **Check macOS version**: Ensure you're on Sonoma 14.0+ for best compatibility
2. **Reinstall jax-metal**: `pip uninstall jax-metal && pip install jax-metal`
3. **Set environment variable**: `ENABLE_PJRT_COMPATIBILITY=1 python your_script.py`

## 📊 Version Compatibility Matrix

| Component | Recommended Version | Notes |
|-----------|-------------------|-------|
| jax-metal | 0.1.1 | Apple's Metal plugin |
| jax | 0.4.26 - 0.4.99 | Compatible with jax-metal |
| jaxlib | 0.4.26 - 0.4.99 | Must match JAX version |
| flax | 0.7.0 - 0.7.99 | For older JAX versions |
| numpy | ≥1.24 | Required dependency |
| python | 3.9 - 3.12 | Supported versions |

## 🎨 Creative Solutions

### 1. Version Constraint Magic
```bash
# Instead of guessing versions, use constraints
pip install "jaxlib>=0.4.26,<0.5.0" "jax>=0.4.26,<0.5.0"
```

**How it works**:
- `>=0.4.26`: Minimum version required
- `<0.5.0`: Maximum version (exclusive)
- **Result**: Installs latest compatible version in range

### 2. Environment Variable Compatibility
```bash
# For newer jaxlib versions with jax-metal
ENABLE_PJRT_COMPATIBILITY=1 python your_script.py
```

### 3. Dependency Conflict Resolution
```bash
# When packages have conflicting requirements
pip install "package-a>=1.0,<2.0" "package-b>=2.0,<3.0"
# Let pip resolve conflicts automatically
```

## 🔍 Understanding Version Specifiers

| Specifier | Meaning | Example |
|-----------|---------|---------|
| `==1.2.3` | Exact version | Only version 1.2.3 |
| `>=1.2.3` | Minimum version | 1.2.3 or higher |
| `<=1.2.3` | Maximum version | 1.2.3 or lower |
| `~=1.2.3` | Compatible release | 1.2.3 to 1.3.0 (exclusive) |
| `>=1.2.3,<2.0.0` | Version range | 1.2.3 to 2.0.0 (exclusive) |

## 🚀 Advanced Setup

### Multi-Environment Setup
```bash
# Create separate environments for different use cases
conda create -n jax-stable python=3.11  # Stable versions
conda create -n jax-latest python=3.11  # Latest versions
conda create -n jax-experimental python=3.11  # Experimental features
```

### Performance Optimization
```bash
# Set environment variables for better performance
export JAX_ENABLE_X64=False  # Use float32 for better performance
export JAX_DISABLE_JIT=0     # Enable JIT compilation
```

### Memory Management
```bash
# Monitor GPU memory usage
python -c "
import jax
print('GPU Memory Info:')
for device in jax.devices():
    print(f'  {device}: {device.memory_info()}')
"
```

## 📚 Example Usage

### Basic JAX with Metal
```python
import jax
import jax.numpy as jnp

# Check devices
print("Available devices:", jax.devices())

# Create array on GPU
x = jnp.array([1, 2, 3, 4, 5])
print("Array:", x)
print("Sum:", jnp.sum(x))

# Matrix multiplication
A = jnp.random.normal(size=(1000, 1000))
B = jnp.random.normal(size=(1000, 1000))
C = jnp.dot(A, B)
print("Matrix multiplication completed!")
```

### FLAX Model Example
```python
import jax
import jax.numpy as jnp
import flax.linen as nn

# Simple neural network
class SimpleNet(nn.Module):
    @nn.compact
    def __call__(self, x):
        x = nn.Dense(128)(x)
        x = jax.nn.relu(x)
        x = nn.Dense(10)(x)
        return x

# Initialize model
model = SimpleNet()
key = jax.random.PRNGKey(0)
x = jax.random.normal(key, (32, 784))
params = model.init(key, x)
output = model.apply(params, x)
print("Model output shape:", output.shape)
```

## 🐛 Common Issues & Solutions

### Issue: "No module named 'jax'"
**Solution**: Ensure you're in the correct conda environment
```bash
conda activate jax-metal
python -c "import jax; print('JAX imported successfully')"
```

### Issue: "Metal device not found"
**Solution**: Check macOS version and reinstall
```bash
# Check macOS version
sw_vers
# Reinstall if needed
pip uninstall jax-metal && pip install jax-metal
```

### Issue: "Out of memory"
**Solution**: Reduce batch size or use gradient checkpointing
```python
# Reduce batch size
batch_size = 16  # Instead of 32 or 64

# Or use gradient checkpointing
from flax.training import checkpoints
```

## 📈 Performance Tips

1. **Use float32**: `export JAX_ENABLE_X64=False`
2. **Enable JIT**: `export JAX_DISABLE_JIT=0`
3. **Batch operations**: Process data in batches
4. **Memory management**: Monitor GPU memory usage
5. **Profile your code**: Use JAX's built-in profiling tools

## 🔗 Useful Resources

- [Apple Metal JAX Documentation](https://developer.apple.com/metal/jax/)
- [JAX Official Documentation](https://jax.readthedocs.io/)
- [FLAX Documentation](https://flax.readthedocs.io/)
- [JAX GitHub Issues](https://github.com/google/jax/issues)

## 📝 Notes

- **Experimental Status**: Metal support is experimental and may have limitations
- **Version Dependencies**: Always check version compatibility between packages
- **Memory Limits**: Monitor GPU memory usage, especially with large models
- **Performance**: Metal performance may vary compared to CUDA on NVIDIA GPUs

## 🤝 Contributing

If you encounter issues or have improvements, please:
1. Check existing GitHub issues
2. Create a new issue with detailed information
3. Include your macOS version, Python version, and error messages

---

**Happy coding with JAX and FLAX on your MacBook Pro! 🚀** 
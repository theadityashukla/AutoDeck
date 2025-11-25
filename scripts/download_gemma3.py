#!/usr/bin/env python3
"""
Script to download Gemma 3 12B INT4 FLAX model from Kaggle
"""

import os
import json
import requests
from pathlib import Path

def download_gemma3_flax():
    """Download Gemma 3 12B INT4 FLAX model from Kaggle"""
    
    # Model details
    model_owner = "google"
    model_slug = "gemma-3"
    framework = "flax"
    instance_slug = "gemma3-12b-int4"
    version = "1"  # Try version 1 first
    
    # Create download directory
    download_dir = Path("gemma3-12b-int4")
    download_dir.mkdir(exist_ok=True)
    
    print(f"Downloading Gemma 3 12B INT4 FLAX model...")
    print(f"Model: {model_owner}/{model_slug}/{framework}/{instance_slug}")
    print(f"Version: {version}")
    print(f"Download directory: {download_dir.absolute()}")
    
    # Try to download using kaggle CLI
    import subprocess
    
    try:
        # First, let's try to list available versions
        cmd = ["kaggle", "models", "instances", "versions", "files", 
               f"{model_owner}/{model_slug}/{framework}/{instance_slug}/{version}"]
        
        print(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("Available files:")
            print(result.stdout)
            
            # Now try to download
            download_cmd = ["kaggle", "models", "instances", "versions", "download",
                          f"{model_owner}/{model_slug}/{framework}/{instance_slug}/{version}"]
            
            print(f"Downloading with command: {' '.join(download_cmd)}")
            download_result = subprocess.run(download_cmd, capture_output=True, text=True)
            
            if download_result.returncode == 0:
                print("✅ Download completed successfully!")
                print(download_result.stdout)
            else:
                print("❌ Download failed:")
                print(download_result.stderr)
                
        else:
            print("❌ Failed to list files:")
            print(result.stderr)
            
            # Try different version numbers
            for v in ["1", "2", "3", "latest"]:
                print(f"\nTrying version: {v}")
                cmd = ["kaggle", "models", "instances", "versions", "files", 
                       f"{model_owner}/{model_slug}/{framework}/{instance_slug}/{v}"]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"✅ Found files for version {v}:")
                    print(result.stdout)
                    break
                else:
                    print(f"❌ Version {v} failed: {result.stderr}")
                    
    except Exception as e:
        print(f"❌ Error: {e}")
        
    # Alternative: Try to get model info
    try:
        print("\nTrying to get model information...")
        info_cmd = ["kaggle", "models", "list", "--owner", model_owner]
        result = subprocess.run(info_cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print("Available Google models:")
            print(result.stdout)
        else:
            print("Failed to get model list:")
            print(result.stderr)
            
    except Exception as e:
        print(f"❌ Error getting model info: {e}")

if __name__ == "__main__":
    download_gemma3_flax() 
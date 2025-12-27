import os
import subprocess
import time

def convert_pptx_to_image(pptx_path, output_dir):
    """
    Converts a PPTX slide to an image using LibreOffice headless.
    """
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    soffice_path = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    
    # Command to convert to PNG
    # --convert-to png --outdir <output_dir> <pptx_path>
    cmd = [
        soffice_path,
        "--headless",
        "--convert-to", "png",
        "--outdir", output_dir,
        pptx_path
    ]
    
    print(f"Running conversion: {' '.join(cmd)}")
    start_time = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("Stdout:", result.stdout)
        print("Stderr:", result.stderr)
        print(f"Conversion took {time.time() - start_time:.2f}s")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Conversion failed: {e}")
        print("Stderr:", e.stderr)
        return False

if __name__ == "__main__":
    # Create a dummy PPTX if needed, or use an existing one
    # For this test, we assume a PPTX exists or we fail.
    # We will use the one generated in previous tests if available.
    
    test_ppt = "generated_presentation.pptx" 
    # Try multiple common names from our tests
    candidates = ["generated_presentation.pptx", "test_presentation.pptx"]
    found_ppt = None
    
    # Check current dir
    for c in candidates:
        if os.path.exists(c):
            found_ppt = c
            break
            
    # Check if we have one in session state (mocked)
    if not found_ppt:
        # Search widely? No, just listdir
        files = [f for f in os.listdir('.') if f.endswith('.pptx')]
        if files:
            found_ppt = files[0]
            
    if found_ppt:
        print(f"Found conversion candidate: {found_ppt}")
        convert_pptx_to_image(found_ppt, "renderer_test_output")
    else:
        print("No PPTX file found to test conversion. Please generate one first.")

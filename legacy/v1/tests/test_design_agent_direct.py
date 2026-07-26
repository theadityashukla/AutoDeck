#!/usr/bin/env python3
"""
Direct test of DesignAgent to see vision model output
"""
import sys
import os
sys.path.insert(0, '/Users/aditya/Documents/Codes/Projects/Gen AI assited Keynotes/AutoDeck')

from autodeck_core.agents.design_agent import DesignAgent

import glob

# Find most recent rendered slide
rendered_slides = glob.glob("/Users/aditya/Documents/Codes/Projects/Gen AI assited Keynotes/AutoDeck/rendered_slides/*.png")
if not rendered_slides:
    print("ERROR: No rendered slides found")
    print("Please render a slide first in the Streamlit app")
    sys.exit(1)

image_path = max(rendered_slides, key=os.path.getctime)
print(f"Using most recent slide: {image_path}")

agent = DesignAgent()

slide_content = {
    "title": "Test Slide",
    "bullet_points": ["Point 1", "Point 2", "Point 3"]
}

print("Calling DesignAgent.analyze_slide...")
result = agent.analyze_slide(image_path, slide_content)

print("\n" + "="*60)
print("FINAL RESULT:")
print("="*60)
print(result)

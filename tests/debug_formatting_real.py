
from autodeck_core.agents.formatting_agent import FormattingAgent
import logging
import sys

# Setup logging to stdout
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

print("Initializing FormattingAgent...")
try:
    agent = FormattingAgent()
    print("Agent initialized.")
except Exception as e:
    print(f"Failed to init agent: {e}")
    sys.exit(1)

test_content = {
    "title": "Pros and Cons of Remote Work",
    "bullet_points": ["Increased flexibility", "Reduced commute time", "Isolation", "Communication challenges"],
    "image_suggestion": "None"
}

print(f"Testing layout determination for: {test_content['title']}")
try:
    layout = agent.determine_layout(test_content)
    print("Layout Result:")
    print(layout)
except Exception as e:
    print(f"Error during determin_layout: {e}")

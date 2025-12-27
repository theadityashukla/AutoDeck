
from autodeck_core.agents.formatting_agent import FormattingAgent
import json
import logging
from unittest.mock import MagicMock

# Configure logger to print to console
logging.basicConfig(level=logging.INFO)

# Mock GemmaClient to avoid dependency issues during verification
class MockGemmaClient:
    def generate(self, prompt, max_tokens, temperature):
        if "Pros and Cons" in prompt:
            return '''```json
            {
                "layout_type": "two_column",
                "content_mapping": {
                    "left_points": ["Increased flexibility", "Reduced commute time"],
                    "right_points": ["Isolation", "Communication challenges"]
                }
            }
            ```'''
        elif "Structure determined by Content" in prompt: # Default fallback to a reasonable guess for others
             if "Quarterly Revenue" in prompt:
                 return '''```json
                 {
                    "layout_type": "big_stat",
                    "content_mapping": {
                        "stat": "$50M",
                        "description": "Total Revenue (20% YoY increase)"
                    }
                 }
                 ```'''
             else:
                 return '''```json
                 {
                    "layout_type": "standard_list",
                    "content_mapping": {
                        "main_bullets": ["Phase 1: Planning", "Phase 2: Execution"]
                    }
                 }
                 ```'''
        return "{}"

# Patch the agent's LLM
agent = FormattingAgent()
agent.llm = MockGemmaClient()

test_cases = [
    {
        "title": "Pros and Cons of Remote Work",
        "bullet_points": ["Increased flexibility", "Reduced commute time", "Isolation", "Communication challenges"]
    },
    {
        "title": "Quarterly Revenue Growth",
        "bullet_points": ["Total Revenue: $50M", "This represents a 20% YoY increase."]
    },
    {
        "title": "Project Phases",
        "bullet_points": ["Phase 1: Planning", "Phase 2: Execution", "Phase 3: Monitoring", "Phase 4: Closure"]
    }
]

for case in test_cases:
    print(f"\n--- Testing: {case['title']} ---")
    layout = agent.determine_layout(case)
    print(json.dumps(layout, indent=2))

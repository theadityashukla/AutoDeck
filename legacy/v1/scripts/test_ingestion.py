import sys
import os

# Ensure we can import from autodeck_core
sys.path.append(os.getcwd())

from autodeck_core.agents.ingestion_agent import IngestionAgent

def test_ingestion():
    print("Testing Ingestion Agent...")
    agent = IngestionAgent()
    
    # Use a sample PDF if available, or create a dummy one
    pdf_path = "0. Input Data/40265_2021_Article_1499.pdf"
    if not os.path.exists(pdf_path):
        print(f"PDF not found at {pdf_path}")
        return

    try:
        agent.ingest(pdf_path)
        print("Test passed!")
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_ingestion()

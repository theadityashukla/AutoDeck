import sys
import os

# Ensure we can import from autodeck_core
sys.path.append(os.getcwd())

from autodeck_core.ingestion.vector_store import VectorStore

def inspect():
    print("Connecting to Vector Store...")
    try:
        store = VectorStore()
        # Get all documents (limit to 10 for display)
        results = store.collection.get(limit=10)
        
        ids = results['ids']
        documents = results['documents']
        metadatas = results['metadatas']
        
        count = store.collection.count()
        print(f"Total chunks in database: {count}")
        
        if len(ids) == 0:
            print("No chunks found. The ingestion might have failed or is still running.")
        
        for i in range(len(ids)):
            print(f"\n--- Chunk {i+1} ---")
            print(f"ID: {ids[i]}")
            print(f"Metadata: {metadatas[i]}")
            print(f"Content Preview: {documents[i][:500]}...")
            print("-" * 50)

    except Exception as e:
        print(f"Error inspecting chunks: {e}")

if __name__ == "__main__":
    inspect()

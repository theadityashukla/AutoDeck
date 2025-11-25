from typing import List, Dict, Any
from autodeck_core.ingestion.vector_store import VectorStore

class RetrievalAgent:
    def __init__(self, collection_name: str = "autodeck_docs", persist_directory: str = "chroma_db"):
        self.vector_store = VectorStore(collection_name=collection_name, persist_directory=persist_directory)

    def retrieve(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieves relevant documents from the vector store based on the query.
        
        Args:
            query: The search query.
            k: Number of results to return.
            
        Returns:
            List of dictionaries containing content and metadata of retrieved chunks.
        """
        print(f"Retrieving top {k} results for query: '{query}'")
        results = self.vector_store.query(query_text=query, n_results=k)
        return results

if __name__ == "__main__":
    # Simple test
    agent = RetrievalAgent()
    results = agent.retrieve("oral semaglutide efficacy", k=2)
    for res in results:
        print(f"\nScore: {res.get('score', 'N/A')}") # Chroma might return distance
        print(f"Content: {res['content'][:200]}...")
        print(f"Metadata: {res['metadata']}")

from typing import List, Dict, Any
from autodeck_core.ingestion.vector_store import VectorStore

from autodeck_core.logger import setup_logger

class RetrievalAgent:
    def __init__(self, collection_name: str = "autodeck_docs", persist_directory: str = "chroma_db"):
        self.vector_store = VectorStore(collection_name=collection_name, persist_directory=persist_directory)
        self.logger = setup_logger("RetrievalAgent")

    def retrieve(self, query: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        Retrieves relevant documents from the vector store based on the query.
        
        Args:
            query: The search query.
            k: Number of results to return.
            
        Returns:
            List of dictionaries containing content and metadata of retrieved chunks.
        """
        self.logger.info(f"Retrieving top {k} results for query: '{query}'")
        results = self.vector_store.query(query_text=query, n_results=k)
        self.logger.info(f"Found {len(results)} matching documents")
        
        # Log details about retrieved documents
        for i, doc in enumerate(results, 1):
            metadata = doc.get('metadata', {})
            page_num = metadata.get('page_number', 'N/A')
            source = metadata.get('source', 'Unknown')
            content_preview = doc.get('content', '')[:80] + "..." if len(doc.get('content', '')) > 80 else doc.get('content', '')
            self.logger.info(f"  [{i}] Page {page_num} from {source}: {content_preview}")
        
        return results

if __name__ == "__main__":
    # Simple test
    agent = RetrievalAgent()
    results = agent.retrieve("oral semaglutide efficacy", k=2)
    for res in results:
        print(f"\nScore: {res.get('score', 'N/A')}") # Chroma might return distance
        print(f"Content: {res['content'][:200]}...")
        print(f"Metadata: {res['metadata']}")

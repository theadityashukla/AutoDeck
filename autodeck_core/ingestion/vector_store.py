import chromadb
from chromadb.config import Settings
from typing import List, Dict, Any
import uuid

class VectorStore:
    def __init__(self, collection_name: str = "autodeck_docs", persist_directory: str = "chroma_db"):
        self.client = chromadb.PersistentClient(path=persist_directory)
        self.collection = self.client.get_or_create_collection(name=collection_name)

    def add_documents(self, documents: List[Dict[str, Any]]):
        """
        Adds documents to the vector store.
        Each document should have 'content' and 'metadata'.
        """
        ids = [str(uuid.uuid4()) for _ in documents]
        documents_text = [doc['content'] for doc in documents]
        metadatas = [doc.get('metadata', {}) for doc in documents]
        
        self.collection.add(
            documents=documents_text,
            metadatas=metadatas,
            ids=ids
        )
        print(f"Added {len(documents)} documents to ChromaDB.")

    def query(self, query_text: str, n_results: int = 5) -> List[Dict[str, Any]]:
        results = self.collection.query(
            query_texts=[query_text],
            n_results=n_results
        )
        
        # Format results
        formatted_results = []
        if results['documents']:
            for i in range(len(results['documents'][0])):
                formatted_results.append({
                    "content": results['documents'][0][i],
                    "metadata": results['metadatas'][0][i],
                    "id": results['ids'][0][i]
                })
        return formatted_results

if __name__ == "__main__":
    store = VectorStore()
    print("VectorStore initialized")

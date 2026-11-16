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

    def get_existing_pages(self, source_filename: str) -> set:
        """
        Returns a set of page numbers that have already been ingested for the given file.
        """
        # We need to fetch all metadata for the given source
        # Chroma doesn't support "select distinct", so we fetch relevant metadata
        results = self.collection.get(
            where={"source": source_filename},
            include=["metadatas"]
        )
        
        existing_pages = set()
        if results['metadatas']:
            for meta in results['metadatas']:
                if 'page_number' in meta:
                    existing_pages.add(meta['page_number'])
        
        return existing_pages

if __name__ == "__main__":
    store = VectorStore()
    print("VectorStore initialized")

# defender/build_index.py
import chromadb
from chromadb.utils import embedding_functions
import pdfplumber
from pathlib import Path

def define_db(agent):
    chroma_client = chromadb.PersistentClient(path=f"./{agent}/chroma_db")
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    collection = chroma_client.get_or_create_collection("policy_corpus", embedding_function=ef)

    for pdf_path in Path(f"{agent}/corpus").glob("*.pdf"):
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                if text and len(text) > 100:
                    collection.add(
                        documents=[text],
                        metadatas=[{"source": pdf_path.name, "page": i}],
                        ids=[f"{pdf_path.stem}_p{i}"]
                    )
    print(f"Indexed {collection.count()} chunks")
# defender/agent.py
import google.generativeai as genai
import chromadb
from chromadb.utils import embedding_functions
from typing import TypedDict, List
from langgraph.graph import StateGraph, END
import os
import pdfplumber
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-3.5-flash")

# Absolute paths relative to THIS file — works from any cwd
BASE = Path(__file__).parent
CHROMA_PATH = BASE / "chroma_db"
CORPUS_DIR = BASE / "corpus"

def build_index():
    """Ingest corpus PDFs into ChromaDB. Safe to call repeatedly."""
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    collection = client.get_or_create_collection("policy_corpus", embedding_function=ef)

    existing = set(collection.get(include=[])["ids"])
    added = 0
    # rglob finds PDFs in subdirs like corpus/NPCI/UPI-Circulars/
    for pdf_path in CORPUS_DIR.rglob("*.pdf"):
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text()
                chunk_id = f"{pdf_path.stem}_p{i}"
                if text and len(text) > 100 and chunk_id not in existing:
                    collection.add(
                        documents=[text],
                        metadatas=[{"source": pdf_path.name, "page": i}],
                        ids=[chunk_id],
                    )
                    added += 1
    print(f"Indexed {collection.count()} chunks ({added} new)")
    return collection

def get_collection():
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    ef = embedding_functions.SentenceTransformerEmbeddingFunction(
        model_name="all-MiniLM-L6-v2"
    )
    return client.get_collection("policy_corpus", embedding_function=ef)

class DefenderState(TypedDict):
    transaction: dict
    policy_hits: List[dict]
    argument: str
    verdict: str

def make_retrieve(collection):
    def retrieve_policy(state: DefenderState) -> DefenderState:
        txn = state["transaction"]
        query = f"Fraud indicators for {txn['type']} transaction amount {txn['amount']} balance {txn['oldbalanceOrg']} to {txn['newbalanceOrig']}"
        results = collection.query(query_texts=[query], n_results=5)
        state["policy_hits"] = [
            {"text": doc, "source": meta["source"], "page": meta["page"]}
            for doc, meta in zip(results["documents"][0], results["metadatas"][0])
        ] if results["documents"] and results["documents"][0] else []
        return state
    return retrieve_policy

def make_generate_argument(model):
    def generate_argument(state: DefenderState) -> DefenderState:
        txn = state["transaction"]
        hits = "\n\n".join(
            f"[{h['source']} p{h['page']}] {h['text'][:600]}"
            for h in state["policy_hits"]
        )
        prompt = f"""You are a fraud prosecutor for a bank's UPI fraud review system.
Argue why this transaction should be flagged, grounded strictly in the cited policy text.

TRANSACTION:
{txn}

RELEVANT POLICY:
{hits if hits else "(no policy matches retrieved — argue from transaction facts only)"}

Structure your response as:
1. PRIMARY VIOLATION — the specific rule at stake
2. EVIDENCE — transaction facts supporting the violation
3. POLICY CITATIONS — quote from the policy text above
4. COUNTERFACTUAL — what single change would make this NOT suspicious

Be concise. Do not invent policy text."""
        response = model.generate_content(prompt)
        state["argument"] = response.text
        return state
    return generate_argument

def build_agent(collection, model):
    graph = StateGraph(DefenderState)
    graph.add_node("retrieve", make_retrieve(collection))
    graph.add_node("argue", make_generate_argument(model))
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "argue")
    graph.add_edge("argue", END)
    return graph.compile()

if __name__ == "__main__":
    build_index()                      # 1. index first
    collection = get_collection()      # 2. then read
    defender = build_agent(collection, model)

    test_txn = {
        "step": 1, "type": "CASH_OUT", "amount": 50000,
        "nameOrig": "C123", "oldbalanceOrg": 50000, "newbalanceOrig": 0,
        "nameDest": "C456", "oldbalanceDest": 0, "newbalanceDest": 0,
    }
    result = defender.invoke({"transaction": test_txn})
    print("\n" + "=" * 60)
    print(result["argument"])
    print("\nRetrieved policy sources:")
    for h in result["policy_hits"]:
        print(f"  - {h['source']} p{h['page']}")
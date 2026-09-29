# defender/agent.py
import google.generativeai as genai
import chromadb
from chromadb.utils import embedding_functions
from typing import TypedDict, List
from langgraph.graph import StateGraph, END
import os
from dotenv import load_dotenv
from Agents.build_index import define_db

define_db("defender")

load_dotenv()

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))  # or use env var
model = genai.GenerativeModel("gemini-1.5-flash")

chroma_client = chromadb.PersistentClient(path="./defender/chroma_db")
ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")
collection = chroma_client.get_collection("policy_corpus", embedding_function=ef)

class DefenderState(TypedDict):
    transaction: dict
    policy_hits: List[dict]
    argument: str
    verdict: str

def retrieve_policy(state: DefenderState) -> DefenderState:
    query = f"Fraud indicators for {state['transaction']['type']} transaction amount {state['transaction']['amount']}"
    results = collection.query(query_texts=[query], n_results=5)
    state["policy_hits"] = [
        {"text": doc, "source": meta["source"], "page": meta["page"]}
        for doc, meta in zip(results["documents"][0], results["metadatas"][0])
    ]
    return state

def generate_argument(state: DefenderState) -> DefenderState:
    txn = state["transaction"]
    hits = "\n\n".join([f"[{h['source']} p{h['page']}] {h['text'][:500]}" for h in state["policy_hits"]])
    
    prompt = f"""You are a fraud prosecutor. Argue why this transaction should be flagged.

TRANSACTION:
{txn}

RELEVANT POLICY:
{hits}

Structure your response:
1. PRIMARY VIOLATION - Specific rule violated
2. EVIDENCE - Transaction facts supporting violation  
3. POLICY CITATIONS - Exact policy references
4. COUNTERFACTUAL - What would make this NOT suspicious"""
    
    response = model.generate_content(prompt)
    state["argument"] = response.text
    return state

# Build graph
graph = StateGraph(DefenderState)
graph.add_node("retrieve", retrieve_policy)
graph.add_node("argue", generate_argument)
graph.set_entry_point("retrieve")
graph.add_edge("retrieve", "argue")
graph.add_edge("argue", END)

defender = graph.compile()

# Usage
if __name__ == "__main__":
    test_txn = {
        "step": 1, "type": "CASH_OUT", "amount": 50000,
        "nameOrig": "C123", "oldbalanceOrg": 50000, "newbalanceOrig": 0,
        "nameDest": "C456", "oldbalanceDest": 0, "newbalanceDest": 0
    }
    result = defender.invoke({"transaction": test_txn})
    print(result["argument"])
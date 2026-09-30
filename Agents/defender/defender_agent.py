"""Defender agent: retrieves policy grounding, then prosecutes the case."""
import os
from typing import TypedDict, List

import google.generativeai as genai
from langgraph.graph import StateGraph, END
from dotenv import load_dotenv

from Agents.build_index import get_collection

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

AGENT = "defender"
MODEL_CANDIDATES = [
    "gemini-3.5-flash",      # current stable
    "gemini-2.5-flash",      # GA until Oct 2026
    "gemini-2.5-flash-lite",
    "gemini-3.8-flash",
]


def resolve_model(candidates=MODEL_CANDIDATES):
    for name in candidates:
        try:
            m = genai.GenerativeModel(name)
            m.generate_content("ping")
            print(f"[{AGENT}] model: {name}")
            return m
        except Exception:
            print(f"[{AGENT}] {name} unavailable, trying next...")
    raise RuntimeError(
        f"No Gemini model available. Check GEMINI_API_KEY.\nTried: {candidates}"
    )


class DefenderState(TypedDict):
    transaction: dict
    policy_hits: List[dict]
    argument: str


def make_retrieve(collection):
    def retrieve_policy(state: DefenderState) -> DefenderState:
        txn = state["transaction"]
        query = (
            f"Fraud indicators for {txn['type']} transaction "
            f"amount {txn['amount']} "
            f"balance {txn['oldbalanceOrg']} -> {txn['newbalanceOrig']} "
            f"destination balance {txn['oldbalanceDest']} -> {txn['newbalanceDest']}"
        )
        results = collection.query(query_texts=[query], n_results=5)
        docs = results.get("documents") or [[]]
        metas = results.get("metadatas") or [[]]
        state["policy_hits"] = [
            {"text": d, "source": m.get("source"), "page": m.get("page")}
            for d, m in zip(docs[0], metas[0])
        ]
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
    # Precondition: run `python -m Agents.build_index defender` first
    collection = get_collection()
    defender = build_agent(collection, resolve_model())

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
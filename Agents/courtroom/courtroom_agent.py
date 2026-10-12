"""Courtroom Agent — three-role adversarial trial for a flagged transaction.

After the attacker/defender duel produces a suspicious transaction (or batch),
the Courtroom Agent conducts a structured argument:

  Prosecutor (uses defender's policy grounding)   → argues FOR flagging
  Defense      (uses attacker's evasion pattern)  → argues AGAINST flagging
  Judge        (synthesizes both + scorer output) → verdict + counterfactual

Output:
  {
    "verdict": "FRAUD" | "NOT FRAUD" | "ESCALATE",
    "confidence": 0.0-1.0,
    "prosecutor_argument": "...",
    "defense_argument": "...",
    "judge_reasoning": "...",
    "counterfactual": "If X were different (e.g., amount < threshold), this would not be flagged."
  }

Run:  python -m Agents.courtroom.courtroom_agent
"""
import json
import os
from typing import TypedDict, List, Optional, Literal

import google.generativeai as genai
from langgraph.graph import StateGraph, END
from dotenv import load_dotenv

from Agents.build_index import get_collection
from Agents.duel import duel_summary, recent_rounds
from Agents.attacker.attacker_agent import _json_text

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

AGENT = "courtroom"
MODEL_CANDIDATES = [
    "gemini-3.5-flash",      # current stable
    "gemini-2.5-flash",      # GA until Oct 2026
    "gemini-2.5-flash-lite",
    "gemini-3.8-flash",
]

VERDICTS = ["FRAUD", "NOT FRAUD", "ESCALATE"]

Verdict = Literal["FRAUD", "NOT FRAUD", "ESCALATE"]


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


class CourtState(TypedDict, total=False):
    transaction: dict
    scorer_output: dict           # {"fraud_probability": ..., "risk_level": ...}
    duel_history: str             # summary of attacker/defender rounds
    policy_hits: List[dict]       # relevant policy grounding
    prosecutor_argument: str
    defense_argument: str
    judge_reasoning: str
    verdict: Verdict
    confidence: float
    counterfactual: str


def make_retrieve(collection):
    def retrieve_policy(state: CourtState) -> CourtState:
        """Ground both sides in the same policy corpus."""
        if not collection:
            state["policy_hits"] = []
            return state
        txn = state["transaction"]
        query = (f"fraud indicators for {txn['type']} transaction amount {txn['amount']} "
                 f"balance patterns zero balance velocity limits chargeback rules")
        results = collection.query(query_texts=[query], n_results=5)
        docs = results.get("documents") or [[]]
        metas = results.get("metadatas") or [[]]
        state["policy_hits"] = [
            {"text": d, "source": m.get("source"), "page": m.get("page")}
            for d, m in zip(docs[0], metas[0])
        ]
        return state
    return retrieve_policy


def make_duel_summary():
    def summarize_duel(state: CourtState) -> CourtState:
        dsum = duel_summary()
        recents = recent_rounds(5)
        lines = []
        for r in recents:
            p = r.get("pattern", {})
            o = r.get("outcome", {})
            lines.append(
                f"Round {r['round']}: {p.get('name','?')} — "
                f"evasion: {p.get('evasion_idea','?')} — "
                f"outcome: {'caught' if o.get('evaluated') else 'unevaluated'}"
            )
        state["duel_history"] = (
            f"Duel summary: {dsum['rounds']} rounds, "
            f"{dsum['caught']} caught, {dsum['missed']} missed, "
            f"catch_rate: {dsum['catch_rate']}\n"
            + "\n".join(lines) if lines else "(no prior rounds)"
        )
        return state
    return summarize_duel


def make_prosecutor(model):
    def prosecute(state: CourtState) -> CourtState:
        txn = state["transaction"]
        scorer = state.get("scorer_output", {})
        hits = "\n\n".join(
            f"[{h['source']} p{h['page']}] {h['text'][:500]}"
            for h in state.get("policy_hits", [])
        )
        prompt = f"""You are the PROSECUTOR in a UPI fraud tribunal.
Argue WHY this transaction should be classified as FRAUD.

TRANSACTION:
{json.dumps(txn, indent=2)}

SCORER OUTPUT (first-pass gradient-boosted model):
fraud_probability: {scorer.get('fraud_probability', 'N/A')}
risk_level: {scorer.get('risk_level', 'N/A')}
is_fraud: {scorer.get('is_fraud', 'N/A')}

DUEL HISTORY (attacker vs defender):
{state.get('duel_history', 'none')}

POLICY CORPUS (cite exactly):
{hits if hits else "(no policy matches)"}

Make a concise, citation-heavy argument. Do NOT invent policy text.
Structure:
1. PRIMARY VIOLATION — which specific rule is breached
2. EVIDENCE — transaction facts matching the rule
3. POLICY CITATIONS — direct quotes
4. WHY DEFENSE WILL FAIL — preempt the likely defense argument"""
        state["prosecutor_argument"] = _json_text(model.generate_content(prompt))
        return state
    return prosecute


def make_defense(model):
    def defend(state: CourtState) -> CourtState:
        txn = state["transaction"]
        scorer = state.get("scorer_output", {})
        hits = "\n\n".join(
            f"[{h['source']} p{h['page']}] {h['text'][:500]}"
            for h in state.get("policy_hits", [])
        )
        prompt = f"""You are the DEFENSE COUNSEL in a UPI fraud tribunal.
Argue WHY this transaction should NOT be classified as FRAUD — it may be
unusual but legitimate, or the signals are ambiguous.

TRANSACTION:
{json.dumps(txn, indent=2)}

SCORER OUTPUT:
fraud_probability: {scorer.get('fraud_probability', 'N/A')}
risk_level: {scorer.get('risk_level', 'N/A')}

DUEL HISTORY (attacker's evasion patterns tested):
{state.get('duel_history', 'none')}

POLICY CORPUS (cite exactly):
{hits if hits else "(no policy matches)"}

Make a concise, citation-heavy argument. Do NOT invent policy text.
Structure:
1. LEGITIMATE EXPLANATION — why a real user might do this
2. INSUFFICIENT EVIDENCE — which fraud elements are NOT met
3. POLICY CITATIONS — rules that do NOT apply or have safe-harbor
4. WHY PROSECUTION OVERREACHES — rebut the likely prosecution points"""
        state["defense_argument"] = _json_text(model.generate_content(prompt))
        return state
    return defend


def make_judge(model):
    def judge(state: CourtState) -> CourtState:
        txn = state["transaction"]
        scorer = state.get("scorer_output", {})
        prompt = f"""You are the JUDGE in a UPI fraud tribunal.
You have heard both sides. Deliver a verdict with reasoning and a counterfactual.

TRANSACTION:
{json.dumps(txn, indent=2)}

SCORER OUTPUT:
fraud_probability: {scorer.get('fraud_probability', 'N/A')}
risk_level: {scorer.get('risk_level', 'N/A')}

PROSECUTOR ARGUMENT:
{state.get('prosecutor_argument', '')}

DEFENSE ARGUMENT:
{state.get('defense_argument', '')}

POLICY CORPUS (for reference):
{'\n\n'.join(f"[{h['source']} p{h['page']}] {h['text'][:400]}" for h in state.get('policy_hits', []))}

RESPOND IN JSON ONLY:
{{
  "verdict": "FRAUD" | "NOT FRAUD" | "ESCALATE",
  "confidence": 0.0-1.0,
  "reasoning": "concise synthesis: which arguments prevailed and why",
  "counterfactual": "If [specific change, e.g., amount were 4900 instead of 50000, or destination had prior balance > 0], this would NOT be flagged."
}}"""
        raw = _json_text(model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"},
        ))
        parsed = _parse_json(raw)
        if not parsed or "verdict" not in parsed:
            # Fallback: let scorer decide
            prob = float(scorer.get("fraud_probability", 0.5))
            if prob >= 0.7:
                parsed = {"verdict": "FRAUD", "confidence": prob}
            elif prob >= 0.3:
                parsed = {"verdict": "ESCALATE", "confidence": 1 - prob}
            else:
                parsed = {"verdict": "NOT FRAUD", "confidence": 1 - prob}
            parsed.setdefault("reasoning", "Fallback to scorer probability.")
            parsed.setdefault("counterfactual", "If fraud_probability were below 0.3, verdict would be NOT FRAUD.")
            print(f"[{AGENT}] WARN judge JSON unparseable, using scorer fallback")
        state["verdict"] = parsed["verdict"]
        state["confidence"] = float(parsed.get("confidence", 0.5))
        state["judge_reasoning"] = parsed.get("reasoning", "")
        state["counterfactual"] = parsed.get("counterfactual", "")
        return state
    return judge


def _parse_json(raw: str) -> Optional[dict]:
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def build_agent(collection, model):
    graph = StateGraph(CourtState)
    graph.add_node("retrieve", make_retrieve(collection))
    graph.add_node("duel_summary", make_duel_summary())
    graph.add_node("prosecute", make_prosecutor(model))
    graph.add_node("defend", make_defense(model))
    graph.add_node("judge", make_judge(model))
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "duel_summary")
    graph.add_edge("duel_summary", "prosecute")
    graph.add_edge("prosecute", "defend")
    graph.add_edge("defend", "judge")
    graph.add_edge("judge", END)
    return graph.compile()


def run_courtroom(transaction: dict, scorer_output: dict) -> dict:
    """Convenience function for pipeline integration."""
    try:
        collection = get_collection()
    except Exception as e:
        print(f"[{AGENT}] no policy index ({e}); continuing without policy")
        collection = None
    court = build_agent(collection, resolve_model())
    result = court.invoke({
        "transaction": transaction,
        "scorer_output": scorer_output,
    })
    return {
        "verdict": result["verdict"],
        "confidence": result["confidence"],
        "prosecutor_argument": result["prosecutor_argument"],
        "defense_argument": result["defense_argument"],
        "judge_reasoning": result["judge_reasoning"],
        "counterfactual": result["counterfactual"],
    }


if __name__ == "__main__":
    # Demo with the classic CASH_OUT drain pattern
    test_txn = {
        "step": 1, "type": "CASH_OUT", "amount": 50000,
        "nameOrig": "C123", "oldbalanceOrg": 50000, "newbalanceOrig": 0,
        "nameDest": "C456", "oldbalanceDest": 0, "newbalanceDest": 0,
    }
    test_scorer = {"fraud_probability": 0.87, "risk_level": "HIGH", "is_fraud": True}

    print(f"\n{'=' * 60}")
    print("COURTROOM TRIAL")
    print(f"{'=' * 60}")

    result = run_courtroom(test_txn, test_scorer)

    print(f"\nVERDICT: {result['verdict']} (confidence: {result['confidence']:.2f})")
    print(f"\nCOUNTERFACTUAL:\n{result['counterfactual']}")
    print(f"\nJUDGE REASONING:\n{result['judge_reasoning']}")
    print(f"\n--- PROSECUTOR ---\n{result['prosecutor_argument'][:800]}...")
    print(f"\n--- DEFENSE ---\n{result['defense_argument'][:800]}...")
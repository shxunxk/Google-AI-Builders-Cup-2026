"""Attacker agent — red-team half of the duel.

Reads what the defender has been catching, reasons about the detection signals
it is relying on, then proposes a NEW evasion pattern and emits synthetic
transactions that implement it. Those transactions are handed to the scorer;
whether they get caught becomes the feedback for the next round.

This is defensive red-teaming: the attacker only evades *our own* detector to
prove the detector can be hardened, and it targets fraud typologies that are
already documented in the shared policy corpus.

Run:  python -m Agents.attacker.attacker_agent
"""
import json
import os
from typing import TypedDict, List, Optional

import google.generativeai as genai
from langgraph.graph import StateGraph, END
from dotenv import load_dotenv

from Agents.build_index import get_collection
from Agents import duel

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

AGENT = "attacker"
MODEL_CANDIDATES = [
    "gemini-3.5-flash",      # current stable
    "gemini-2.5-flash",      # GA until Oct 2026
    "gemini-2.5-flash-lite",
    "gemini-3.8-flash",
]

N_TRANSACTIONS = 4
TXN_SCHEMA = {
    "type": "object",
    "properties": {
        "transactions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "step": {"type": "integer"},
                    "type": {"type": "string",
                             "enum": ["PAYMENT", "TRANSFER", "CASH_OUT",
                                      "CASH_IN", "DEBIT"]},
                    "amount": {"type": "number"},
                    "nameOrig": {"type": "string"},
                    "oldbalanceOrg": {"type": "number"},
                    "newbalanceOrig": {"type": "number"},
                    "nameDest": {"type": "string"},
                    "oldbalanceDest": {"type": "number"},
                    "newbalanceDest": {"type": "number"},
                },
                "required": ["step", "type", "amount", "nameOrig",
                             "oldbalanceOrg", "newbalanceOrig", "nameDest",
                             "oldbalanceDest", "newbalanceDest"],
            },
        }
    },
    "required": ["transactions"],
}


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


def _json_text(response) -> str:
    """response.text can be empty when the model spends its budget thinking."""
    text = response.text
    if text:
        return text
    for cand in getattr(response, "candidates", []) or []:
        parts = getattr(getattr(cand, "content", None), "parts", None) or []
        joined = "".join(getattr(p, "text", "") for p in parts)
        if joined.strip():
            return joined
    return ""


def _parse_json(raw: str):
    """Models sometimes wrap JSON in prose or fences despite response_mime_type."""
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


class AttackerState(TypedDict, total=False):
    history: str            # what earlier rounds did and whether they worked
    detection_signals: str  # signals the defender appears to rely on
    known_typologies: str   # relevant fraud typologies from the policy corpus
    pattern: dict           # the new evasion hypothesis
    transactions: List[dict]
    round_no: int


def make_review(model):
    def review_history(state: AttackerState) -> AttackerState:
        rounds = duel.recent_rounds(5)
        if not rounds:
            state["history"] = (
                "No prior rounds. This is the opening attack — establish a "
                "baseline evasion that a naive amount/balance heuristic should miss."
            )
            return state

        lines = []
        for r in rounds:
            p = r.get("pattern", {})
            o = r.get("outcome", {})
            verdict = (f"caught {o.get('caught')}/{o.get('total')}"
                       if o.get("evaluated") else "NOT YET SCORED")
            lines.append(
                f"- Round {r['round']}: {p.get('name', '?')} | evasion: "
                f"{p.get('evasion_idea', '?')} | target signal: "
                f"{p.get('targets_signal', '?')} | result: {verdict}"
            )
        missed = sum(1 for r in rounds if r.get("outcome", {}).get("missed", 0) > 0)
        state["history"] = (
            f"Recent rounds:\n" + "\n".join(lines) +
            f"\n\n{missed} of {len(rounds)} recent rounds had at least one "
            f"transaction slip past the scorer."
        )
        return state
    return review_history


def make_retrieve(collection):
    def retrieve_typologies(state: AttackerState) -> AttackerState:
        """Ground the attack in documented fraud patterns, not invented ones."""
        if not collection:
            state["known_typologies"] = "(no corpus index available)"
            return state
        query = ("mule account layering, money laundering pattern, digital arrest "
                 "scam, phishing credential theft, fraud indicators in account "
                 "behaviour, suspicious balance and velocity patterns")
        results = collection.query(query_texts=[query], n_results=4)
        docs = results.get("documents") or [[]]
        metas = results.get("metadatas") or [[]]
        if not docs[0]:
            state["known_typologies"] = "(no policy matches retrieved)"
            return state
        state["known_typologies"] = "\n\n".join(
            f"[{m.get('source')} p{m.get('page')}] {d[:500]}"
            for d, m in zip(docs[0], metas[0])
        )
        return state
    return retrieve_typologies


def make_analyze(model):
    def analyze_signals(state: AttackerState) -> AttackerState:
        prompt = f"""You are the red-team half of a fraud-detection research loop.
Your job is to find the WEAKEST POINT in an automated UPI fraud detector so the
defending team can harden it. This is authorized defensive testing of our own model.

HISTORY OF PAST ATTACKS:
{state.get('history', 'none')}

KNOWN DOCUMENTED FRAUD TYPOLOGIES (from policy corpus):
{state.get('known_typologies', 'none')}

Identify what the detector is most likely keying on. A first-pass gradient-boosted
scorer on UPI transactions typically leans on: transaction type, amount magnitude
relative to balance, whether an account is fully drained, and zeroed balances.

List the 3 signals it most depends on, and for each name the specific weakness —
the legitimate-looking way real fraud could still satisfy that signal.

Respond in plain text, no JSON."""
        state["detection_signals"] = _json_text(model.generate_content(prompt))
        return state
    return analyze_signals


def make_evolve(model):
    def evolve_pattern(state: AttackerState) -> AttackerState:
        prompt = f"""Propose the next evasion attack.

WHAT THE DETECTOR RELIES ON:
{state.get('detection_signals', 'unknown')}

HISTORY:
{state.get('history', 'none')}

CONSTRAINTS:
- Must be a real, documented fraud typology — not a fantasy attack.
- Must differ from every past round's evasion idea listed above.
- Must be a change to transaction STRUCTURE and AMOUNT/BALANCE TIMING only.
  Never propose modifying the scorer's code, thresholds, or weights.
- The whole point is that it may well get caught; a caught attack is a
  successful experiment that teaches the defender something.

Respond in JSON only:
{{
  "name": "short identifier, e.g. layering_via_low_amount_chain",
  "typology": "which documented fraud pattern this realises",
  "evasion_idea": "one sentence: how it avoids the detector's signal",
  "targets_signal": "which detector signal it tries to defeat",
  "rationale": "why a naive detector would miss this"
}}"""
        raw = _json_text(model.generate_content(
            prompt,
            generation_config={"response_mime_type": "application/json"},
        ))
        parsed = _parse_json(raw)
        if not parsed or "name" not in parsed:
            parsed = {
                "name": "layering_via_low_amount_chain",
                "typology": "mule account layering (fallback — model output unparseable)",
                "evasion_idea": "Split the transfer into sub-threshold amounts so no "
                                "single transaction looks large.",
                "targets_signal": "amount magnitude",
                "rationale": "Falls back to a documented layering pattern when the "
                             "model's JSON could not be parsed.",
            }
            print(f"[{AGENT}] WARN pattern JSON unparseable, using fallback")
        state["pattern"] = parsed
        return state
    return evolve_pattern


def make_generate(model):
    def generate_transactions(state: AttackerState) -> AttackerState:
        p = state["pattern"]
        prompt = f"""Emit {N_TRANSACTIONS} synthetic UPI transactions that implement this
evasion pattern, so we can test whether our detector catches them.

EVASION PATTERN:
name: {p.get('name')}
typology: {p.get('typology')}
idea: {p.get('evasion_idea')}

RULES for the transactions:
- Must be realistic and internally consistent.
- oldbalanceOrg - amount == newbalanceOrig (payer is debited exactly the amount).
- newbalanceDest - oldbalanceDest == amount (payee is credited exactly the amount).
- Vary the step number 1-744 and vary the amounts slightly across transactions.
- Use plausible account IDs like "C1000001234" and "M2000005678".
- These are SIMULATED records for red-team testing only.

Respond in JSON only, matching this shape:
{{"transactions": [ {{step, type, amount, nameOrig, oldbalanceOrg,
newbalanceOrig, nameDest, oldbalanceDest, newbalanceDest}}, ... ]}}"""
        raw = _json_text(model.generate_content(
            prompt,
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": TXN_SCHEMA,
            },
        ))
        parsed = _parse_json(raw)
        txns = (parsed or {}).get("transactions") or []
        txns = [t for t in txns if _is_consistent(t)]
        if not txns:
            txns = _fallback_transactions(p)
            print(f"[{AGENT}] WARN generated transactions unusable, using fallback")
        state["transactions"] = txns
        return state
    return generate_transactions


def _is_consistent(t: dict) -> bool:
    try:
        amt = float(t["amount"])
        return amt > 0 and abs(
            (float(t["oldbalanceOrg"]) - amt) - float(t["newbalanceOrig"])
        ) < 0.01 and abs(
            (float(t["newbalanceDest"]) - float(t["oldbalanceDest"])) - amt
        ) < 0.01
    except (KeyError, TypeError, ValueError):
        return False


def _fallback_transactions(pattern: dict) -> list[dict]:
    """Deterministic layering pattern, used only if generation fails."""
    out = []
    for i in range(N_TRANSACTIONS):
        amt = 4800.0 + i * 120          # sub-threshold-looking amounts
        out.append({
            "step": 30 + i * 3,
            "type": "TRANSFER",
            "amount": amt,
            "nameOrig": f"C100000{4000 + i}",
            "oldbalanceOrg": 30000.0,
            "newbalanceOrig": 30000.0 - amt,
            "nameDest": f"C100000{7000 + i}",
            "oldbalanceDest": 1000.0 + i,
            "newbalanceDest": 1000.0 + i + amt,
        })
    return out


def build_agent(collection, model):
    graph = StateGraph(AttackerState)
    graph.add_node("review", make_review(model))
    graph.add_node("retrieve", make_retrieve(collection))
    graph.add_node("analyze", make_analyze(model))
    graph.add_node("evolve", make_evolve(model))
    graph.add_node("generate", make_generate(model))
    graph.set_entry_point("review")
    graph.add_edge("review", "retrieve")
    graph.add_edge("retrieve", "analyze")
    graph.add_edge("analyze", "evolve")
    graph.add_edge("evolve", "generate")
    graph.add_edge("generate", END)
    return graph.compile()


def run_round(attacker) -> dict:
    """One attacker turn. Returns the persisted duel round."""
    result = attacker.invoke({})
    round_rec = duel.append_round(result["pattern"], result["transactions"])
    return round_rec


if __name__ == "__main__":
    try:
        collection = get_collection()
    except Exception as e:
        print(f"[{AGENT}] no policy index ({e}); continuing without typologies")
        collection = None

    attacker = build_agent(collection, resolve_model())

    print(f"\n{'=' * 60}")
    print("DUEL STATE BEFORE ATTACK")
    print(json.dumps(duel.duel_summary(), indent=2))

    rec = run_round(attacker)
    p = rec["pattern"]

    print(f"\n{'=' * 60}")
    print(f"ROUND {rec['round']} — {p.get('name')}")
    print(f"typology: {p.get('typology')}")
    print(f"evasion:  {p.get('evasion_idea')}")
    print(f"targets:  {p.get('targets_signal')}")
    print(f"\n{len(rec['transactions'])} synthetic transactions:")
    for t in rec["transactions"]:
        print(f"  {t['type']:9} {t['amount']:>10,.2f}  "
              f"{t['nameOrig']} -> {t['nameDest']}")

    print(f"\nNext: score them and record the outcome")
    print(f"  from Agents.duel import record_scores, next_round_number")
    print(f"  record_scores({rec['round']}, <scorer output>)")
    print(f"\nlog: {duel.DUEL_PATH}")
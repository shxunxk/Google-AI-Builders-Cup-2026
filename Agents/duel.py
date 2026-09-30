"""Shared duel-round store (stands in for Firestore).

The duel loop needs state that both the attacker and the defender read and
write: which attacks were tried, how the scorer rated them, and what the
defender argued. In production this is a Firestore collection; locally it is
a JSON file so the loop runs with no cloud dependency.

Round shape:
    {
      "round": 3,
      "ts": "2026-09-30T12:00:00Z",
      "pattern": {...attacker hypothesis...},
      "transactions": [...],
      "scores": [{...scorer output...}],
      "defender_args": [...],
      "outcome": {"caught": 2, "missed": 3, "evaluated": true}
    }
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

AGENTS_DIR = Path(__file__).parent
DUEL_PATH = AGENTS_DIR / "duel_rounds.json"

MISS_THRESHOLD = 0.5      # scorer proba >= this counts as caught


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_rounds() -> list[dict]:
    if not DUEL_PATH.exists():
        return []
    try:
        with open(DUEL_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        # A corrupt log must not stop the duel; start fresh.
        return []


def save_rounds(rounds: list[dict]) -> None:
    with open(DUEL_PATH, "w", encoding="utf-8") as f:
        json.dump(rounds, f, indent=2, ensure_ascii=False)


def recent_rounds(n: int = 5) -> list[dict]:
    """Most recent n rounds, oldest-first within the slice."""
    return load_rounds()[-n:]


def next_round_number() -> int:
    return len(load_rounds()) + 1


def append_round(pattern: dict, transactions: list[dict]) -> dict:
    rounds = load_rounds()
    r = {
        "round": next_round_number(),
        "ts": _now(),
        "pattern": pattern,
        "transactions": transactions,
        "scores": [],
        "defender_args": [],
        "outcome": {"evaluated": False, "caught": 0, "missed": 0},
    }
    rounds.append(r)
    save_rounds(rounds)
    return r


def record_scores(round_no: int, scores: list[dict]) -> dict:
    """Attach scorer output to a round and compute caught/missed."""
    rounds = load_rounds()
    for r in rounds:
        if r["round"] == round_no:
            r["scores"] = scores
            caught = sum(1 for s in scores
                         if float(s.get("fraud_probability", 0)) >= MISS_THRESHOLD)
            r["outcome"] = {
                "evaluated": True,
                "caught": caught,
                "missed": len(scores) - caught,
                "total": len(scores),
            }
            save_rounds(rounds)
            return r
    raise KeyError(f"round {round_no} not found")


def record_defender_args(round_no: int, arguments: list[str]) -> dict:
    rounds = load_rounds()
    for r in rounds:
        if r["round"] == round_no:
            r["defender_args"] = arguments
            save_rounds(rounds)
            return r
    raise KeyError(f"round {round_no} not found")


def duel_summary() -> dict:
    """Aggregate view — what the defender uses to decide what to harden."""
    rounds = load_rounds()
    total_caught = sum(r["outcome"].get("caught", 0) for r in rounds)
    total_missed = sum(r["outcome"].get("missed", 0) for r in rounds)
    evaluated = total_caught + total_missed
    # Missed = attack succeeded. Catch rate should fall over time as the
    # defender hardens; rising miss count is the story the demo needs to show.
    return {
        "rounds": len(rounds),
        "evaluated": evaluated,
        "caught": total_caught,
        "missed": total_missed,
        "catch_rate": round(total_caught / evaluated, 4) if evaluated else None,
        "unevaluated_rounds": [r["round"] for r in rounds
                               if not r["outcome"].get("evaluated")],
    }
"""FinCity Graph Engine — Cloud Run-compatible FastAPI application."""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from Agents.fincity.data_loader import (
    build_graph,
    compute_communities,
    get_fraud_rings,
    get_time_windows as make_time_windows,
    load_transactions,
)

logger = logging.getLogger(__name__)
app = FastAPI(title="FinCity Graph Engine", version="1.0.0")

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class GraphResponse(BaseModel):
    nodes: Dict[str, Any]
    edges: List[Dict[str, Any]]
    rings: List[Dict[str, Any]]
    stats: Dict[str, Any]


class TimeWindowResponse(BaseModel):
    windows: List[Dict[str, Any]]
    current: int


class FraudRingsResponse(BaseModel):
    rings: List[Dict[str, Any]]


class CaseFileResponse(BaseModel):
    account_id: str
    profile: Dict[str, Any]
    recent_outgoing: List[Dict[str, Any]]
    recent_incoming: List[Dict[str, Any]]
    fraud_rings: List[str]


class WorstTxnResponse(BaseModel):
    step: int
    type: str
    amount: float
    nameOrig: str
    nameDest: str
    isFraud: int
    orig_risk: float
    dest_risk: float
    risk_basis: str


_current_window = 0
_time_windows: List[tuple[int, int]] = []


def _ensure_time_windows() -> List[tuple[int, int]]:
    global _time_windows
    if not _time_windows:
        _time_windows = make_time_windows(load_transactions(), n_windows=20)
    return _time_windows


def _selected_window(index: Optional[int]) -> tuple[int, Optional[tuple[int, int]]]:
    global _current_window
    windows = _ensure_time_windows()
    if not windows:
        return 0, None
    if index is not None:
        _current_window = min(max(index, 0), len(windows) - 1)
    else:
        _current_window = min(_current_window, len(windows) - 1)
    return _current_window, windows[_current_window]


def _graph_for(
    min_txn_count: int,
    max_nodes: int,
    time_window_idx: Optional[int],
):
    index, window = _selected_window(time_window_idx)
    nodes, edges = build_graph(
        min_txn_count=min_txn_count,
        max_nodes=max_nodes,
        time_window=window,
    )
    return index, window, nodes, edges


@app.get("/")
async def index():
    """Serve the FinCity graph interface."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
async def health():
    return {"status": "healthy", "service": "FinCity Graph Engine"}


@app.get("/api/graph", response_model=GraphResponse)
def get_graph(
    min_txn_count: int = Query(1, ge=1),
    max_nodes: int = Query(500, ge=50, le=2000),
    time_window_idx: Optional[int] = Query(None, ge=0),
):
    """Return a bounded graph snapshot for one time window."""
    index, window, nodes, edges = _graph_for(
        min_txn_count, max_nodes, time_window_idx
    )
    rings = get_fraud_rings(nodes, edges)
    communities = compute_communities(nodes, edges)
    stats = {
        "num_nodes": len(nodes),
        "num_edges": len(edges),
        "num_communities": len(communities),
        "num_fraud_rings": len(rings),
        "current_window": index,
        "total_windows": len(_ensure_time_windows()),
        "window_range": window,
        "customer_nodes": sum(node["type"] == "customer" for node in nodes.values()),
        "merchant_nodes": sum(node["type"] == "merchant" for node in nodes.values()),
        "total_fraud_txns": sum(edge["fraud_count"] for edge in edges),
        "total_review_signals": sum(edge["review_count"] for edge in edges),
        "risk_basis": (
            "observed_label"
            if any(node["risk_basis"] == "observed_label" for node in nodes.values())
            else "review_heuristic"
        ),
    }
    return GraphResponse(nodes=nodes, edges=edges, rings=rings, stats=stats)


@app.get("/api/time-windows", response_model=TimeWindowResponse)
def get_time_windows_api():
    windows = _ensure_time_windows()
    current, _ = _selected_window(None)
    return TimeWindowResponse(
        windows=[
            {
                "index": index,
                "start": start,
                "end": end,
                "label": f"Step {start}–{end}",
            }
            for index, (start, end) in enumerate(windows)
        ],
        current=current,
    )


@app.post("/api/time-window/{idx}")
def set_time_window(idx: int):
    current, window = _selected_window(idx)
    if window is None:
        raise HTTPException(status_code=503, detail="No transaction time windows available")
    return {"current_window": current, "window": window}


@app.get("/api/fraud-rings", response_model=FraudRingsResponse)
def get_fraud_rings_api(
    min_fraud_rate: float = Query(0.3, ge=0, le=1),
    min_txn_count: int = Query(1, ge=1),
    max_nodes: int = Query(500, ge=50, le=2000),
    time_window_idx: Optional[int] = Query(None, ge=0),
):
    _, _, nodes, edges = _graph_for(min_txn_count, max_nodes, time_window_idx)
    return FraudRingsResponse(
        rings=get_fraud_rings(nodes, edges, min_fraud_rate=min_fraud_rate)
    )


@app.get("/api/case-file/{account_id}", response_model=CaseFileResponse)
def get_case_file(
    account_id: str,
    max_nodes: int = Query(500, ge=50, le=2000),
    time_window_idx: Optional[int] = Query(None, ge=0),
):
    """Return the account profile and its latest observed transactions."""
    _, window, nodes, edges = _graph_for(1, max_nodes, time_window_idx)
    if account_id not in nodes:
        raise HTTPException(status_code=404, detail="Account not found in this graph sample")

    df = load_transactions()
    if window:
        df = df.loc[df["step"].between(*window)]
    outgoing = df.loc[df["nameOrig"] == account_id].sort_values("step", ascending=False).head(20)
    incoming = df.loc[df["nameDest"] == account_id].sort_values("step", ascending=False).head(20)

    def transaction_records(frame: pd.DataFrame, other_account: str) -> List[dict]:
        fields = ["step", "type", "amount", other_account]
        if "isFraud" in frame.columns:
            fields.append("isFraud")
        records = frame[fields].rename(
            columns={other_account: "nameDest" if other_account == "nameDest" else "nameOrig"}
        ).to_dict("records")
        return [
            {
                key: (value.item() if hasattr(value, "item") else value)
                for key, value in record.items()
            }
            for record in records
        ]

    rings = get_fraud_rings(nodes, edges)
    account_rings = [ring["id"] for ring in rings if account_id in ring["nodes"]]
    return CaseFileResponse(
        account_id=account_id,
        profile=nodes[account_id],
        recent_outgoing=transaction_records(outgoing, "nameDest"),
        recent_incoming=transaction_records(incoming, "nameOrig"),
        fraud_rings=account_rings,
    )


def _worst_transaction(
    ring_id: str,
    min_txn_count: int,
    max_nodes: int,
    time_window_idx: Optional[int],
) -> tuple[dict, dict, dict]:
    _, window, nodes, edges = _graph_for(min_txn_count, max_nodes, time_window_idx)
    ring = next((item for item in get_fraud_rings(nodes, edges) if item["id"] == ring_id), None)
    if ring is None:
        raise HTTPException(status_code=404, detail="Ring not found in this time window")

    ring_nodes = set(ring["nodes"])
    transactions = load_transactions()
    if window:
        transactions = transactions.loc[transactions["step"].between(*window)]
    within_ring = transactions.loc[
        transactions["nameOrig"].isin(ring_nodes)
        & transactions["nameDest"].isin(ring_nodes)
    ]
    if within_ring.empty:
        raise HTTPException(status_code=404, detail="No transactions found in this ring")
    if "isFraud" in within_ring.columns:
        labeled = within_ring.loc[within_ring["isFraud"] == 1]
        if not labeled.empty:
            within_ring = labeled
    transaction = within_ring.nlargest(1, "amount").iloc[0].to_dict()
    result = {
        "step": int(transaction["step"]),
        "type": str(transaction["type"]),
        "amount": float(transaction["amount"]),
        "nameOrig": str(transaction["nameOrig"]),
        "nameDest": str(transaction["nameDest"]),
        "isFraud": int(transaction.get("isFraud", 0)),
        "orig_risk": float(nodes[transaction["nameOrig"]]["risk_score"]),
        "dest_risk": float(nodes[transaction["nameDest"]]["risk_score"]),
        "risk_basis": ring["risk_basis"],
    }
    return result, transaction, ring


@app.get("/api/worst-txn/{ring_id}", response_model=WorstTxnResponse)
def get_worst_txn(
    ring_id: str,
    min_txn_count: int = Query(1, ge=1),
    max_nodes: int = Query(500, ge=50, le=2000),
    time_window_idx: Optional[int] = Query(None, ge=0),
):
    """Select the highest-value labeled or review-worthy transaction in a ring."""
    result, _, _ = _worst_transaction(
        ring_id, min_txn_count, max_nodes, time_window_idx
    )
    return WorstTxnResponse(**result)


@app.post("/api/courtroom/{ring_id}")
async def open_courtroom(
    ring_id: str,
    min_txn_count: int = Query(1, ge=1),
    max_nodes: int = Query(500, ge=50, le=2000),
    time_window_idx: Optional[int] = Query(None, ge=0),
):
    """Run the Courtroom agents on the ring's highest-priority transaction."""
    transaction_result, transaction, _ = _worst_transaction(
        ring_id, min_txn_count, max_nodes, time_window_idx
    )
    try:
        from Agents.courtroom.courtroom_agent import run_courtroom
    except ImportError as error:
        logger.exception("Courtroom dependencies are unavailable")
        raise HTTPException(
            status_code=503,
            detail=f"Courtroom service dependencies are unavailable: {error}",
        ) from error

    probability = (
        max(transaction_result["orig_risk"], transaction_result["dest_risk"])
        if transaction_result["risk_basis"] == "observed_label"
        else None
    )
    scorer_output = {
        "fraud_probability": probability,
        "risk_level": (
            "HIGH" if probability >= 0.7
            else "MEDIUM" if probability >= 0.3
            else "LOW" if probability is not None
            else "UNSCORED"
        ),
        "is_fraud": bool(transaction_result["isFraud"]),
        "risk_basis": transaction_result["risk_basis"],
    }
    try:
        trial = await run_in_threadpool(run_courtroom, transaction, scorer_output)
    except RuntimeError as error:
        logger.exception("Courtroom model could not run")
        raise HTTPException(status_code=503, detail=str(error)) from error
    return {"transaction": transaction_result, "trial": trial}


@app.get("/api/stats")
def get_stats():
    _, _, nodes, edges = _graph_for(1, 500, None)
    rings = get_fraud_rings(nodes, edges)
    communities = compute_communities(nodes, edges)
    return {
        "total_accounts": len(nodes),
        "total_links": len(edges),
        "communities": len(communities),
        "fraud_rings": len(rings),
        "high_risk_accounts": sum(node["risk_score"] > 0.5 for node in nodes.values()),
        "customer_ratio": (
            sum(node["type"] == "customer" for node in nodes.values()) / len(nodes)
            if nodes else 0
        ),
    }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)

"""Build bounded, time-windowed account graphs from the local transaction data."""

from collections import defaultdict
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent.parent.parent / "data"
TRANSACTION_CSV = DATA_DIR / "transaction_data.csv"
DEFAULT_TRANSACTION_LIMIT = 100_000

_transactions: Optional[pd.DataFrame] = None


def _load_bigquery_transactions(limit: int) -> pd.DataFrame:
    table = os.environ["FINCITY_BIGQUERY_TABLE"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+", table):
        raise ValueError(
            "FINCITY_BIGQUERY_TABLE must be a fully qualified project.dataset.table identifier"
        )
    try:
        from google.cloud import bigquery
    except ImportError as error:
        raise RuntimeError(
            "BigQuery is configured but google-cloud-bigquery is not installed"
        ) from error

    client = bigquery.Client()
    query = f"""
        SELECT *
        FROM `{table}` TABLESAMPLE SYSTEM (10 PERCENT)
        LIMIT @row_limit
    """
    config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("row_limit", "INT64", limit)
        ]
    )
    rows = client.query(query, job_config=config).result()
    records = [dict(row.items()) for row in rows]
    if not records:
        raise RuntimeError(
            f"BigQuery sample returned no rows from {table}; verify the table and sample size"
        )
    return pd.DataFrame.from_records(records)


def load_transactions(limit: Optional[int] = None) -> pd.DataFrame:
    """Read only a bounded transaction sample; the source CSV can be very large."""
    global _transactions
    requested_limit = limit or int(
        os.environ.get("FINCITY_MAX_TRANSACTIONS", DEFAULT_TRANSACTION_LIMIT)
    )
    if _transactions is None or len(_transactions) < requested_limit:
        if os.environ.get("FINCITY_BIGQUERY_TABLE"):
            print(f"Loading a bounded BigQuery sample from {os.environ['FINCITY_BIGQUERY_TABLE']}...")
            _transactions = _load_bigquery_transactions(requested_limit)
        else:
            if not TRANSACTION_CSV.exists():
                raise FileNotFoundError(
                    f"FinCity transaction data not found: {TRANSACTION_CSV}; "
                    "set FINCITY_BIGQUERY_TABLE to use BigQuery"
                )
            print(f"Loading up to {requested_limit:,} FinCity transactions...")
            _transactions = pd.read_csv(TRANSACTION_CSV, nrows=requested_limit)
        print(f"Loaded {len(_transactions):,} transactions")
    return _transactions


def _window_transactions(time_window: Optional[Tuple[int, int]]) -> pd.DataFrame:
    df = load_transactions()
    if time_window is None:
        return df
    start, end = time_window
    return df.loc[df["step"].between(start, end)]


def build_graph(
    min_txn_count: int = 1,
    max_nodes: int = 500,
    time_window: Optional[Tuple[int, int]] = None,
) -> Tuple[Dict[str, dict], List[dict]]:
    """Aggregate a window into an account graph, retaining the most active nodes."""
    if min_txn_count < 1 or max_nodes < 1:
        raise ValueError("min_txn_count and max_nodes must be positive")

    df = _window_transactions(time_window)
    if df.empty:
        return {}, []

    # The checked-in source has no fraud labels. For that data, expose a transparent
    # review signal rather than presenting unsupervised transactions as confirmed fraud.
    has_labels = "isFraud" in df.columns and df["isFraud"].notna().all()
    amount_threshold = float(df["amount"].quantile(0.95))
    if has_labels:
        review_signal = df["isFraud"].fillna(0).astype(int)
    else:
        review_signal = (
            df["type"].isin(["TRANSFER", "CASH_OUT"])
            & (df["amount"] >= amount_threshold)
            & (df["oldbalanceOrg"] > 0)
            & (df["newbalanceOrig"] <= df["oldbalanceOrg"] * 0.1)
        ).astype(int)

    fraud_label = df["isFraud"].fillna(0).astype(int) if has_labels else 0
    work = df.assign(_review_signal=review_signal, _fraud_label=fraud_label)
    grouped = work.groupby(["nameOrig", "nameDest"], sort=False).agg(
        txn_count=("amount", "size"),
        total_amount=("amount", "sum"),
        avg_amount=("amount", "mean"),
        review_count=("_review_signal", "sum"),
        fraud_count=("_fraud_label", "sum"),
        first_step=("step", "min"),
        last_step=("step", "max"),
    ).reset_index()
    grouped = grouped.loc[grouped["txn_count"] >= min_txn_count]
    if grouped.empty:
        return {}, []

    metrics = defaultdict(lambda: {
        "outgoing_count": 0,
        "incoming_count": 0,
        "outgoing_amount": 0.0,
        "incoming_amount": 0.0,
        "review_outgoing": 0,
        "review_incoming": 0,
        "fraud_outgoing": 0,
        "fraud_incoming": 0,
    })
    for row in grouped.itertuples(index=False):
        source, target = str(row.nameOrig), str(row.nameDest)
        metrics[source]["outgoing_count"] += int(row.txn_count)
        metrics[source]["outgoing_amount"] += float(row.total_amount)
        metrics[source]["review_outgoing"] += int(row.review_count)
        metrics[source]["fraud_outgoing"] += int(row.fraud_count)
        metrics[target]["incoming_count"] += int(row.txn_count)
        metrics[target]["incoming_amount"] += float(row.total_amount)
        metrics[target]["review_incoming"] += int(row.review_count)
        metrics[target]["fraud_incoming"] += int(row.fraud_count)

    ranked = sorted(
        metrics,
        key=lambda account: (
            metrics[account]["outgoing_count"] + metrics[account]["incoming_count"],
            metrics[account]["review_outgoing"] + metrics[account]["review_incoming"],
        ),
        reverse=True,
    )
    seed_count = min(len(ranked), max(1, max_nodes // 4))
    keep = set(ranked[:seed_count])
    neighbor_map = defaultdict(list)
    for row in grouped.itertuples(index=False):
        source, target = str(row.nameOrig), str(row.nameDest)
        priority = (int(row.review_count), int(row.txn_count), float(row.total_amount))
        neighbor_map[source].append((target, priority))
        neighbor_map[target].append((source, priority))
    for neighbors in neighbor_map.values():
        neighbors.sort(key=lambda item: item[1], reverse=True)

    queue = list(keep)
    visited = set()
    while queue and len(keep) < max_nodes:
        account = queue.pop(0)
        if account in visited:
            continue
        visited.add(account)
        for neighbor, _ in neighbor_map[account]:
            if neighbor in keep:
                continue
            keep.add(neighbor)
            queue.append(neighbor)
            if len(keep) >= max_nodes:
                break

    if len(keep) < max_nodes:
        keep.update(account for account in ranked if len(keep) < max_nodes)

    balance_rows = pd.concat([
        df[["nameOrig", "newbalanceOrig"]].rename(
            columns={"nameOrig": "account_id", "newbalanceOrig": "balance"}
        ),
        df[["nameDest", "newbalanceDest"]].rename(
            columns={"nameDest": "account_id", "newbalanceDest": "balance"}
        ),
    ]).drop_duplicates("account_id", keep="last")
    balances = dict(zip(balance_rows["account_id"], balance_rows["balance"]))

    nodes: Dict[str, dict] = {}
    for account in keep:
        metric = metrics[account]
        outgoing = metric["outgoing_count"]
        incoming = metric["incoming_count"]
        transaction_count = outgoing + incoming
        review_count = metric["review_outgoing"] + metric["review_incoming"]
        nodes[account] = {
            "id": account,
            "type": "customer" if account.startswith("C") else (
                "merchant" if account.startswith("M") else "unknown"
            ),
            "balance": float(balances.get(account, 0) or 0),
            "outgoing_count": outgoing,
            "incoming_count": incoming,
            "outgoing_amount": metric["outgoing_amount"],
            "incoming_amount": metric["incoming_amount"],
            "review_outgoing": metric["review_outgoing"],
            "review_incoming": metric["review_incoming"],
            "fraud_outgoing": metric["fraud_outgoing"],
            "fraud_incoming": metric["fraud_incoming"],
            "total_txns": transaction_count,
            "risk_score": review_count / max(1, transaction_count),
            "risk_basis": "observed_label" if has_labels else "review_heuristic",
        }

    edges: List[dict] = []
    for row in grouped.itertuples(index=False):
        source, target = str(row.nameOrig), str(row.nameDest)
        if source not in keep or target not in keep:
            continue
        transaction_count = int(row.txn_count)
        review_count = int(row.review_count)
        fraud_count = int(row.fraud_count)
        edges.append({
            "source": source,
            "target": target,
            "weight": transaction_count,
            "txn_count": transaction_count,
            "total_amount": float(row.total_amount),
            "avg_amount": float(row.avg_amount),
            "review_count": review_count,
            "review_rate": review_count / max(1, transaction_count),
            "fraud_count": fraud_count,
            "fraud_rate": fraud_count / max(1, transaction_count),
            "first_step": int(row.first_step),
            "last_step": int(row.last_step),
        })
    return nodes, edges


def get_time_windows(
    df: pd.DataFrame, n_windows: int = 20
) -> List[Tuple[int, int]]:
    """Split the loaded transaction steps into non-empty, inclusive windows."""
    if df.empty or n_windows < 1:
        return []
    steps = np.sort(df["step"].dropna().unique())
    if not len(steps):
        return []
    chunks = np.array_split(steps, min(n_windows, len(steps)))
    return [(int(chunk[0]), int(chunk[-1])) for chunk in chunks if len(chunk)]


def compute_communities(
    nodes: Dict[str, dict],
    edges: List[dict],
    min_community_size: int = 3,
) -> List[List[str]]:
    """Find connected components among high-activity or review-signal edges."""
    weights = [edge["weight"] for edge in edges]
    threshold = float(np.percentile(weights, 75)) if weights else 1
    adjacency = defaultdict(set)
    for edge in edges:
        if edge["weight"] >= threshold or edge["review_count"] > 0:
            source, target = edge["source"], edge["target"]
            adjacency[source].add(target)
            adjacency[target].add(source)

    visited = set()
    communities = []
    for start in nodes:
        if start in visited:
            continue
        queue = [start]
        component = set()
        while queue:
            node = queue.pop()
            if node in visited:
                continue
            visited.add(node)
            component.add(node)
            queue.extend(adjacency[node] - visited)
        if len(component) >= min_community_size:
            communities.append(sorted(component))
    return sorted(communities, key=lambda component: (-len(component), component[0]))


def get_fraud_rings(
    nodes: Dict[str, dict],
    edges: List[dict],
    min_fraud_rate: float = 0.3,
) -> List[dict]:
    """Return review-worthy connected components, not claims of confirmed fraud."""
    rings = []
    for component in compute_communities(nodes, edges):
        members = set(component)
        internal_edges = [
            edge for edge in edges
            if edge["source"] in members and edge["target"] in members
        ]
        if not internal_edges:
            continue
        total_review = sum(edge["review_count"] for edge in internal_edges)
        total_fraud = sum(edge["fraud_count"] for edge in internal_edges)
        total_txns = sum(edge["txn_count"] for edge in internal_edges)
        signal_rate = total_review / max(1, total_txns)
        if signal_rate < min_fraud_rate and total_review == 0:
            continue
        ring_nodes = [nodes[node] for node in component]
        rings.append({
            "nodes": component,
            "size": len(component),
            "internal_edges": len(internal_edges),
            "total_review_signals": total_review,
            "total_fraud_txns": total_fraud,
            "total_txns": total_txns,
            "signal_rate": signal_rate,
            "fraud_rate": total_fraud / max(1, total_txns),
            "avg_risk": float(np.mean([node["risk_score"] for node in ring_nodes])),
            "customer_count": sum(node["type"] == "customer" for node in ring_nodes),
            "merchant_count": sum(node["type"] == "merchant" for node in ring_nodes),
            "risk_basis": (
                "observed_label"
                if any(node["risk_basis"] == "observed_label" for node in ring_nodes)
                else "review_heuristic"
            ),
        })
    rings.sort(
        key=lambda ring: (-ring["signal_rate"], -ring["size"], ring["nodes"][0])
    )
    for index, ring in enumerate(rings, start=1):
        ring["id"] = f"ring_{index}"
    return rings
